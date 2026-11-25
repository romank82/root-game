"""Откат батча выплат (шаг 5).

Два сценария, оба нужны:

  1. Админ откатывает батч вручную (ошибся батчем, кошелёк не тот).
  2. Авто-откат по таймауту: батч висит в processing дольше
     ton.payout_processing_timeout_hours — деньги игрока нельзя держать вечно.

Два режима отката заявки:
  * return_to_pending — заявка ждёт следующего батча, холд НЕ возвращается
    (деньги всё ещё зарезервированы под вывод, игрок не получил их обратно);
  * fail_and_refund — заявка 'failed' + холд возвращается игроку.

Ключевой инвариант: CONFIRMED заявки не откатываются никогда. Если батч
подтверждён частично, откат трогает только processing — иначе можно вернуть
игроку деньги, которые уже ушли в блокчейн.

Вторая ловушка: PayoutAttempt со статусом 'sending' блокирует новую попытку
через частичный unique-индекс uq_payout_attempts_no_second_send. Поэтому при
возврате в pending попытка помечается 'failed' — иначе заявка навсегда
застрянет и в следующий батч не попадёт.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.mission_engine import MissionEngineError
from app.models import PayoutAttempt, PayoutBatch, WithdrawalRequest
from app.withdrawal_service import (
    PAYOUT_ATTEMPT_ACTIVE_STATUSES,
    PAYOUT_ATTEMPT_FAILED,
    _refund_withdrawal_hold,
    _utcnow,
)

logger = logging.getLogger(__name__)

BATCH_STATUS_ROLLED_BACK = "rolled_back"
BATCH_STATUS_CONFIRMED = "confirmed"

# Режимы отката.
MODE_RETURN_TO_PENDING = "return_to_pending"
MODE_FAIL_AND_REFUND = "fail_and_refund"
ROLLBACK_MODES = (MODE_RETURN_TO_PENDING, MODE_FAIL_AND_REFUND)

TIMEOUT_SETTING_KEY = "ton.payout_processing_timeout_hours"
DEFAULT_TIMEOUT_HOURS = 24

# Максимальная длина причины (колонка Text, но логи/UI не любят простыни).
MAX_REASON_LENGTH = 500


class BatchRollbackError(MissionEngineError):
    """Ошибка отката с привязкой к HTTP-статусу."""


def _read_timeout_hours(session: Session) -> int:
    """Таймаут обработки из CMS; при мусоре — дефолт, а не падение."""
    from app.models import SystemSetting

    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == TIMEOUT_SETTING_KEY,
            SystemSetting.status == "active",
        )
    )
    value = getattr(setting, "value_json", None)
    try:
        hours = int(value)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_HOURS
    return hours if hours > 0 else DEFAULT_TIMEOUT_HOURS


def rollback_payout_batch(
    batch_id: str,
    reason: str,
    mode: str = MODE_RETURN_TO_PENDING,
    admin_id: str | None = None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Откатить батч: processing-заявки вернуть в pending или провалить.

    force=True — откатить даже частично подтверждённый батч (confirmed
    заявки всё равно не трогаются). Без force частично подтверждённый батч
    откатывать нельзя: подтверждённые деньги уже ушли, а откат остатка
    лучше делать осознанно.

    Возвращает:
      {batchId, status, mode, returned, failed, skippedConfirmed, reason}
    """
    if mode not in ROLLBACK_MODES:
        raise BatchRollbackError(
            422,
            "mode должен быть одним из: " + ", ".join(ROLLBACK_MODES),
        )
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise BatchRollbackError(422, "Причина отката обязательна.")
    clean_reason = clean_reason[:MAX_REASON_LENGTH]

    returned: list[str] = []
    failed: list[str] = []
    skipped_confirmed: list[str] = []

    with SessionLocal.begin() as session:
        batch = session.scalar(
            select(PayoutBatch)
            .where(PayoutBatch.id == batch_id)
            .with_for_update()
        )
        if batch is None:
            raise BatchRollbackError(404, "Батч не найден.")
        if batch.status == BATCH_STATUS_CONFIRMED:
            raise BatchRollbackError(
                409, "Батч подтверждён: откат невозможен."
            )
        if batch.status == BATCH_STATUS_ROLLED_BACK:
            raise BatchRollbackError(409, "Батч уже откачен.")

        rows = list(
            session.execute(
                select(WithdrawalRequest, PayoutAttempt)
                .outerjoin(
                    PayoutAttempt,
                    PayoutAttempt.withdrawal_id == WithdrawalRequest.id,
                )
                .where(WithdrawalRequest.batch_id == batch_id)
                .order_by(WithdrawalRequest.created_at, WithdrawalRequest.id)
                .with_for_update(of=WithdrawalRequest)
            ).all()
        )

        has_confirmed = any(
            withdrawal.status == "confirmed" for withdrawal, _ in rows
        )
        if has_confirmed and not force:
            raise BatchRollbackError(
                409,
                "Батч подтверждён частично: оплаченные заявки не откатываются. "
                "Повторите с force=true, чтобы вернуть только неоплаченные.",
            )

        for withdrawal, attempt in rows:
            if withdrawal.status == "confirmed":
                # Деньги ушли в блокчейн — не трогаем ни при каких условиях.
                skipped_confirmed.append(withdrawal.id)
                continue
            if withdrawal.status not in ("processing", "approved"):
                # pending/failed/rejected — откатывать нечего.
                continue

            if mode == MODE_FAIL_AND_REFUND:
                withdrawal.status = "failed"
                withdrawal.reason = clean_reason
                _refund_withdrawal_hold(session, withdrawal)
                failed.append(withdrawal.id)
            else:
                withdrawal.status = "pending"
                withdrawal.batch_id = None
                returned.append(withdrawal.id)

            if admin_id is not None:
                withdrawal.admin_id = admin_id

            # Попытка закрывается 'failed' в обоих режимах: АКТИВНАЯ попытка
            # (sending ИЛИ sent) держит частичный unique-индекс
            # uq_payout_attempts_no_second_send и не дала бы создать новую
            # попытку в следующем батче.
            #
            # Раньше закрывалась только 'sending'. На проде это дало 500 при
            # сборке нового батча: после неудачной оплаты попытка была 'sent',
            # откат её не тронул, и INSERT новой попытки падал с
            # UniqueViolation по uq_payout_attempts_no_second_send.
            if attempt is not None and attempt.status in PAYOUT_ATTEMPT_ACTIVE_STATUSES:
                attempt.status = PAYOUT_ATTEMPT_FAILED
                attempt.error = f"Rollback: {clean_reason}"[:1000]

        batch.status = BATCH_STATUS_ROLLED_BACK
        batch.rollback_reason = clean_reason
        batch.terminal_at = _utcnow()
        session.flush()

    logger.info(
        "Batch %s rolled back (mode=%s): %d returned, %d failed, "
        "%d confirmed skipped",
        batch_id,
        mode,
        len(returned),
        len(failed),
        len(skipped_confirmed),
    )

    return {
        "batchId": batch_id,
        "status": BATCH_STATUS_ROLLED_BACK,
        "mode": mode,
        "returned": returned,
        "failed": failed,
        "skippedConfirmed": skipped_confirmed,
        "reason": clean_reason,
    }


def rollback_stale_processing(batch_id: str) -> dict[str, Any] | None:
    """Авто-откат просроченного батча: истёк таймаут processing.

    Возвращает результат отката или None, если батч не просрочен либо
    не в подходящем статусе. Заявки возвращаются в pending (НЕ failed):
    деньги игрока остаются зарезервированными, заявка просто ждёт нового
    батча. Возврат холда — осознанное решение админа, не автомат.
    """
    with SessionLocal() as session:
        batch = session.get(PayoutBatch, batch_id)
        if batch is None:
            return None
        if batch.status not in ("ready", "submitted"):
            return None
        timeout_hours = _read_timeout_hours(session)
        opened_at = batch.opened_at
        if opened_at is None:
            return None
        now = _utcnow()
        # opened_at из SQLite приходит naive: приводим к таймзоне now, иначе
        # вычитание aware - naive падает.
        if opened_at.tzinfo is None and now.tzinfo is not None:
            opened_at = opened_at.replace(tzinfo=now.tzinfo)
        age_hours = (now - opened_at).total_seconds() / 3600
        if age_hours < timeout_hours:
            return None

    logger.warning(
        "Batch %s просрочен (%.1f ч > %d ч): авто-откат в pending",
        batch_id,
        age_hours,
        timeout_hours,
    )
    return rollback_payout_batch(
        batch_id,
        reason=(
            f"Авто-откат: батч не подтверждён за {timeout_hours} ч "
            "(ton.payout_processing_timeout_hours)."
        ),
        mode=MODE_RETURN_TO_PENDING,
        admin_id=None,
        force=True,
    )


def rollback_all_stale_batches() -> list[dict[str, Any]]:
    """Пройти по открытым батчам и откатить просроченные (для планировщика).

    Вызывается из фонового джоба; безопасен в нескольких воркерах: откат
    идёт под блокировкой строки батча, второй воркер увидит
    status='rolled_back' и ничего не сделает.
    """
    from app.payout_batch_service import BATCH_OPEN_STATUSES

    with SessionLocal() as session:
        batch_ids = list(
            session.scalars(
                select(PayoutBatch.id).where(
                    PayoutBatch.status.in_(BATCH_OPEN_STATUSES)
                )
            ).all()
        )

    results: list[dict[str, Any]] = []
    for batch_id in batch_ids:
        try:
            result = rollback_stale_processing(batch_id)
        except MissionEngineError as error:
            # Гонка: другой воркер уже откатил/подтвердил — это норма.
            logger.info("Batch %s skipped during stale rollback: %s",
                        batch_id, error.detail)
            continue
        if result is not None:
            results.append(result)
    return results
