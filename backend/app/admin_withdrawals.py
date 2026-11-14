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
from sqlalchemy import func, select

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.mission_engine import MissionEngineError
from app.models import AdminUser, WithdrawalRequest
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


def _serialize_withdrawal(withdrawal: WithdrawalRequest) -> dict[str, Any]:
    """WithdrawalRequest -> безопасный JSON (адрес получателя — не секрет)."""
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

    return {
        "withdrawals": [_serialize_withdrawal(row) for row in rows],
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

