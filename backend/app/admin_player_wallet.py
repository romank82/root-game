"""Админ-операции кошелька игрока: ручные начисление/списание ROOT (шаг 5.4).

- POST /api/v1/admin/players/{player_id}/wallet-adjustment
  Прямое исполнение при direct-grant и сумме ниже порога; при
  approval-grant или сумме >= economy.manual_adjustment_approval_threshold
  создаёт AdminApprovalRequest и отвечает 201.
- POST /api/v1/admin/players/wallet-adjustment-requests/{approval_id}/execute
  Dedicated executor для супер-админа: применяет approved-заявку
  (action_type player.wallet_credit | player.wallet_debit).

Все изменения ROOT — immutable проводки WalletTransaction
(reference_type=admin_credit|admin_debit, reference_id=request_id,
amount > 0, направление в transaction_type); баланс кошелька меняется
только внутри этих проводок. Идемпотентность по
(requested_by_admin_id, request_id) для заявок и по
(wallet_id, reference_type, reference_id) для проводок.
Аудит — write_admin_audit, sensitive-данные в audit не попадают.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.admin_access import (
    APPROVAL_EXECUTION_MODE,
    get_admin_user,
    get_permission_execution_mode,
    require_super_admin,
)
from app.admin_approvals import (
    APPROVED,
    EXECUTED,
    EXECUTION_FAILED,
    PENDING,
    _serialize as _serialize_approval,
)
from app.admin_audit import (
    build_admin_approval_audit_snapshot,
    sanitize_audit_data,
    write_admin_audit,
)
from app.db import SessionLocal
from app.models import (
    AdminApprovalRequest,
    AdminUser,
    GamePlayer,
    SystemSetting,
    Wallet,
    WalletTransaction,
)
from app.system_settings_catalog import get_definition

router = APIRouter(prefix="/api/v1/admin/players", tags=["admin-player-wallet"])

# --- Доменные константы -----------------------------------------------------
PLAYERS_MANAGE_PERMISSION = "players.manage"
ADMIN_CREDIT_REFERENCE_TYPE = "admin_credit"
ADMIN_DEBIT_REFERENCE_TYPE = "admin_debit"
ACTION_TYPE_CREDIT = "player.wallet_credit"
ACTION_TYPE_DEBIT = "player.wallet_debit"
MANUAL_ADJUSTMENT_THRESHOLD_KEY = "economy.manual_adjustment_approval_threshold"
DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD = 1000
MAX_REASON_LEDGER = 255
ROOT_CURRENCY = "ROOT"
ACTIVE_SETTING_STATUS = "active"


class WalletAdjustmentError(Exception):
    """Доменная ошибка wallet-adjustment с machine-readable code."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class WalletAdjustmentPayload(BaseModel):
    direction: Literal["credit", "debit"]
    amount: int = Field(ge=1, le=1_000_000_000)
    reason: str = Field(min_length=1, max_length=4_000)
    # request_id копируется в wallet_transactions.reference_id, а это
    # VARCHAR(64) в БД (PostgreSQL падает на большей длине), поэтому
    # лимит здесь обязан совпадать со столбцом reference_id.
    request_id: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None


# --- Вспомогательные хелперы -------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:24]}"


def _client_ip_address(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} не может состоять только из пробелов.",
        )
    return normalized


def _validate_expiry(expires_at: datetime) -> datetime:
    if expires_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiresAt должен содержать timezone.",
        )
    if expires_at <= _now():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiresAt должен быть в будущем.",
        )
    return expires_at


def _read_threshold(session: Any) -> int:
    """Порог approval для ручных корректировок (A.2).

    Приоритет: активная SystemSetting-запись -> default каталога ->
    DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD.
    """
    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == MANUAL_ADJUSTMENT_THRESHOLD_KEY,
            SystemSetting.status == ACTIVE_SETTING_STATUS,
        )
    )
    # Явная проверка статуса: страховка от устаревших копий в кэшах/тестах,
    # WHERE выше остаётся первичным фильтром для реальной БД.
    if (
        setting is not None
        and getattr(setting, "status", None) == ACTIVE_SETTING_STATUS
        and isinstance(setting.value_json, int)
        and setting.value_json >= 0
    ):
        return setting.value_json
    definition = get_definition(MANUAL_ADJUSTMENT_THRESHOLD_KEY)
    if definition is not None and isinstance(definition.default_value, int):
        return definition.default_value
    return DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD


def _get_wallet_for_update(session: Any, player_id: str) -> Wallet | None:
    return session.scalar(
        select(Wallet)
        .where(Wallet.player_id == player_id, Wallet.currency == ROOT_CURRENCY)
        .with_for_update()
    )


def _build_ledger_reason(direction: str, reason: str | None) -> str:
    """Reason для ledger: как есть (<=255) или обрезанный; дефолт оборонительный."""
    if reason:
        return reason if len(reason) <= MAX_REASON_LEDGER else reason[:MAX_REASON_LEDGER]
    return f"Admin {direction}: manual adjustment (no reason)"


def _apply_wallet_adjustment(
    session: Any,
    *,
    wallet: Wallet | None,
    player_id: str,
    direction: str,
    amount: int,
    reason: str,
    request_id: str,
    admin: AdminUser,
    request: Request,
    approval: AdminApprovalRequest | None = None,
) -> WalletTransaction:
    """Создать ровно одну immutable проводку ROOT (credit/debit) и зааудитить.

    amount всегда > 0, направление задаётся transaction_type.
    wallet должен быть захвачен FOR UPDATE. Для debit кошелёк обязан
    существовать и покрывать сумму; для credit при отсутствии кошелька
    он создаётся. Аудит пишется только после успешного flush.
    """
    if direction not in ("credit", "debit"):
        raise WalletAdjustmentError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_direction",
            "Направление должно быть credit или debit.",
        )
    if wallet is None and direction == "debit":
        raise WalletAdjustmentError(
            status.HTTP_409_CONFLICT,
            "insufficient_balance",
            "Недостаточно ROOT: кошелёк не существует.",
        )

    before_balance = wallet.available_balance if wallet is not None else 0
    if direction == "debit":
        if wallet.available_balance < amount:
            raise WalletAdjustmentError(
                status.HTTP_409_CONFLICT,
                "insufficient_balance",
                "Недостаточно ROOT для списания.",
            )
        new_balance = wallet.available_balance - amount
    else:
        new_balance = before_balance + amount

    if wallet is None:  # credit, кошелёк отсутствует — создаём.
        wallet = Wallet(
            id=_new_id("wallet"),
            player_id=player_id,
            currency=ROOT_CURRENCY,
            available_balance=0,
            locked_balance=0,
        )
        session.add(wallet)
        session.flush()

    wallet.available_balance = new_balance

    reference_type = (
        ADMIN_CREDIT_REFERENCE_TYPE if direction == "credit" else ADMIN_DEBIT_REFERENCE_TYPE
    )
    metadata = {
        "requestId": request_id,
        "playerId": player_id,
        "direction": direction,
        "amountAtomic": amount,
        "fullReason": reason,
        "initiatedByType": "admin",
        "initiatedByAdminId": admin.id,
    }
    if approval is not None:
        metadata["approvalRequestId"] = approval.id

    transaction = WalletTransaction(
        id=_new_id("wallet-transaction"),
        wallet_id=wallet.id,
        amount=amount,
        balance_after=new_balance,
        transaction_type=direction,
        reason=_build_ledger_reason(direction, reason),
        reference_type=reference_type,
        reference_id=request_id,
        metadata_json=sanitize_audit_data(metadata),
    )
    session.add(transaction)
    session.flush()

    write_admin_audit(
        session,
        actor=admin,
        action=(
            f"player.wallet_{direction}"
            if approval is None
            else f"player.wallet_{direction}.via_approval"
        ),
        entity_type="player",
        entity_id=player_id,
        request=request,
        permission_code=PLAYERS_MANAGE_PERMISSION,
        approval_request_id=approval.id if approval is not None else None,
        request_id=request_id,
        before={"availableBalance": before_balance},
        after={"availableBalance": new_balance},
        metadata={
            "direction": direction,
            "amountAtomic": amount,
            "referenceType": reference_type,
            "referenceId": request_id,
        },
    )
    return transaction


def _existing_matches(
    existing: WalletTransaction, direction: str, amount: int, reason: str
) -> bool:
    """Тот же request_id и то же содержимое — безопасный идемпотентный replay."""
    metadata = existing.metadata_json or {}
    return (
        existing.transaction_type == direction
        and existing.amount == amount
        and metadata.get("fullReason") == reason
        and metadata.get("requestId") == existing.reference_id
    )


def _serialize_wallet_adjustment_result(
    tx: WalletTransaction, wallet: Wallet, idempotent: bool
) -> dict[str, Any]:
    return {
        "transaction": {
            "id": tx.id,
            "amount": tx.amount,
            "balanceAfter": tx.balance_after,
            "transactionType": tx.transaction_type,
            "reason": tx.reason,
            "referenceType": tx.reference_type,
            "referenceId": tx.reference_id,
            "metadata": sanitize_audit_data(tx.metadata_json or {}),
            "createdAt": (
                getattr(tx, "created_at", None).isoformat()
                if getattr(tx, "created_at", None)
                else None
            ),
        },
        "wallet": {
            "playerId": wallet.player_id,
            "currency": wallet.currency,
            "availableBalance": wallet.available_balance,
            "lockedBalance": wallet.locked_balance,
        },
        "idempotent": idempotent,
    }


def _audit_approval(
    *,
    session: Any,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    outcome: str,
    request: Request,
    metadata: dict[str, Any] | None = None,
) -> None:
    write_admin_audit(
        session,
        actor=actor,
        action=action,
        entity_type="admin_approval_request",
        entity_id=approval.id,
        request=request,
        permission_code=approval.required_permission_code,
        approval_request_id=approval.id,
        request_id=approval.request_id,
        before=build_admin_approval_audit_snapshot(before),
        after=build_admin_approval_audit_snapshot(after),
        outcome=outcome,
        metadata=metadata
        or {
            "actionType": approval.action_type,
            "targetEntityType": approval.target_entity_type,
            "targetEntityId": approval.target_entity_id,
        },
    )


def _mark_execution_failed(
    *,
    session: Any,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    error_code: str,
    request: Request,
) -> dict[str, Any]:
    """Финальный consumed-статус EXECUTION_FAILED с аудитом (паттерн 5.x)."""
    before = _serialize_approval(approval)
    approval.status = EXECUTION_FAILED
    approval.executed_by_admin_id = actor.id
    approval.executed_at = _now()
    approval.execution_result = {"status": "failed", "errorCode": error_code}
    approval.execution_error = error_code
    session.flush()

    after = _serialize_approval(approval)
    _audit_approval(
        session=session,
        actor=actor,
        approval=approval,
        action="admin_approval_request.execution_failed",
        before=before,
        after=after,
        outcome="failure",
        request=request,
        metadata={
            "actionType": approval.action_type,
            "targetEntityType": approval.target_entity_type,
            "targetEntityId": approval.target_entity_id,
            "errorCode": error_code,
        },
    )
    return after


def _execution_failed_response(
    *,
    session: Any,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    error_code: str,
    request: Request,
) -> JSONResponse:
    after = _mark_execution_failed(
        session=session,
        actor=actor,
        approval=approval,
        error_code=error_code,
        request=request,
    )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"approval": after, "idempotent": False, "error": error_code},
    )


def _create_wallet_adjustment_request(
    *,
    session: Any,
    admin: AdminUser,
    player_id: str,
    direction: str,
    amount: int,
    reason: str,
    request_id: str,
    expires_at: datetime | None,
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на wallet-adjustment (idempotency по request_id).

    При повторном request_id с тем же содержимым отвечает 200 + idempotent,
    с другим содержимым — 409.
    """
    action_type = ACTION_TYPE_CREDIT if direction == "credit" else ACTION_TYPE_DEBIT
    snapshot = {
        "direction": direction,
        "amount": amount,
        "reason": reason,
        "playerId": player_id,
        "thresholdChecked": True,
    }
    expected = {
        "required_permission_code": PLAYERS_MANAGE_PERMISSION,
        "action_type": action_type,
        "target_entity_type": "player",
        "target_entity_id": player_id,
        "payload_snapshot": snapshot,
        "reason": reason,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
    }

    existing = session.scalar(
        select(AdminApprovalRequest)
        .where(
            AdminApprovalRequest.requested_by_admin_id == admin.id,
            AdminApprovalRequest.request_id == request_id,
        )
        .with_for_update()
    )
    if existing is not None:
        current = {
            "required_permission_code": existing.required_permission_code,
            "action_type": existing.action_type,
            "target_entity_type": existing.target_entity_type,
            "target_entity_id": existing.target_entity_id,
            "payload_snapshot": existing.payload_snapshot,
            "reason": existing.reason,
            "expires_at": (
                existing.expires_at.isoformat() if existing.expires_at is not None else None
            ),
        }
        if current != expected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="requestId уже использован с другим содержимым заявки.",
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"approval": _serialize_approval(existing), "idempotent": True},
        )

    approval = AdminApprovalRequest(
        id=_new_id("admin-approval"),
        status=PENDING,
        requested_by_admin_id=admin.id,
        required_permission_code=PLAYERS_MANAGE_PERMISSION,
        action_type=action_type,
        target_entity_type="player",
        target_entity_id=player_id,
        payload_snapshot=snapshot,
        reason=reason,
        request_ip_address=_client_ip_address(request),
        request_id=request_id,
        expires_at=expires_at,
        execution_result={},
    )
    try:
        session.add(approval)
        session.flush()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Конфликт идемпотентности заявки.",
        ) from error

    serialized = _serialize_approval(approval)
    _audit_approval(
        session=session,
        actor=admin,
        approval=approval,
        action="admin_approval_request.created",
        before={},
        after=serialized,
        outcome="success",
        request=request,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"approval": serialized, "idempotent": False},
    )


@router.post("/{player_id}/wallet-adjustment", response_model=None)
def create_player_wallet_adjustment(
    player_id: str,
    payload: WalletAdjustmentPayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
) -> dict[str, Any] | JSONResponse:
    """Начислить/списать ROOT: прямое исполнение либо создание approval-заявки.

    НЕ использует require_permission: для approval-ветки нужно самим считать
    execution_mode через get_permission_execution_mode (как admin_system_settings).
    """
    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")
    direction = payload.direction
    amount = payload.amount
    expires_at = (
        _validate_expiry(payload.expires_at) if payload.expires_at is not None else None
    )

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Игрок не найден.",
            )

        execution_mode = get_permission_execution_mode(admin, PLAYERS_MANAGE_PERMISSION)
        if execution_mode is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        threshold = _read_threshold(session)

        # Super-admin не блокируется порогом: по конвенции admin_system_settings
        # он не создаёт заявки (одобрять его некому), а только исполняет.
        needs_approval = (execution_mode == APPROVAL_EXECUTION_MODE) or (
            not admin.is_super_admin and amount >= threshold
        )

        if needs_approval:
            return _create_wallet_adjustment_request(
                session=session,
                admin=admin,
                player_id=player_id,
                direction=direction,
                amount=amount,
                reason=reason,
                request_id=request_id,
                expires_at=expires_at,
                request=request,
            )

        # Прямое исполнение.
        reference_type = (
            ADMIN_CREDIT_REFERENCE_TYPE if direction == "credit" else ADMIN_DEBIT_REFERENCE_TYPE
        )
        wallet = _get_wallet_for_update(session, player_id)

        if wallet is not None:
            existing = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == reference_type,
                    WalletTransaction.reference_id == request_id,
                )
            )
            if existing is not None:
                if _existing_matches(existing, direction, amount, reason):
                    return _serialize_wallet_adjustment_result(existing, wallet, idempotent=True)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="requestId уже использован с другим содержимым проводки.",
                )

        try:
            transaction = _apply_wallet_adjustment(
                session=session,
                wallet=wallet,
                player_id=player_id,
                direction=direction,
                amount=amount,
                reason=reason,
                request_id=request_id,
                admin=admin,
                request=request,
            )
        except WalletAdjustmentError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности: requestId уже использован для этого кошелька.",
            ) from error

        result_wallet = wallet if wallet is not None else session.get(Wallet, transaction.wallet_id)
        return _serialize_wallet_adjustment_result(transaction, result_wallet, idempotent=False)


@router.post("/wallet-adjustment-requests/{approval_id}/execute")
def execute_player_wallet_adjustment(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
) -> dict[str, Any]:
    """Исполнить approved заявку на credit/debit только супер-админом.

    Никакого generic executor: принимаются исключительно
    player.wallet_credit и player.wallet_debit.
    """
    with SessionLocal.begin() as session:
        approval = session.scalar(
            select(AdminApprovalRequest)
            .where(AdminApprovalRequest.id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Заявка не найдена.",
            )

        if approval.action_type not in (ACTION_TYPE_CREDIT, ACTION_TYPE_DEBIT):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Executor принимает только player.wallet_credit и player.wallet_debit.",
            )

        if approval.status == EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        if approval.expires_at is not None and approval.expires_at <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Исполнять можно только approved заявку.",
            )

        snapshot = approval.payload_snapshot or {}
        player_id = snapshot.get("playerId") or approval.target_entity_id
        direction = snapshot.get("direction")
        amount = snapshot.get("amount")
        reason = approval.reason or snapshot.get("reason") or ""

        if direction not in ("credit", "debit") or not isinstance(amount, int) or amount <= 0:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="invalid_payload_snapshot",
                request=request,
            )

        player = session.get(GamePlayer, player_id)
        if player is None:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="player_not_found",
                request=request,
            )

        wallet = _get_wallet_for_update(session, player_id)
        reference_type = (
            ADMIN_CREDIT_REFERENCE_TYPE if direction == "credit" else ADMIN_DEBIT_REFERENCE_TYPE
        )
        if wallet is not None:
            duplicate = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == reference_type,
                    WalletTransaction.reference_id == approval.request_id,
                )
            )
            if duplicate is not None:
                return _execution_failed_response(
                    session=session,
                    actor=admin,
                    approval=approval,
                    error_code="idempotency_conflict",
                    request=request,
                )

        try:
            transaction = _apply_wallet_adjustment(
                session=session,
                wallet=wallet,
                player_id=player_id,
                direction=direction,
                amount=amount,
                reason=reason,
                request_id=approval.request_id,
                admin=admin,
                request=request,
                approval=approval,
            )
        except WalletAdjustmentError as error:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code=error.code,
                request=request,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности проводки: заявка переиспользует requestId.",
            ) from error

        result_wallet = wallet if wallet is not None else session.get(Wallet, transaction.wallet_id)

        before_approval = _serialize_approval(approval)
        approval.status = EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "playerId": player_id,
            "direction": direction,
            "amount": amount,
            "transactionId": transaction.id,
            "balanceAfter": transaction.balance_after,
        }
        approval.execution_error = None
        session.flush()

        after_approval = _serialize_approval(approval)
        _audit_approval(
            session=session,
            actor=admin,
            approval=approval,
            action="admin_approval_request.executed",
            before=before_approval,
            after=after_approval,
            outcome="success",
            request=request,
            metadata={
                "actionType": approval.action_type,
                "targetEntityType": approval.target_entity_type,
                "targetEntityId": approval.target_entity_id,
                "walletDirection": direction,
                "amountAtomic": amount,
                "transactionId": transaction.id,
            },
        )

        result = _serialize_wallet_adjustment_result(transaction, result_wallet, idempotent=False)
        return {"approval": after_approval, **result}