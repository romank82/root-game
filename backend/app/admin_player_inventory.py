"""Админ-операции инвентаря игрока: ручная выдача/отзыв ключей (шаг 5.5).

- POST /api/v1/admin/players/{player_id}/inventory-item-adjustment
  Прямое исполнение при direct-grant; при approval-grant или
  quantity >= gameplay.manual_item_adjustment_approval_threshold
  (для не-super-admin) создаёт AdminApprovalRequest и отвечает 201.
- POST /api/v1/admin/players/inventory-item-adjustment-requests/{approval_id}/execute
  Dedicated executor для супер-админа: применяет approved-заявку
  (action_type player.inventory_grant | player.inventory_revoke).

Все изменения инвентаря — ровно одна immutable InventoryEvent-проводка
(reference_type=admin_item_grant|admin_item_revoke, reference_id=request_id,
quantity_delta != 0); PlayerItem.quantity меняется только внутри этой
проводки. Идемпотентность по (player_item_id, event_type, reference_type,
reference_id) для событий и по (requested_by_admin_id, request_id) для заявок.
Игровые ограничения предмета (sale_forbidden, transfer_forbidden,
trade_forbidden, stack_limit, is_consumable) админ-выдачу/отзыв не блокируют.
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
from app.datetime_utils import ensure_utc
from app.db import SessionLocal
from app.models import (
    AdminApprovalRequest,
    AdminUser,
    GamePlayer,
    InventoryEvent,
    Item,
    PlayerItem,
    SystemSetting,
)
from app.system_settings_catalog import get_definition

router = APIRouter(prefix="/api/v1/admin/players", tags=["admin-player-inventory"])

# --- Доменные константы -----------------------------------------------------
PLAYERS_MANAGE_PERMISSION = "players.manage"
ADMIN_GRANT_REFERENCE_TYPE = "admin_item_grant"
ADMIN_REVOKE_REFERENCE_TYPE = "admin_item_revoke"
ACTION_TYPE_GRANT = "player.inventory_grant"
ACTION_TYPE_REVOKE = "player.inventory_revoke"
MANUAL_ITEM_ADJUSTMENT_THRESHOLD_KEY = (
    "gameplay.manual_item_adjustment_approval_threshold"
)
DEFAULT_MANUAL_ITEM_ADJUSTMENT_THRESHOLD = 5
MAX_REASON_METADATA = 4_000
OBTAINED_FROM_TYPE = "admin_manual"
ACTIVE_SETTING_STATUS = "active"


class InventoryAdjustmentError(Exception):
    """Доменная ошибка inventory-adjustment с machine-readable code."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class InventoryItemAdjustmentPayload(BaseModel):
    direction: Literal["grant", "revoke"]
    item_id: str = Field(min_length=1, max_length=64)
    quantity: int = Field(ge=1, le=1_000)
    reason: str = Field(min_length=1, max_length=4_000)
    # request_id копируется в inventory_events.reference_id, а это
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
    """Порог approval для ручной выдачи/отзыва ключей (шаг 5.5).

    Приоритет: активная SystemSetting-запись -> default каталога ->
    DEFAULT_MANUAL_ITEM_ADJUSTMENT_THRESHOLD.
    """
    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == MANUAL_ITEM_ADJUSTMENT_THRESHOLD_KEY,
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
    definition = get_definition(MANUAL_ITEM_ADJUSTMENT_THRESHOLD_KEY)
    if definition is not None and isinstance(definition.default_value, int):
        return definition.default_value
    return DEFAULT_MANUAL_ITEM_ADJUSTMENT_THRESHOLD


def _serialize_inventory_event(event: InventoryEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "playerItemId": event.player_item_id,
        "eventType": event.event_type,
        "quantityDelta": event.quantity_delta,
        "referenceType": event.reference_type,
        "referenceId": event.reference_id,
        "metadata": sanitize_audit_data(event.metadata_json or {}),
        "createdAt": (
            getattr(event, "created_at", None).isoformat()
            if getattr(event, "created_at", None)
            else None
        ),
    }


def _serialize_inventory_adjustment_result(
    event: InventoryEvent, player_item: PlayerItem, idempotent: bool
) -> dict[str, Any]:
    return {
        "inventoryEvent": _serialize_inventory_event(event),
        "playerItem": {
            "id": player_item.id,
            "playerId": player_item.player_id,
            "itemId": player_item.item_id,
            "quantity": player_item.quantity,
        },
        "idempotent": idempotent,
    }


def _apply_inventory_adjustment(
    session: Any,
    *,
    player_id: str,
    direction: str,
    item_id: str,
    quantity: int,
    reason: str,
    request_id: str,
    admin: AdminUser,
    request: Request,
    approval: AdminApprovalRequest | None = None,
) -> tuple[InventoryEvent, PlayerItem]:
    """Создать ровно одну immutable InventoryEvent-проводку (grant/revoke).

    quantity всегда > 0, направление задаётся event_type
    (credited | consumed). grant требует Item.status == "published"; revoke
    статус не проверяет, но требует существующую строку PlayerItem и
    количество >= quantity. Для grant при отсутствии строки она создаётся
    с obtained_from_type="admin_manual" и obtained_from_id=request_id.
    Игровые player-ограничения админ-операции не блокируют.
    Аудит пишется только после успешного flush.
    """
    if direction not in ("grant", "revoke"):
        raise InventoryAdjustmentError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_direction",
            "Направление должно быть grant или revoke.",
        )

    item = session.get(Item, item_id)
    if item is None:
        raise InventoryAdjustmentError(
            status.HTTP_409_CONFLICT,
            "item_not_found",
            "Предмет не найден.",
        )
    if direction == "grant" and item.status != "published":
        raise InventoryAdjustmentError(
            status.HTTP_409_CONFLICT,
            "item_not_available",
            "Предмет не в статусе published.",
        )

    player_item = session.scalar(
        select(PlayerItem)
        .where(
            PlayerItem.player_id == player_id,
            PlayerItem.item_id == item_id,
        )
        .with_for_update()
    )

    if direction == "revoke":
        if player_item is None:
            raise InventoryAdjustmentError(
                status.HTTP_409_CONFLICT,
                "player_item_missing",
                "У игрока нет этого предмета.",
            )
        if player_item.quantity < quantity:
            raise InventoryAdjustmentError(
                status.HTTP_409_CONFLICT,
                "insufficient_quantity",
                "Недостаточное количество предмета для списания.",
            )
    elif player_item is None:
        # grant: строки нет — создаём с нулевым балансом и сразу начисляем.
        player_item = PlayerItem(
            id=_new_id("player-item"),
            player_id=player_id,
            item_id=item_id,
            quantity=0,
            obtained_from_type=OBTAINED_FROM_TYPE,
            obtained_from_id=request_id,
        )
        session.add(player_item)
        session.flush()

    before_quantity = player_item.quantity
    new_quantity = before_quantity + (quantity if direction == "grant" else -quantity)
    player_item.quantity = new_quantity

    event_type = "credited" if direction == "grant" else "consumed"
    reference_type = (
        ADMIN_GRANT_REFERENCE_TYPE
        if direction == "grant"
        else ADMIN_REVOKE_REFERENCE_TYPE
    )
    metadata = {
        "requestId": request_id,
        "playerId": player_id,
        "itemId": item_id,
        "direction": direction,
        "amountAtomic": quantity,
        "fullReason": reason[:MAX_REASON_METADATA] if reason else "",
        "initiatedByType": "admin",
        "initiatedByAdminId": admin.id,
    }
    if approval is not None:
        metadata["approvalRequestId"] = approval.id

    event = InventoryEvent(
        id=_new_id("inventory-event"),
        player_item_id=player_item.id,
        event_type=event_type,
        quantity_delta=quantity if direction == "grant" else -quantity,
        reference_type=reference_type,
        reference_id=request_id,
        metadata_json=sanitize_audit_data(metadata),
    )
    session.add(event)
    session.flush()

    write_admin_audit(
        session,
        actor=admin,
        action=(
            f"player.inventory_{direction}"
            if approval is None
            else f"player.inventory_{direction}.via_approval"
        ),
        entity_type="player",
        entity_id=player_id,
        request=request,
        permission_code=PLAYERS_MANAGE_PERMISSION,
        approval_request_id=approval.id if approval is not None else None,
        request_id=request_id,
        before={"quantity": before_quantity},
        after={"quantity": new_quantity},
        metadata={
            "direction": direction,
            "itemId": item_id,
            "amountAtomic": quantity,
            "referenceType": reference_type,
            "referenceId": request_id,
        },
    )
    return event, player_item


def _existing_event_matches(
    existing: InventoryEvent, direction: str, quantity: int
) -> bool:
    """Тот же request_id и то же содержимое — безопасный идемпотентный replay."""
    metadata = existing.metadata_json or {}
    expected_delta = quantity if direction == "grant" else -quantity
    return (
        existing.quantity_delta == expected_delta
        and metadata.get("amountAtomic") == quantity
        and metadata.get("direction") == direction
    )


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
    """Финальный consumed-статус EXECUTION_FAILED с аудитом (паттерн 5.x).

    ФИКС 1: execution_error — строка (модель: Mapped[str | None] / Text).
    ФИКС 2: возвращает сериализованное after, чтобы
    _execution_failed_response собрала JSONResponse(409).
    """
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


def _create_inventory_adjustment_request(
    *,
    session: Any,
    admin: AdminUser,
    player_id: str,
    direction: str,
    item_id: str,
    quantity: int,
    reason: str,
    request_id: str,
    expires_at: datetime | None,
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на inventory-adjustment (idempotency по request_id).

    При повторном request_id с тем же содержимым отвечает 200 + idempotent,
    с другим содержимым — 409.
    """
    action_type = ACTION_TYPE_GRANT if direction == "grant" else ACTION_TYPE_REVOKE
    snapshot = {
        "direction": direction,
        "itemId": item_id,
        "quantity": quantity,
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


@router.post("/{player_id}/inventory-item-adjustment", response_model=None)
def create_player_inventory_item_adjustment(
    player_id: str,
    payload: InventoryItemAdjustmentPayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
) -> dict[str, Any] | JSONResponse:
    """Выдать/отозвать ключ: прямое исполнение либо создание approval-заявки.

    НЕ использует require_permission: для approval-ветки нужно самим считать
    execution_mode через get_permission_execution_mode (как admin_system_settings).
    """
    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")
    direction = payload.direction
    item_id = payload.item_id
    quantity = payload.quantity
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
            not admin.is_super_admin and quantity >= threshold
        )

        if needs_approval:
            return _create_inventory_adjustment_request(
                session=session,
                admin=admin,
                player_id=player_id,
                direction=direction,
                item_id=item_id,
                quantity=quantity,
                reason=reason,
                request_id=request_id,
                expires_at=expires_at,
                request=request,
            )

        # Прямое исполнение.
        reference_type = (
            ADMIN_GRANT_REFERENCE_TYPE
            if direction == "grant"
            else ADMIN_REVOKE_REFERENCE_TYPE
        )
        event_type = "credited" if direction == "grant" else "consumed"
        player_item = session.scalar(
            select(PlayerItem)
            .where(
                PlayerItem.player_id == player_id,
                PlayerItem.item_id == item_id,
            )
            .with_for_update()
        )

        if player_item is not None:
            existing = session.scalar(
                select(InventoryEvent).where(
                    InventoryEvent.player_item_id == player_item.id,
                    InventoryEvent.event_type == event_type,
                    InventoryEvent.reference_type == reference_type,
                    InventoryEvent.reference_id == request_id,
                )
            )
            if existing is not None:
                if _existing_event_matches(existing, direction, quantity):
                    return _serialize_inventory_adjustment_result(
                        existing, player_item, idempotent=True
                    )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="requestId уже использован с другим содержимым проводки.",
                )

        try:
            event, player_item = _apply_inventory_adjustment(
                session=session,
                player_id=player_id,
                direction=direction,
                item_id=item_id,
                quantity=quantity,
                reason=reason,
                request_id=request_id,
                admin=admin,
                request=request,
            )
        except InventoryAdjustmentError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности: requestId уже использован для этого предмета.",
            ) from error

        return _serialize_inventory_adjustment_result(event, player_item, idempotent=False)


@router.post(
    "/inventory-item-adjustment-requests/{approval_id}/execute",
    response_model=None,
)
def execute_player_inventory_item_adjustment(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
) -> dict[str, Any] | JSONResponse:
    """Исполнить approved заявку на grant/revoke только супер-админом.

    Никакого generic executor: принимаются исключительно
    player.inventory_grant и player.inventory_revoke.
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

        if approval.action_type not in (ACTION_TYPE_GRANT, ACTION_TYPE_REVOKE):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Executor принимает только player.inventory_grant и player.inventory_revoke.",
            )

        if approval.status == EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        expires_at = ensure_utc(approval.expires_at)
        if expires_at is not None and expires_at <= _now():
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
        quantity = snapshot.get("quantity")
        item_id = snapshot.get("itemId")
        reason = approval.reason or snapshot.get("reason") or ""

        if (
            direction not in ("grant", "revoke")
            or not isinstance(quantity, int)
            or quantity <= 0
            or not isinstance(item_id, str)
            or not item_id
        ):
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

        player_item = session.scalar(
            select(PlayerItem)
            .where(
                PlayerItem.player_id == player_id,
                PlayerItem.item_id == item_id,
            )
            .with_for_update()
        )
        event_type = "credited" if direction == "grant" else "consumed"
        reference_type = (
            ADMIN_GRANT_REFERENCE_TYPE
            if direction == "grant"
            else ADMIN_REVOKE_REFERENCE_TYPE
        )
        if player_item is not None:
            duplicate = session.scalar(
                select(InventoryEvent).where(
                    InventoryEvent.player_item_id == player_item.id,
                    InventoryEvent.event_type == event_type,
                    InventoryEvent.reference_type == reference_type,
                    InventoryEvent.reference_id == approval.request_id,
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
            event, player_item = _apply_inventory_adjustment(
                session=session,
                player_id=player_id,
                direction=direction,
                item_id=item_id,
                quantity=quantity,
                reason=reason,
                request_id=approval.request_id,
                admin=admin,
                request=request,
                approval=approval,
            )
        except InventoryAdjustmentError as error:
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

        before_approval = _serialize_approval(approval)
        approval.status = EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "playerId": player_id,
            "direction": direction,
            "itemId": item_id,
            "quantity": quantity,
            "inventoryEventId": event.id,
            "quantityAfter": player_item.quantity,
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
                "inventoryDirection": direction,
                "itemId": item_id,
                "amountAtomic": quantity,
                "inventoryEventId": event.id,
            },
        )

        result = _serialize_inventory_adjustment_result(event, player_item, idempotent=False)
        return {"approval": after_approval, **result}