"""Админ-эндпоинты вывода ROOT → TON (11.6).

- GET    /api/v1/admin/withdrawals — список заявок: фильтры status,
  player_id, period (day|week|month|all), пагинация limit/offset,
  сортировка created_at desc, id desc.
- POST   /api/v1/admin/withdrawals/batch — батч-выплата pending-заявок
  (process_withdrawal_batch): каждая -> confirmed+ton_tx_hash либо
  failed+refund холда игроку.
- POST   /api/v1/admin/withdrawals/{withdrawal_id}/reject — отклонение
  одной заявки (reject_withdrawal): refund холда + статус rejected.

Permission: players.read (список — read-only, без новой permission, как
в admin_monitoring), players.manage (batch/reject — мутирующие операции).
Режим — direct (testnet), без super-admin approval.

Аудит мутаций — write_admin_audit в той же сессии, что и вызов сервиса
(request=None в юнит-тестах даёт fallback correlation "cli:...").
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.mission_engine import MissionEngineError
from app.models import (
    AdminUser,
    PayoutAttempt,
    PayoutBatch,
    WithdrawalRequest,
)
from app.withdrawal_service import (
    NANO_PER_ROOT,
    process_withdrawal_batch,
    reject_withdrawal,
)

router = APIRouter(
    prefix="/api/v1/admin/withdrawals",
    tags=["admin-withdrawals"],
)

# Локальные константы пермишенов — как в admin_players/admin_monitoring
# (нет общей registry в admin_access; менять их вне задачи запрещено).
PLAYERS_READ_PERMISSION = "players.read"
PLAYERS_MANAGE_PERMISSION = "players.manage"

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# period -> период в днях (created_at >= now - N days); "all" — без ограничения.
PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}
VALID_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "processing",
    "confirmed",
    "failed",
)


class WithdrawalRejectPayload(BaseModel):
    """POST /{withdrawal_id}/reject: обязательный reason (1..255 символов)."""

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=255)


def _serialize_withdrawal(
    withdrawal: WithdrawalRequest,
    attempt: PayoutAttempt | None = None,
) -> dict[str, Any]:
    """WithdrawalRequest -> безопасный JSON (адрес получателя — не секрет).

    attempt — последняя попытка выплаты (PayoutAttempt). По ней админка
    показывает, ПОЧЕМУ выплата не прошла: без этого `failed` + пустой tx-hash
    не отличить от сети, конфига или баланса, и причину искать только в логах.
    """
    return {
        "id": withdrawal.id,
        "playerId": withdrawal.player_id,
        "amountRoot": withdrawal.amount_root,
        # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
        "amountRootNano": (
            withdrawal.amount_root_nano
            if withdrawal.amount_root_nano is not None
            else withdrawal.amount_root * NANO_PER_ROOT
        ),
        "toAddress": withdrawal.to_address,
        "status": withdrawal.status,
        "tonTxHash": withdrawal.ton_tx_hash,
        "batchId": withdrawal.batch_id,
        "adminId": withdrawal.admin_id,
        "reason": withdrawal.reason,
        # Причина отказа выплаты (не путать с reason — это отклонение админом).
        "payoutError": attempt.error if attempt is not None else None,
        "payoutAttemptStatus": attempt.status if attempt is not None else None,
        "payoutAttemptedAt": (
            attempt.created_at.isoformat()
            if attempt is not None and attempt.created_at
            else None
        ),
        "createdAt": (
            withdrawal.created_at.isoformat() if withdrawal.created_at else None
        ),
        "updatedAt": (
            withdrawal.updated_at.isoformat() if withdrawal.updated_at else None
        ),
    }


def _period_start(period: str) -> datetime | None:
    """Начало period-окна (naive UTC, как сервер хранит created_at)."""
    days = PERIOD_DAYS.get(period)
    if days is None:
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now - timedelta(days=days)


@router.get("")
def list_admin_withdrawals(
    status: str | None = None,
    player_id: str | None = None,
    period: str = "all",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
) -> dict[str, Any]:
    """Список заявок на вывод (11.6): статус/игрок/период/пагинация.

    Сортировка created_at desc, id desc — детерминированный порядок.
    """
    if status is not None and status not in VALID_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                "status должен быть одним из: pending, approved, rejected, "
                "processing, confirmed, failed."
            ),
        )
    if period not in PERIOD_DAYS:
        raise HTTPException(
            status_code=422,
            detail="period должен быть 'day', 'week', 'month' или 'all'.",
        )

    safe_limit = max(1, min(limit, MAX_LIMIT))
    safe_offset = max(0, offset)

    filters = []
    if status is not None:
        filters.append(WithdrawalRequest.status == status)
    if player_id is not None:
        filters.append(WithdrawalRequest.player_id == player_id)
    period_start = _period_start(period)
    if period_start is not None:
        filters.append(WithdrawalRequest.created_at >= period_start)

    with SessionLocal() as session:  # read-only, не begin()
        total = (
            session.scalar(
                select(func.count())
                .select_from(WithdrawalRequest)
                .where(*filters)
            )
            or 0
        )
        rows = session.scalars(
            select(WithdrawalRequest)
            .where(*filters)
            .order_by(
                WithdrawalRequest.created_at.desc(),
                WithdrawalRequest.id.desc(),
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()

        # Последняя попытка выплаты по каждой заявке — одним запросом.
        # Без этого причина отказа невидима: админка получает только
        # status='failed' и пустой tx-hash, а текст ошибки лежит в
        # PayoutAttempt.error и теряется.
        attempts_by_withdrawal: dict[str, PayoutAttempt] = {}
        if rows:
            attempt_rows = session.scalars(
                select(PayoutAttempt)
                .where(
                    PayoutAttempt.withdrawal_id.in_(
                        [row.id for row in rows]
                    )
                )
                .order_by(
                    PayoutAttempt.created_at.desc(),
                    PayoutAttempt.id.desc(),
                )
            ).all()
            for attempt in attempt_rows:
                # Первая в порядке desc — самая свежая; остальные игнорируем.
                attempts_by_withdrawal.setdefault(
                    attempt.withdrawal_id, attempt
                )

    return {
        "withdrawals": [
            _serialize_withdrawal(
                row, attempts_by_withdrawal.get(row.id)
            )
            for row in rows
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.post("/batch")
def run_admin_withdrawal_batch(
    request: Request,
    limit: int = DEFAULT_LIMIT,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Батч-выплата pending-заявок (11.6): confirmed/failed + аудит.

    Лимит — операционная страховка (не более MAX_LIMIT за один вызов).
    Возвращает результат сервиса {batchId, confirmed, failed}.
    """
    safe_limit = max(1, min(limit, MAX_LIMIT))

    with SessionLocal.begin() as session:
        result = process_withdrawal_batch(admin.id, safe_limit)
        write_admin_audit(
            session,
            actor=admin,
            action="withdrawal.batch",
            entity_type="withdrawal_batch",
            entity_id=result["batchId"],
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=None,
            after={
                "batchId": result["batchId"],
                "confirmed": result["confirmed"],
                "failed": result["failed"],
            },
        )
        session.flush()

    return result


# --- Батчи для внешней оплаты (TON Connect, 11.x-external-payout) ----------
#
# Схема: сервер формирует батч и выдаёт каждой заявке свой query_id; владелец
# игры подписывает пачку jetton-переводов на своём устройстве; сервер сверяет
# блокчейн. Приватный ключ на сервере не нужен.


@router.post("/payout-batches")
def create_payout_batch_route(
    request: Request,
    limit: int = DEFAULT_LIMIT,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Сформировать батч из накопленных pending-заявок (или вернуть открытый).

    Идемпотентно: при уже открытом батче возвращается он же, второй не
    создаётся (барьер — частичный unique-индекс в БД, см. PayoutBatch).
    Заявки переходят в processing и получают по одному query_id.
    """
    from app.payout_batch_service import create_payout_batch

    safe_limit = max(1, min(limit, MAX_LIMIT))
    try:
        result = create_payout_batch(admin_id=admin.id, limit=safe_limit)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.detail
        ) from error

    with SessionLocal.begin() as session:
        write_admin_audit(
            session,
            actor=admin,
            action="withdrawal.batch_created",
            entity_type="payout_batch",
            entity_id=result["batchId"],
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=None,
            after={
                "batchId": result["batchId"],
                "status": result["status"],
                "itemCount": result["itemCount"],
                "totalRoot": result["totalRoot"],
            },
        )
        session.flush()

    return result


@router.post("/payout-batches/{batch_id}/rollback")
def rollback_payout_batch_route(
    batch_id: str,
    payload: dict[str, Any],
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Откатить батч: processing-заявки вернуть в pending или провалить.

    Тело: {"reason": "...", "mode": "return_to_pending" | "fail_and_refund",
    "force": false}.

    mode=return_to_pending — заявки ждут следующего батча, холд остаётся
    (деньги всё ещё зарезервированы). mode=fail_and_refund — заявка failed
    и холд возвращается игроку.

    Подтверждённые заявки не откатываются никогда: деньги уже в блокчейне.
    Частично подтверждённый батч требует force=true.
    """
    from app.payout_rollback_service import (
        MODE_RETURN_TO_PENDING,
        rollback_payout_batch,
    )

    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Ожидается JSON-объект.")
    reason = payload.get("reason")
    mode = payload.get("mode") or MODE_RETURN_TO_PENDING
    force = bool(payload.get("force", False))

    try:
        result = rollback_payout_batch(
            batch_id,
            reason=str(reason or ""),
            mode=str(mode),
            admin_id=admin.id,
            force=force,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.detail
        ) from error

    with SessionLocal.begin() as session:
        write_admin_audit(
            session,
            actor=admin,
            action="withdrawal.batch_rolled_back",
            entity_type="payout_batch",
            entity_id=batch_id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=None,
            after={
                "batchId": batch_id,
                "mode": result["mode"],
                "returned": len(result["returned"]),
                "failed": len(result["failed"]),
                "reason": result["reason"],
            },
        )
        session.flush()

    return result


@router.post("/payout-batches/{batch_id}/confirm")
def confirm_payout_batch_route(
    batch_id: str,
    payload: dict[str, Any],
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Подтвердить батч по подписанному BOC от TON Connect.

    Тело: {"boc": "<base64 BOC>"}. BOC — то, что вернул кошелёк после
    подписи. Сервер проверяет подпись, отправителя, соответствие переводам
    батча, затем ищет каждый перевод в блокчейне и подтверждает ТОЛЬКО
    найденные заявки: частичная оплата — штатный сценарий TON.
    """
    from app.payout_confirm_service import confirm_payout_batch
    from app.ton_payout_lookup import lookup_transfer_by_query_id

    boc = payload.get("boc") if isinstance(payload, dict) else None
    if not isinstance(boc, str) or not boc.strip():
        raise HTTPException(status_code=422, detail="Поле boc обязательно.")

    try:
        result = confirm_payout_batch(
            batch_id,
            boc.strip(),
            admin_id=admin.id,
            blockchain_lookup=lookup_transfer_by_query_id,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.detail
        ) from error

    with SessionLocal.begin() as session:
        write_admin_audit(
            session,
            actor=admin,
            action="withdrawal.batch_confirmed",
            entity_type="payout_batch",
            entity_id=batch_id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=None,
            after={
                "batchId": batch_id,
                "status": result["status"],
                "confirmedCount": result["confirmedCount"],
                "pendingCount": result["pendingCount"],
            },
        )
        session.flush()

    return result


@router.get("/payout-batches")
def list_payout_batches_route(
    status: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
) -> dict[str, Any]:
    """Список батчей: «требует действия» первыми, внутри — старые сверху.

    Порядок отражает рабочую очередь: ready (надо платить) -> submitted
    (надо сверить) -> остальные (история, новые первыми).
    """
    from app.payout_batch_service import BATCH_STATUSES, serialize_batch_row

    if status is not None and status not in BATCH_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=(
                "status должен быть одним из: "
                + ", ".join(BATCH_STATUSES)
            ),
        )
    safe_limit = max(1, min(limit, MAX_LIMIT))
    safe_offset = max(0, offset)

    with SessionLocal() as session:
        filters = []
        if status is not None:
            filters.append(PayoutBatch.status == status)
        total = (
            session.scalar(
                select(func.count()).select_from(PayoutBatch).where(*filters)
            )
            or 0
        )
        rows = session.scalars(
            select(PayoutBatch)
            .where(*filters)
            .order_by(
                # 0 — ready, 1 — submitted, 2 — закрытые.
                case(
                    (PayoutBatch.status == "ready", 0),
                    (PayoutBatch.status == "submitted", 1),
                    else_=2,
                ),
                # Внутри «требует действия» — старые сверху (дольше ждут).
                PayoutBatch.opened_at.asc(),
                PayoutBatch.id.desc(),
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()

        items_by_batch = {
            row.id: session.scalar(
                select(func.count())
                .select_from(WithdrawalRequest)
                .where(WithdrawalRequest.batch_id == row.id)
            )
            or 0
            for row in rows
        }

    return {
        "batches": [
            serialize_batch_row(row, items_by_batch.get(row.id, 0))
            for row in rows
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/payout-batches/{batch_id}")
def get_payout_batch_route(
    batch_id: str,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
) -> dict[str, Any]:
    """Детали батча: заявки с их query_id для сборки TON Connect-запроса."""
    from app.payout_batch_service import get_payout_batch

    try:
        return get_payout_batch(batch_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code, detail=error.detail
        ) from error


@router.post("/{withdrawal_id}/reject")
def reject_admin_withdrawal(
    withdrawal_id: str,
    payload: WithdrawalRejectPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Отклонить заявку (11.6): refund холда игроку + аудит.

    reject_withdrawal кидает MissionEngineError(404) для отсутствующих
    или уже закрытых статусов — переводим в HTTPException.
    A11: финансовая операция (reject_withdrawal) и audit выполняются
    в одной транзакции. При сбое audit откатывается и финансовое изменение.
    """
    try:
        with SessionLocal.begin() as session:
            result = reject_withdrawal(
                admin.id, withdrawal_id, payload.reason, session=session
            )
            write_admin_audit(
                session,
                actor=admin,
                action="withdrawal.rejected",
                entity_type="withdrawal",
                entity_id=withdrawal_id,
                request=request,
                permission_code=PLAYERS_MANAGE_PERMISSION,
                before={"status": "pending"},
                after={"status": "rejected", "reason": payload.reason},
            )
            session.flush()
        return result
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

