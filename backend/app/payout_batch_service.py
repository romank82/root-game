"""Формирование батчей выплат для оплаты внешним кошельком (TON Connect).

Заменяет автоматическую отправку (send_jetton_transfer): сервер только готовит
данные — список заявок с уникальными query_id, — а подписывает владелец игры
на своём устройстве.

Инварианты:
  * один открытый батч на систему (барьер — частичный unique-индекс в БД);
  * заявки уходят из pending в processing в той же транзакции, что и создание
    батча: иначе между выборкой и записью игрок мог бы отменить заявку, и она
    попала бы в батч дважды;
  * каждая заявка получает PayoutAttempt(sending) со своим query_id — по нему
    потом сверяется блокчейн;
  * повторный вызов при открытом батче возвращает существующий батч, а не
    создаёт второй.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.mission_engine import MissionEngineError
from app.models import (
    GamePlayer,
    PayoutAttempt,
    PayoutBatch,
    PlayerRestriction,
    WithdrawalRequest,
)
from app.withdrawal_service import (
    NANO_PER_ROOT,
    PAYOUT_ATTEMPT_ACTIVE_STATUSES,
    PAYOUT_ATTEMPT_SENDING,
    _new_id,
    _new_payout_query_id,
    _utcnow,
)

logger = logging.getLogger(__name__)

BATCH_STATUS_READY = "ready"
BATCH_STATUS_SUBMITTED = "submitted"
BATCH_STATUS_CONFIRMED = "confirmed"
BATCH_STATUS_ROLLED_BACK = "rolled_back"

# Все допустимые статусы батча (зеркало CHECK-констрейнта в БД).
# Кэш jetton-кошелька отправителя: адрес стабилен, а запрос к TON API
# небесплатный. Пустая строка — «вычисляли, не получилось».
_SENDER_JETTON_CACHE: str | None = None

BATCH_STATUSES = (
    BATCH_STATUS_READY,
    BATCH_STATUS_SUBMITTED,
    BATCH_STATUS_CONFIRMED,
    BATCH_STATUS_ROLLED_BACK,
)

# Статусы батча, в которых он считается «открытым» (инвариант в БД).
BATCH_OPEN_STATUSES = (BATCH_STATUS_READY, BATCH_STATUS_SUBMITTED)

# Лимит заявок в батче: предохранитель от гигантских списков.
BATCH_MAX_ITEMS = 200


def _open_batch(session: Session) -> PayoutBatch | None:
    """Текущий открытый батч (ready/submitted) или None."""
    return session.scalar(
        select(PayoutBatch).where(PayoutBatch.status.in_(BATCH_OPEN_STATUSES))
    )


def _pending_withdrawal_ids(session: Session, limit: int) -> list[str]:
    """Кандидаты: pending-заявки без активного restriction на вывод.

    Тот же фильтр, что был в process_withdrawal_batch: restricted-игроки в
    батч не попадают, чтобы ограничение нельзя было обойти массовой выплатой.
    """
    restricted = select(PlayerRestriction.player_id).where(
        PlayerRestriction.restriction_type == "withdrawal_restricted",
        PlayerRestriction.status == "active",
    )
    return list(
        session.scalars(
            select(WithdrawalRequest.id)
            .where(
                WithdrawalRequest.status == "pending",
                WithdrawalRequest.player_id.not_in(restricted),
            )
            .order_by(WithdrawalRequest.created_at, WithdrawalRequest.id)
            .limit(limit)
        ).all()
    )


def _build_payload_text(
    session: Session, withdrawals: list[WithdrawalRequest]
) -> str:
    """Человекочитаемый список для проверки глазами (не для парсинга).

    Формат: адрес, сумма ROOT, query_id. Используется как снимок содержимого
    батча в истории и для сверки вручную, если понадобится.
    """
    lines: list[str] = []
    for withdrawal in withdrawals:
        amount_nano = withdrawal.amount_root_nano or (
            withdrawal.amount_root * NANO_PER_ROOT
        )
        amount = amount_nano / NANO_PER_ROOT
        lines.append(
            f"{withdrawal.to_address},{amount:g},{withdrawal.id}"
        )
    return "\n".join(lines)


def _serialize_item(
    withdrawal: WithdrawalRequest,
    query_id: str | None,
    jetton_wallet: str | None = None,
    nickname: str | None = None,
) -> dict[str, Any]:
    """Заявка в ответе админке: всё, что нужно фронту для TON Connect.

    jettonWallet — адрес jetton-кошелька получателя: переводить ROOT нужно
    на него, а не на обычный адрес игрока. None означает «не удалось
    определить» (нет TON API) — фронт в этом случае блокирует оплату.

    nickname — читаемый логин вида «roman#491-773-811». player_id в базе
    админу ничего не говорит (по нему игрока не найти), поэтому в интерфейсе
    показывается ник, и он ведёт в карточку игрока.
    """
    amount_nano = withdrawal.amount_root_nano or (
        withdrawal.amount_root * NANO_PER_ROOT
    )
    return {
        "withdrawalId": withdrawal.id,
        "playerId": withdrawal.player_id,
        "playerNickname": nickname,
        "toAddress": withdrawal.to_address,
        "jettonWallet": jetton_wallet,
        "amountRoot": withdrawal.amount_root,
        "amountRootNano": amount_nano,
        "queryId": query_id,
        "status": withdrawal.status,
    }


def _serialize_batch(
    batch: PayoutBatch, items: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    return {
        "batchId": batch.id,
        "status": batch.status,
        "totalNano": batch.total_nano,
        "totalRoot": (batch.total_nano or 0) / NANO_PER_ROOT,
        "itemCount": len(items) if items is not None else None,
        "openedAt": batch.opened_at.isoformat() if batch.opened_at else None,
        "txHash": batch.tx_hash,
        "payloadText": batch.payload_text,
        "items": items,
    }


def serialize_batch_row(batch: PayoutBatch, item_count: int) -> dict[str, Any]:
    """Краткая строка для списка батчей (без списка заявок)."""
    total_nano = batch.total_nano or 0
    opened = batch.opened_at
    age_days = None
    if opened is not None:
        age_days = max(0, (_utcnow() - opened).days)
    return {
        "batchId": batch.id,
        "status": batch.status,
        "totalNano": total_nano,
        "totalRoot": total_nano / NANO_PER_ROOT,
        "itemCount": item_count,
        "openedAt": opened.isoformat() if opened else None,
        "ageDays": age_days,
        # Батч «на оплату» висит дольше двух дней — стоит подсветить в UI.
        "stale": batch.status in BATCH_OPEN_STATUSES
        and age_days is not None
        and age_days >= 2,
        "txHash": batch.tx_hash,
        "rollbackReason": batch.rollback_reason,
    }


def get_payout_batch(
    batch_id: str, resolve_wallets: bool = True
) -> dict[str, Any]:
    """Детали одного батча: заявки с query_id и jetton-wallet для оплаты.

    resolve_wallets=False — не ходить в TON API (для тестов и для случаев,
    когда нужен только список заявок без оплаты).
    """
    with SessionLocal() as session:
        batch = session.get(PayoutBatch, batch_id)
        if batch is None:
            raise MissionEngineError(404, "Батч не найден.")
        rows = session.execute(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.batch_id == batch_id)
            .order_by(WithdrawalRequest.created_at, WithdrawalRequest.id)
        ).scalars().all()
        addresses = sorted({row.to_address for row in rows})

    wallets: dict[str, str | None] = {}
    if resolve_wallets and addresses:
        # Импорт локальный: модуль тянет TON-клиент, а он нужен не всегда.
        from app.ton_payout_lookup import resolve_jetton_wallets

        try:
            wallets = resolve_jetton_wallets(addresses)
        except Exception as error:  # noqa: BLE001 — батч важнее адресов
            logger.warning(
                "Jetton wallet resolution failed for batch %s: %s",
                batch_id,
                error,
            )

    with SessionLocal() as session:
        batch = session.get(PayoutBatch, batch_id)
        if batch is None:  # pragma: no cover
            raise MissionEngineError(404, "Батч не найден.")
        items = _load_batch_items(session, batch_id, wallets)
        result = _serialize_batch(batch, items)

    # Адрес для ОТПРАВКИ transfer: по TEP-74 сообщение 0xf8a7ea5 уходит на
    # СВОЙ jetton-кошелёк (отправителя), а получатель указан в теле. Если
    # отправить на jetton-кошелёк получателя, он не существует — сообщение
    # отбивается (bounce) и деньги не доходят. Именно это случилось на
    # первой реальной выплате.
    result["senderJettonWallet"] = _resolve_sender_jetton_wallet()
    return result


def _resolve_sender_jetton_wallet() -> str | None:
    """jetton-кошелёк кошелька выплат — адрес назначения для transfer.

    Кэшируется в модуле: адрес меняется только при смене кошелька выплат
    или минтера, а запрос к TON API небесплатный.
    """
    global _SENDER_JETTON_CACHE
    if _SENDER_JETTON_CACHE is not None:
        return _SENDER_JETTON_CACHE or None

    from app.ton_payout_lookup import _read_payout_wallet, resolve_jetton_wallets

    wallet = _read_payout_wallet()
    if not wallet:
        _SENDER_JETTON_CACHE = ""
        return None

    try:
        resolved = resolve_jetton_wallets([wallet])
    except Exception as error:  # noqa: BLE001 — TON API может быть недоступен
        logger.warning("Не удалось вычислить jetton-кошелёк отправителя: %s", error)
        return None

    address = resolved.get(wallet)
    if address:
        _SENDER_JETTON_CACHE = address
    return address


def _load_batch_items(
    session: Session,
    batch_id: str,
    jetton_wallets: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    """Заявки батча с их query_id (для отдачи фронту и для истории)."""
    # Два запроса вместо JOIN: у заявки может быть несколько попыток за
    # историю (после отката прежняя помечается 'failed', новый батч создаёт
    # свежую 'sending'). JOIN на withdrawal_id возвращал заявку ДВАЖДЫ —
    # интерфейс показывал «2 заявки · 310 ROOT» вместо «1 заявка · 155 ROOT»,
    # а кнопка оплаты собирала два перевода на одну заявку с разными
    # query_id, то есть владелец подписал бы двойную выплату.
    withdrawals = list(
        session.scalars(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.batch_id == batch_id)
            .order_by(WithdrawalRequest.created_at, WithdrawalRequest.id)
        ).all()
    )
    if not withdrawals:
        return []

    attempts = list(
        session.scalars(
            select(PayoutAttempt)
            .where(
                PayoutAttempt.withdrawal_id.in_([w.id for w in withdrawals]),
                PayoutAttempt.status.in_(PAYOUT_ATTEMPT_ACTIVE_STATUSES),
            )
            .order_by(PayoutAttempt.created_at.desc())
        ).all()
    )
    # На заявку — первая (самая свежая) активная попытка.
    by_withdrawal: dict[str, PayoutAttempt] = {}
    for attempt in attempts:
        by_withdrawal.setdefault(attempt.withdrawal_id, attempt)

    # Ники одним запросом: админ должен видеть «кто», а не только id.
    player_ids = {w.player_id for w in withdrawals if w.player_id}
    nicknames: dict[str, str | None] = {}
    if player_ids:
        rows = session.execute(
            select(GamePlayer.id, GamePlayer.nickname).where(
                GamePlayer.id.in_(player_ids)
            )
        ).all()
        nicknames = {row[0]: row[1] for row in rows}

    wallets = jetton_wallets or {}
    return [
        _serialize_item(
            withdrawal,
            by_withdrawal[withdrawal.id].query_id
            if withdrawal.id in by_withdrawal
            else None,
            wallets.get(withdrawal.to_address),
            nicknames.get(withdrawal.player_id),
        )
        for withdrawal in withdrawals
    ]


def create_payout_batch(
    admin_id: str | None = None, limit: int = BATCH_MAX_ITEMS
) -> dict[str, Any]:
    """Сформировать батч из накопленных pending-заявок.

    Поведение при уже открытом батче: вернуть его, не создавая второй.
    Это важно для ночного джоба, который вызывает функцию в каждом из 3
    воркеров gunicorn.

    Возвращает {"batchId", "status", "totalNano", "totalRoot", "itemCount",
    "items"} — повтор вызова идемпотентен по batchId.
    """
    safe_limit = max(1, min(limit, BATCH_MAX_ITEMS))

    # 1. Уже есть открытый батч — возвращаем его (идемпотентность).
    with SessionLocal() as session:
        existing = _open_batch(session)
        if existing is not None:
            items = _load_batch_items(session, existing.id)
            logger.info(
                "Payout batch %s already open (%s); reusing, %d items",
                existing.id,
                existing.status,
                len(items),
            )
            return _serialize_batch(existing, items)
        to_process = _pending_withdrawal_ids(session, safe_limit)

    if not to_process:
        raise MissionEngineError(409, "Нет заявок на вывод в статусе pending.")

    batch_id = _new_id("batch")
    total_nano = 0

    # 2. Создание батча и перевод заявок — одна транзакция.
    try:
        with SessionLocal.begin() as session:
            # Проверяем ещё раз под блокировкой: между шагом 1 и 2 мог
            # появиться открытый батч (другой воркер).
            if _open_batch(session) is not None:
                raise _BatchAlreadyOpen()

            withdrawals = list(
                session.scalars(
                    select(WithdrawalRequest)
                    .where(
                        WithdrawalRequest.id.in_(to_process),
                        WithdrawalRequest.status == "pending",
                    )
                    .order_by(WithdrawalRequest.created_at, WithdrawalRequest.id)
                    .with_for_update()
                ).all()
            )
            if not withdrawals:
                raise MissionEngineError(
                    409, "Заявки уже обработаны другим батчем."
                )

            now = _utcnow()
            for withdrawal in withdrawals:
                amount_nano = withdrawal.amount_root_nano or (
                    withdrawal.amount_root * NANO_PER_ROOT
                )
                total_nano += amount_nano
                withdrawal.status = "processing"
                withdrawal.batch_id = batch_id
                if admin_id is not None:
                    withdrawal.admin_id = admin_id
                session.add(
                    PayoutAttempt(
                        id=_new_id("payout-attempt"),
                        withdrawal_id=withdrawal.id,
                        status=PAYOUT_ATTEMPT_SENDING,
                        query_id=_new_payout_query_id(),
                    )
                )

            batch = PayoutBatch(
                id=batch_id,
                admin_id=admin_id,
                status=BATCH_STATUS_READY,
                total_nano=total_nano,
                payload_text=_build_payload_text(session, withdrawals),
                opened_at=now,
            )
            session.add(batch)
            session.flush()
    except _BatchAlreadyOpen:
        # Гонка: пока шли сюда, другой процесс создал батч. Возвращаем его.
        with SessionLocal() as session:
            existing = _open_batch(session)
            if existing is None:  # pragma: no cover — крайне маловероятно
                raise
            items = _load_batch_items(session, existing.id)
            return _serialize_batch(existing, items)
    except IntegrityError:
        # Барьер БД: два воркера одновременно дошли до INSERT. Побеждает один,
        # второй получает существующий батч.
        with SessionLocal() as session:
            existing = _open_batch(session)
            if existing is None:
                raise
            items = _load_batch_items(session, existing.id)
            logger.info(
                "Payout batch barrier hit; reusing %s", existing.id
            )
            return _serialize_batch(existing, items)

    with SessionLocal() as session:
        batch = session.get(PayoutBatch, batch_id)
        if batch is None:  # pragma: no cover
            raise MissionEngineError(500, "Батч не сохранился.")
        items = _load_batch_items(session, batch_id)
        logger.info(
            "Payout batch %s created: %d items, %d nano",
            batch_id,
            len(items),
            total_nano,
        )
        return _serialize_batch(batch, items)


class _BatchAlreadyOpen(Exception):
    """Внутренний сигнал: открытый батч появился между проверкой и записью."""
