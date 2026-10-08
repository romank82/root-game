"""Админ-операции ограничений игрока (шаг 5.7): создать и снять ограничение.

- POST /api/v1/admin/players/{player_id}/restrictions
  Создать ограничение (chat/transfer/team/mission/payment/withdrawal_restricted,
  suspended, blocked) с причиной, окном действия и аудитом. При
  direct-grant — прямое исполнение (200); при
  requires_super_admin_approval — 201 (approval-заявка
  player.restriction_create).
- POST /api/v1/admin/players/restriction-requests/{approval_id}/execute
  Dedicated executor для супер-админа (только player.restriction_create).
- POST /api/v1/admin/players/{player_id}/restrictions/{restriction_id}/revoke
  Снять ограничение (lifecycle active -> revoked) с причиной и аудитом.
- POST /api/v1/admin/players/restriction-revoke-requests/{approval_id}/execute
  Dedicated executor для супер-админа (только player.restriction_revoke).

Маппинг прав: blocked/suspended -> players.block; остальные 6 типов ->
players.restrict. Тот же permission используется в заявке
(required_permission_code) и в аудите.

Источник истины — PlayerRestriction; GamePlayer.status — кэш-агрегат.
recompute_player_status вызывается ВСЕГДА при создании и снятии
(write-through, не только для gate-типов — подтверждено в плане 5.7).
Ленивая синхронизация кэша из auth-гейтов живёт в player_restrictions_engine
и вызывается из main/mission_engine.

Идемпотентность по request_id (вариант B, как в 5.6): признаком «этот
request_id уже применили» служит immutable admin_audit_log. Для create
entity_id = новый PlayerRestriction.id (генерируется до flush), поэтому
replay ищет audit по request_id и отдаёт созданное ограничение; повторное
использование request_id с другим содержимым -> 409. Для revoke
entity_id = PlayerRestriction.id (как в mission-cancel), снятие уже
снятого/истёкшего другим request_id -> 409.

Активное ограничение того же типа у игрока уже есть -> 409
(unique-индекс uq_player_restrictions_active_per_type — страховка от гонки).
Аудиты пишутся только после успешного flush.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
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
    AdminAuditLog,
    AdminUser,
    GamePlayer,
    PlayerRestriction,
)
from app.player_restrictions_engine import (
    ACTIVE_RESTRICTION_STATUS,
    REVOKED_RESTRICTION_STATUS,
    VALID_RESTRICTION_TYPES,
    get_active_restrictions,
    recompute_player_status,
)

router = APIRouter(prefix="/api/v1/admin/players", tags=["admin-player-restrictions"])

# --- Доменные константы -----------------------------------------------------
PLAYERS_RESTRICT_PERMISSION = "players.restrict"
PLAYERS_BLOCK_PERMISSION = "players.block"

ACTION_TYPE_RESTRICTION_CREATE = "player.restriction_create"
ACTION_TYPE_RESTRICTION_REVOKE = "player.restriction_revoke"

# blocked/suspended запирают доступ -> players.block; остальные типы -> restrict.
RESTRICTION_TYPE_TO_PERMISSION: dict[str, str] = {
    "chat_restricted": PLAYERS_RESTRICT_PERMISSION,
    "transfer_restricted": PLAYERS_RESTRICT_PERMISSION,
    "team_restricted": PLAYERS_RESTRICT_PERMISSION,
    "mission_restricted": PLAYERS_RESTRICT_PERMISSION,
    "payment_restricted": PLAYERS_RESTRICT_PERMISSION,
    "withdrawal_restricted": PLAYERS_RESTRICT_PERMISSION,
    "suspended": PLAYERS_BLOCK_PERMISSION,
    "blocked": PLAYERS_BLOCK_PERMISSION,
}

REASON_MAX_LENGTH = 4_000
EVIDENCE_MAX_LENGTH = 4_000
REQUEST_ID_MAX_LENGTH = 64
class RestrictionPayload(BaseModel):
    """Создание ограничения (шаг 5.7)."""

    restriction_type: str = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)
    # Идемпотентный ключ операции. Повтор того же request_id уже применённой
    # операции -> 200 idempotent; вместе с другим содержимым -> 409.
    request_id: str = Field(min_length=1, max_length=REQUEST_ID_MAX_LENGTH)
    # Окно действия ограничения. expiresAt используется и как дедлайн заявки
    # на одобрение (выполнение после него -> 409).
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    evidence: str | None = Field(default=None, max_length=EVIDENCE_MAX_LENGTH)


class RestrictionRevokePayload(BaseModel):
    """Снятие ограничения (шаг 5.7)."""

    reason: str = Field(min_length=1, max_length=REASON_MAX_LENGTH)
    request_id: str = Field(min_length=1, max_length=REQUEST_ID_MAX_LENGTH)
    # Дедлайн заявки на одобрение (для approval-ветки).
    expires_at: datetime | None = None


class RestrictionHTTPError(Exception):
    """Доменная ошибка модуля ограничений с machine-readable code."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


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


def _is_expired(value: datetime | None) -> bool:
    """Проверка дедлайна заявки с нормализацией tz (SQLite naive)."""
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= _now()


def _validate_restriction_window(
    starts_at: datetime | None,
    expires_at: datetime | None,
) -> None:
    """Оба поля должны быть tz-aware; expiresAt — в будущем и >= startsAt."""
    if starts_at is not None and starts_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="startsAt должен содержать timezone.",
        )
    if expires_at is not None:
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
    if starts_at is not None and expires_at is not None and expires_at < starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiresAt не может быть раньше startsAt.",
        )


def _permission_for_type(restriction_type: str) -> str | None:
    return RESTRICTION_TYPE_TO_PERMISSION.get(restriction_type)


def _find_player_restriction(
    session: Any,
    player_id: str,
    restriction_id: str,
) -> PlayerRestriction | None:
    return session.scalar(
        select(PlayerRestriction)
        .where(
            PlayerRestriction.player_id == player_id,
            PlayerRestriction.id == restriction_id,
        )
        .with_for_update()
    )
def _find_restriction_create_replay(
    session: Any,
    request_id: str,
    player_id: str,
) -> PlayerRestriction | None:
    """Создание с этим request_id уже применялось: вернуть созданное ограничение.

    Поиск по immutable admin_audit_log (entity_type=player_restriction,
    request_id, outcome=success). Если запись есть, но ограничение не найдено —
    повреждение данных (физическое удаление запрещено): повторно применять
    операцию нельзя -> 409.
    """
    audit = session.scalar(
        select(AdminAuditLog)
        .where(
            AdminAuditLog.request_id == request_id,
            AdminAuditLog.outcome == "success",
            AdminAuditLog.action.in_(
                (
                    ACTION_TYPE_RESTRICTION_CREATE,
                    f"{ACTION_TYPE_RESTRICTION_CREATE}.via_approval",
                )
            ),
        )
        .order_by(AdminAuditLog.created_at.desc())
    )
    if audit is None:
        return None

    restriction = session.get(PlayerRestriction, audit.entity_id)
    if restriction is None or restriction.player_id != player_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="requestId уже использован ранее.",
        )
    return restriction


def _find_restriction_revoke_audit(
    session: Any,
    restriction_id: str,
    request_id: str,
) -> AdminAuditLog | None:
    """Успешное снятие ограничения с этим request_id уже в immutable аудите."""
    return session.scalar(
        select(AdminAuditLog).where(
            AdminAuditLog.entity_type == "player_restriction",
            AdminAuditLog.entity_id == restriction_id,
            AdminAuditLog.request_id == request_id,
            AdminAuditLog.outcome == "success",
            AdminAuditLog.action.in_(
                (
                    ACTION_TYPE_RESTRICTION_REVOKE,
                    f"{ACTION_TYPE_RESTRICTION_REVOKE}.via_approval",
                )
            ),
        )
    )


def _serialize_restriction(restriction: PlayerRestriction) -> dict[str, Any]:
    """Та же форма, что в player-card (admin_players.py), + playerId."""
    return {
        "id": restriction.id,
        "playerId": restriction.player_id,
        "restrictionType": restriction.restriction_type,
        "status": restriction.status,
        "reason": restriction.reason,
        "evidence": restriction.evidence,
        "adminId": restriction.admin_id,
        "startsAt": (
            restriction.starts_at.isoformat()
            if getattr(restriction, "starts_at", None)
            else None
        ),
        "expiresAt": (
            restriction.expires_at.isoformat()
            if getattr(restriction, "expires_at", None)
            else None
        ),
        "approvedByApprovalId": restriction.approval_request_id,
        "revokedAt": (
            restriction.revoked_at.isoformat()
            if getattr(restriction, "revoked_at", None)
            else None
        ),
        "revocationReason": restriction.revocation_reason,
    }


def _serialize_create_result(
    restriction: PlayerRestriction,
    player_status: str,
    player_status_changed: bool,
    idempotent: bool,
) -> dict[str, Any]:
    return {
        "restriction": _serialize_restriction(restriction),
        "playerStatus": player_status,
        "playerStatusChanged": player_status_changed,
        "idempotent": idempotent,
    }


def _serialize_revoke_result(
    restriction: PlayerRestriction,
    player_status: str,
    player_status_changed: bool,
    idempotent: bool,
) -> dict[str, Any]:
    return {
        "restriction": _serialize_restriction(restriction),
        "playerStatus": player_status,
        "playerStatusChanged": player_status_changed,
        "idempotent": idempotent,
    }
def _apply_restriction_create(
    *,
    session: Any,
    player: GamePlayer,
    restriction_type: str,
    reason: str,
    request_id: str,
    admin: AdminUser,
    request: Request,
    starts_at: datetime | None,
    expires_at: datetime | None,
    evidence: str | None,
    approval: AdminApprovalRequest | None = None,
) -> tuple[PlayerRestriction, bool]:
    """Создать ограничение и синхронизировать кэш GamePlayer.status.

    Write-through: recompute_player_status выполняется ВСЕГДА после создания
    (не только для gate-типов) — кэш не расходится с источником истины.
    Idempotency: request_id в immutable аудите (entity_id = новый
    PlayerRestriction.id, генерируется до flush); активный дубль того же типа
    блокируется в роутере и на уровне БД (uq_player_restrictions_active_per_type).
    """
    previously = player.status

    restriction = PlayerRestriction(
        id=_new_id("player-restriction"),
        player_id=player.id,
        restriction_type=restriction_type,
        status=ACTIVE_RESTRICTION_STATUS,
        reason=reason,
        evidence=evidence,
        admin_id=admin.id,
        starts_at=starts_at,
        expires_at=expires_at,
        approval_request_id=approval.id if approval is not None else None,
    )
    session.add(restriction)
    session.flush()

    _, player_status_changed = recompute_player_status(session, player)

    metadata: dict[str, Any] = {
        "playerId": player.id,
        "restrictionType": restriction_type,
        "requestId": request_id,
        "startsAt": starts_at.isoformat() if starts_at is not None else None,
        "expiresAt": expires_at.isoformat() if expires_at is not None else None,
        "evidenceProvided": bool(evidence),
        "playerStatusChanged": player_status_changed,
        "fullReason": reason,
    }
    if approval is not None:
        metadata["approvalRequestId"] = approval.id

    write_admin_audit(
        session,
        actor=admin,
        action=(
            ACTION_TYPE_RESTRICTION_CREATE
            if approval is None
            else f"{ACTION_TYPE_RESTRICTION_CREATE}.via_approval"
        ),
        entity_type="player_restriction",
        entity_id=restriction.id,
        request=request,
        permission_code=RESTRICTION_TYPE_TO_PERMISSION[restriction_type],
        approval_request_id=approval.id if approval is not None else None,
        request_id=request_id,
        before={"playerStatus": previously},
        after={"playerStatus": player.status},
        # Двойная защита: recursive redaction и в audit-module, и здесь.
        metadata=sanitize_audit_data(metadata),
    )
    return restriction, player_status_changed


def _apply_restriction_revoke(
    *,
    session: Any,
    player: GamePlayer,
    restriction: PlayerRestriction,
    reason: str,
    request_id: str,
    admin: AdminUser,
    request: Request,
    approval: AdminApprovalRequest | None = None,
) -> tuple[PlayerRestriction, bool]:
    """Снять ограничение (active -> revoked) и синхронизировать кэш статуса.

    Write-through: recompute выполняется всегда — снятие может вернуть игрока
    в active либо понизить blocked -> suspended при остающемся suspension.
    Повторное снятие уже неактивного ограничения обрабатывается в роутере
    (replay -> 200 idempotent; иначе 409).
    """
    previously = player.status

    restriction.status = REVOKED_RESTRICTION_STATUS
    restriction.revoked_by_admin_id = admin.id
    restriction.revoked_at = _now()
    restriction.revocation_reason = reason
    session.flush()

    _, player_status_changed = recompute_player_status(session, player)

    metadata: dict[str, Any] = {
        "playerId": player.id,
        "restrictionType": restriction.restriction_type,
        "requestId": request_id,
        "playerStatusChanged": player_status_changed,
        "fullReason": reason,
    }
    if approval is not None:
        metadata["approvalRequestId"] = approval.id

    write_admin_audit(
        session,
        actor=admin,
        action=(
            ACTION_TYPE_RESTRICTION_REVOKE
            if approval is None
            else f"{ACTION_TYPE_RESTRICTION_REVOKE}.via_approval"
        ),
        entity_type="player_restriction",
        entity_id=restriction.id,
        request=request,
        permission_code=RESTRICTION_TYPE_TO_PERMISSION[restriction.restriction_type],
        approval_request_id=approval.id if approval is not None else None,
        request_id=request_id,
        before={
            "restrictionStatus": ACTIVE_RESTRICTION_STATUS,
            "playerStatus": previously,
        },
        after={
            "restrictionStatus": REVOKED_RESTRICTION_STATUS,
            "playerStatus": player.status,
        },
        # Двойная защита: recursive redaction и в audit-module, и здесь.
        metadata=sanitize_audit_data(metadata),
    )
    return restriction, player_status_changed
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
def _create_restriction_request(
    *,
    session: Any,
    admin: AdminUser,
    player_id: str,
    restriction_type: str,
    reason: str,
    request_id: str,
    starts_at: datetime | None,
    expires_at: datetime | None,
    evidence: str | None,
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на ограничение (idempotency по request_id).

    При повторном request_id с тем же содержимым отвечает 200 + idempotent,
    с другим содержимым — 409. expiresAt ограничения становится и дедлайном
    заявки на одобрение.
    """
    permission = RESTRICTION_TYPE_TO_PERMISSION[restriction_type]
    snapshot = {
        "playerId": player_id,
        "restrictionType": restriction_type,
        "reason": reason,
        "startsAt": starts_at.isoformat() if starts_at is not None else None,
        "expiresAt": expires_at.isoformat() if expires_at is not None else None,
        "evidence": evidence,
    }
    expected = {
        "required_permission_code": permission,
        "action_type": ACTION_TYPE_RESTRICTION_CREATE,
        "target_entity_type": "player_restriction",
        "target_entity_id": None,
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
        required_permission_code=permission,
        action_type=ACTION_TYPE_RESTRICTION_CREATE,
        target_entity_type="player_restriction",
        target_entity_id=None,
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
def _create_revoke_request(
    *,
    session: Any,
    admin: AdminUser,
    player_id: str,
    restriction: PlayerRestriction,
    reason: str,
    request_id: str,
    expires_at: datetime | None,
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на снятие ограничения (idempotency по request_id)."""
    permission = RESTRICTION_TYPE_TO_PERMISSION[restriction.restriction_type]
    snapshot = {
        "playerId": player_id,
        "restrictionId": restriction.id,
        "restrictionType": restriction.restriction_type,
        "reason": reason,
    }
    expected = {
        "required_permission_code": permission,
        "action_type": ACTION_TYPE_RESTRICTION_REVOKE,
        "target_entity_type": "player_restriction",
        "target_entity_id": restriction.id,
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
        required_permission_code=permission,
        action_type=ACTION_TYPE_RESTRICTION_REVOKE,
        target_entity_type="player_restriction",
        target_entity_id=restriction.id,
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
@router.post("/{player_id}/restrictions", response_model=None)
def create_player_restriction(
    player_id: str,
    payload: RestrictionPayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
) -> dict[str, Any] | JSONResponse:
    """Создать ограничение игрока: прямое исполнение либо approval-заявка.

    Permission берётся от типа ограничения: blocked/suspended -> players.block,
    иные 6 типов -> players.restrict (см. RESTRICTION_TYPE_TO_PERMISSION).
    Идемпотентность — replay из immutable admin_audit_log; активное
    ограничение того же типа -> 409. GamePlayer.status синхронизируется
    всегда (write-through).
    """
    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")
    _validate_restriction_window(payload.starts_at, payload.expires_at)

    restriction_type = payload.restriction_type.strip()
    permission = _permission_for_type(restriction_type)
    if permission is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Неизвестный тип ограничения.",
        )

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Игрок не найден.",
            )

        execution_mode = get_permission_execution_mode(admin, permission)
        if execution_mode is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        # Idempotent replay: тот же request_id уже применили -> 200 idempotent
        # (независимо от текущего статуса ограничения — снятие/expiry не
        # аннулирует исторический факт применения).
        replay = _find_restriction_create_replay(session, request_id, player_id)
        if replay is not None:
            if replay.restriction_type != restriction_type:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="requestId уже использован с другим содержимым.",
                )
            return _serialize_create_result(
                replay,
                player.status,
                player_status_changed=False,
                idempotent=True,
            )

        # Активный дубль типа блокируем; уникальный частичный индекс
        # uq_player_restrictions_active_per_type — страховка от гонки.
        active = get_active_restrictions(session, player_id)
        if any(r.restriction_type == restriction_type for r in active):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Активное ограничение этого типа уже действует на игрока.",
            )

        if execution_mode == APPROVAL_EXECUTION_MODE:
            return _create_restriction_request(
                session=session,
                admin=admin,
                player_id=player_id,
                restriction_type=restriction_type,
                reason=reason,
                request_id=request_id,
                starts_at=payload.starts_at,
                expires_at=payload.expires_at,
                evidence=payload.evidence,
                request=request,
            )

        try:
            restriction, changed = _apply_restriction_create(
                session=session,
                player=player,
                restriction_type=restriction_type,
                reason=reason,
                request_id=request_id,
                admin=admin,
                request=request,
                starts_at=payload.starts_at,
                expires_at=payload.expires_at,
                evidence=payload.evidence,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности: активное ограничение этого типа уже есть.",
            ) from error

        return _serialize_create_result(
            restriction,
            player.status,
            changed,
            idempotent=False,
        )
@router.post(
    "/{player_id}/restrictions/{restriction_id}/revoke",
    response_model=None,
)
def revoke_player_restriction(
    player_id: str,
    restriction_id: str,
    payload: RestrictionRevokePayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
) -> dict[str, Any] | JSONResponse:
    """Снять ограничение игрока (active -> revoked): direct либо approval-заявка.

    Permission — от типа снимаемого ограничения (players.block | players.restrict).
    Повторный revoke уже снятого/истёкшего ограничения: тот же request_id ->
    200 idempotent, иной -> 409.
    """
    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Игрок не найден.",
            )

        restriction = _find_player_restriction(session, player_id, restriction_id)
        if restriction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Ограничение не найдено.",
            )

        permission = RESTRICTION_TYPE_TO_PERMISSION.get(restriction.restriction_type)
        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Неизвестный тип ограничения.",
            )

        execution_mode = get_permission_execution_mode(admin, permission)
        if execution_mode is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        if restriction.status != ACTIVE_RESTRICTION_STATUS:
            # Idempotent replay: тот же request_id -> 200 idempotent.
            replay = _find_restriction_revoke_audit(session, restriction.id, request_id)
            if replay is not None:
                return _serialize_revoke_result(
                    restriction,
                    player.status,
                    player_status_changed=False,
                    idempotent=True,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ограничение уже снято или истекло.",
            )

        if execution_mode == APPROVAL_EXECUTION_MODE:
            return _create_revoke_request(
                session=session,
                admin=admin,
                player_id=player_id,
                restriction=restriction,
                reason=reason,
                request_id=request_id,
                expires_at=payload.expires_at,
                request=request,
            )

        try:
            updated, changed = _apply_restriction_revoke(
                session=session,
                player=player,
                restriction=restriction,
                reason=reason,
                request_id=request_id,
                admin=admin,
                request=request,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности снятия ограничения.",
            ) from error

        return _serialize_revoke_result(
            updated,
            player.status,
            changed,
            idempotent=False,
        )
def _parse_datetime_snapshot(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        return parsed
    return parsed.replace(tzinfo=timezone.utc)


@router.post("/restriction-requests/{approval_id}/execute", response_model=None)
def execute_player_restriction_create(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
) -> dict[str, Any] | JSONResponse:
    """Исполнить approved заявку на создание ограничения супер-админом.

    Никакого generic executor: принимается исключительно
    action_type == player.restriction_create.
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

        if approval.action_type != ACTION_TYPE_RESTRICTION_CREATE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Executor принимает только player.restriction_create.",
            )

        if approval.status == EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        if _is_expired(approval.expires_at):
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
        restriction_type = snapshot.get("restrictionType")
        reason = approval.reason or snapshot.get("reason") or ""
        starts_at = _parse_datetime_snapshot(snapshot.get("startsAt"))
        expires_at = _parse_datetime_snapshot(snapshot.get("expiresAt"))
        evidence = snapshot.get("evidence")

        if (
            not isinstance(restriction_type, str)
            or restriction_type not in VALID_RESTRICTION_TYPES
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

        # Решение уже было применено тем же request_id (например, тем же
        # request_id в direct-пути): не дублируем, помечаем заявку EXECUTED.
        replay = _find_restriction_create_replay(session, approval.request_id, player_id)
        if replay is not None:
            before = _serialize_approval(approval)
            approval.status = EXECUTED
            approval.executed_by_admin_id = admin.id
            approval.executed_at = _now()
            approval.execution_result = {
                "status": "executed",
                "playerId": player_id,
                "restrictionId": replay.id,
                "restrictionType": replay.restriction_type,
                "idempotent": True,
            }
            approval.execution_error = None
            session.flush()
            after = _serialize_approval(approval)
            _audit_approval(
                session=session,
                actor=admin,
                approval=approval,
                action="admin_approval_request.executed",
                before=before,
                after=after,
                outcome="success",
                request=request,
                metadata={
                    "actionType": approval.action_type,
                    "targetEntityType": approval.target_entity_type,
                    "targetEntityId": approval.target_entity_id,
                    "restrictionId": replay.id,
                    "idempotent": True,
                },
            )
            return {"approval": after, "idempotent": True}

        active = get_active_restrictions(session, player_id)
        if any(r.restriction_type == restriction_type for r in active):
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="duplicate_active_restriction",
                request=request,
            )

        try:
            restriction, changed = _apply_restriction_create(
                session=session,
                player=player,
                restriction_type=restriction_type,
                reason=reason,
                request_id=approval.request_id,
                admin=admin,
                request=request,
                starts_at=starts_at,
                expires_at=expires_at,
                evidence=evidence if isinstance(evidence, str) else None,
                approval=approval,
            )
        except IntegrityError as error:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="duplicate_active_restriction",
                request=request,
            )
        before_approval = _serialize_approval(approval)
        approval.status = EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "playerId": player_id,
            "restrictionId": restriction.id,
            "restrictionType": restriction.restriction_type,
            "playerStatus": player.status,
            "playerStatusChanged": changed,
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
                "restrictionId": restriction.id,
                "playerStatus": player.status,
                "playerStatusChanged": changed,
            },
        )

        result = _serialize_create_result(
            restriction,
            player.status,
            changed,
            idempotent=False,
        )
        return {"approval": after_approval, **result}
@router.post("/restriction-revoke-requests/{approval_id}/execute", response_model=None)
def execute_player_restriction_revoke(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
) -> dict[str, Any] | JSONResponse:
    """Исполнить approved заявку на снятие ограничения супер-админом.

    Никакого generic executor: принимается исключительно
    action_type == player.restriction_revoke.
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

        if approval.action_type != ACTION_TYPE_RESTRICTION_REVOKE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Executor принимает только player.restriction_revoke.",
            )

        if approval.status == EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        if _is_expired(approval.expires_at):
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
        restriction_id = snapshot.get("restrictionId") or approval.target_entity_id
        reason = approval.reason or snapshot.get("reason") or ""

        if not isinstance(restriction_id, str) or not restriction_id:
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

        restriction = _find_player_restriction(session, player_id, restriction_id)
        if restriction is None:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="restriction_not_found",
                request=request,
            )

        if restriction.status != ACTIVE_RESTRICTION_STATUS:
            # Уже снято/истекло тем же request_id -> idempotent-результат.
            replay = _find_restriction_revoke_audit(
                session, restriction.id, approval.request_id
            )
            if replay is not None:
                before = _serialize_approval(approval)
                approval.status = EXECUTED
                approval.executed_by_admin_id = admin.id
                approval.executed_at = _now()
                approval.execution_result = {
                    "status": "executed",
                    "playerId": player_id,
                    "restrictionId": restriction.id,
                    "restrictionType": restriction.restriction_type,
                    "idempotent": True,
                }
                approval.execution_error = None
                session.flush()
                after = _serialize_approval(approval)
                _audit_approval(
                    session=session,
                    actor=admin,
                    approval=approval,
                    action="admin_approval_request.executed",
                    before=before,
                    after=after,
                    outcome="success",
                    request=request,
                    metadata={
                        "actionType": approval.action_type,
                        "targetEntityType": approval.target_entity_type,
                        "targetEntityId": approval.target_entity_id,
                        "restrictionId": restriction.id,
                        "idempotent": True,
                    },
                )
                return {"approval": after, "idempotent": True}
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="restriction_already_inactive",
                request=request,
            )

        try:
            updated, changed = _apply_restriction_revoke(
                session=session,
                player=player,
                restriction=restriction,
                reason=reason,
                request_id=approval.request_id,
                admin=admin,
                request=request,
                approval=approval,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности: заявка переиспользует requestId.",
            ) from error