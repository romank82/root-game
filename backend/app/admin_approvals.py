from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.admin_access import (
    APPROVAL_EXECUTION_MODE,
    DIRECT_EXECUTION_MODE,
    get_admin_user,
    get_permission_execution_mode,
    require_super_admin,
)
from app.db import SessionLocal
from app.models import AdminApprovalRequest, AdminAuditLog, AdminUser

router = APIRouter(prefix="/api/v1/admin/approvals", tags=["admin-approvals"])

PENDING = "pending"
APPROVED = "approved"
REJECTED = "rejected"
EXPIRED = "expired"
CANCELLED = "cancelled"
EXECUTED = "executed"
EXECUTION_FAILED = "execution_failed"

SYSTEM_SETTING_CHANGE_ACTION = "system_setting.change"

class CreateApprovalPayload(BaseModel):
    required_permission_code: str = Field(min_length=3, max_length=128)
    action_type: str = Field(min_length=3, max_length=128)
    target_entity_type: str = Field(min_length=3, max_length=64)
    target_entity_id: str | None = Field(default=None, max_length=64)
    payload_snapshot: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=4_000)
    request_id: str = Field(min_length=8, max_length=128)
    expires_at: datetime | None = None

class ReviewApprovalPayload(BaseModel):
    comment: str | None = Field(default=None, max_length=4_000)


class CancelApprovalPayload(BaseModel):
    reason: str = Field(min_length=3, max_length=4_000)

def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"

def _client_ip_address(request: Request) -> str | None:
    """Use only the direct peer address; forwarded headers are untrusted."""
    return request.client.host if request.client else None

def _normalize_required(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Поле не может состоять только из пробелов.",
        )
    return normalized

def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None

def _now() -> datetime:
    return datetime.now(timezone.utc)

def _is_expired(approval: AdminApprovalRequest, now: datetime) -> bool:
    return approval.expires_at is not None and approval.expires_at <= now

def _serialize(approval: AdminApprovalRequest) -> dict[str, Any]:
    return {
        "id": approval.id,
        "status": approval.status,
        "requestedByAdminId": approval.requested_by_admin_id,
        "requiredPermissionCode": approval.required_permission_code,
        "actionType": approval.action_type,
        "targetEntityType": approval.target_entity_type,
        "targetEntityId": approval.target_entity_id,
        "payloadSnapshot": approval.payload_snapshot,
        "reason": approval.reason,
        "requestId": approval.request_id,
        "expiresAt": (
            approval.expires_at.isoformat()
            if approval.expires_at is not None
            else None
        ),
        "approvedByAdminId": approval.approved_by_admin_id,
        "approvedAt": (
            approval.approved_at.isoformat()
            if approval.approved_at is not None
            else None
        ),
        "approvalComment": approval.approval_comment,
        "rejectedByAdminId": approval.rejected_by_admin_id,
        "rejectedAt": (
            approval.rejected_at.isoformat()
            if approval.rejected_at is not None
            else None
        ),
        "rejectionComment": approval.rejection_comment,
        "cancelledByAdminId": approval.cancelled_by_admin_id,
        "cancelledAt": (
            approval.cancelled_at.isoformat()
            if approval.cancelled_at is not None
            else None
        ),
        "cancellationReason": approval.cancellation_reason,
        "executedByAdminId": approval.executed_by_admin_id,
        "executedAt": (
            approval.executed_at.isoformat()
            if approval.executed_at is not None
            else None
        ),
        "executionResult": approval.execution_result,
        "executionError": approval.execution_error,
        "createdAt": approval.created_at.isoformat() if approval.created_at else None,
        "updatedAt": approval.updated_at.isoformat() if approval.updated_at else None,
    }

def _audit(
    session: Any,
    *,
    actor: AdminUser,
    action: str,
    approval: AdminApprovalRequest,
    before: dict[str, Any],
    after: dict[str, Any],
    request: Request,
) -> None:
    session.add(
        AdminAuditLog(
            id=_new_id("admin-audit"),
            admin_user_id=actor.id,
            action=action,
            entity_type="admin_approval_request",
            entity_id=approval.id,
            permission_code=approval.required_permission_code,
            approval_request_id=approval.id,
            request_id=approval.request_id,
            reason=approval.reason,
            before_json=before,
            after_json=after,
            outcome="success",
            metadata_json={
                "actionType": approval.action_type,
                "targetEntityType": approval.target_entity_type,
                "targetEntityId": approval.target_entity_id,
            },
            ip_address=_client_ip_address(request),
        )
    )

def _expire_if_needed(
    session: Any,
    approval: AdminApprovalRequest,
    now: datetime,
) -> bool:
    if approval.status in {PENDING, APPROVED} and _is_expired(approval, now):
        approval.status = EXPIRED
        session.flush()
        return True
    return False

@router.post("", status_code=status.HTTP_201_CREATED)
def create_approval(
    payload: CreateApprovalPayload,
    request: Request,
    actor: AdminUser = Depends(get_admin_user),
):
    """
    Create an immutable approval request.

    This route never executes an action. Dedicated future executors must
    validate action_type, revalidate target state and atomically consume an
    approved request.
    """
    permission_code = _normalize_required(payload.required_permission_code)
    action_type = _normalize_required(payload.action_type)
    target_entity_type = _normalize_required(payload.target_entity_type)
    reason = _normalize_required(payload.reason)
    request_id = _normalize_required(payload.request_id)
    target_entity_id = _normalize_optional(payload.target_entity_id)

    if actor.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Супер-администратор выполняет действия напрямую и не создаёт заявку.",
        )

    # System settings requests must use their dedicated endpoint. This prevents
    # arbitrary payload snapshots from bypassing catalog/schema validation.
    if action_type == SYSTEM_SETTING_CHANGE_ACTION:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Для изменения системной настройки используйте "
                "специализированный endpoint system-settings."
            ),
        )

    execution_mode = get_permission_execution_mode(actor, permission_code)
    if execution_mode != APPROVAL_EXECUTION_MODE:
        detail = (
            "Для создания заявки требуется активный permission "
            "с режимом requires_super_admin_approval."
        )
        if execution_mode == DIRECT_EXECUTION_MODE:
            detail = "Этот permission имеет прямой режим и не требует заявки."
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
        )

    now = _now()
    if payload.expires_at is not None:
        expires_at = payload.expires_at
        if expires_at.tzinfo is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expiresAt должен содержать timezone.",
            )
        if expires_at <= now:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="expiresAt должен быть в будущем.",
            )
    else:
        expires_at = None

    expected = {
        "required_permission_code": permission_code,
        "action_type": action_type,
        "target_entity_type": target_entity_type,
        "target_entity_id": target_entity_id,
        "payload_snapshot": payload.payload_snapshot,
        "reason": reason,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }

    try:
        with SessionLocal.begin() as session:
            existing = session.scalar(
                select(AdminApprovalRequest)
                .where(
                    AdminApprovalRequest.requested_by_admin_id == actor.id,
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
                        existing.expires_at.isoformat()
                        if existing.expires_at is not None
                        else None
                    ),
                }
                if current != expected:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="requestId уже использован с другим содержимым заявки.",
                    )
                return {"approval": _serialize(existing), "idempotent": True}

            approval = AdminApprovalRequest(
                id=_new_id("admin-approval"),
                status=PENDING,
                requested_by_admin_id=actor.id,
                required_permission_code=permission_code,
                action_type=action_type,
                target_entity_type=target_entity_type,
                target_entity_id=target_entity_id,
                payload_snapshot=payload.payload_snapshot,
                reason=reason,
                request_ip_address=_client_ip_address(request),
                request_id=request_id,
                expires_at=expires_at,
                execution_result={},
            )
            session.add(approval)
            session.flush()

            serialized = _serialize(approval)
            _audit(
                session,
                actor=actor,
                action="admin_approval_request.created",
                approval=approval,
                before={},
                after=serialized,
                request=request,
            )
            return {"approval": serialized, "idempotent": False}
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Конфликт идемпотентности заявки. Повторите запрос с новым requestId.",
        ) from error

@router.get("")
def list_approvals(
    actor: AdminUser = Depends(get_admin_user),
):
    """Initiators see own requests; super-admins see the complete queue."""
    with SessionLocal.begin() as session:
        now = _now()
        query = select(AdminApprovalRequest).order_by(
            AdminApprovalRequest.created_at.desc()
        )
        if not actor.is_super_admin:
            query = query.where(AdminApprovalRequest.requested_by_admin_id == actor.id)

        approvals = session.scalars(query.with_for_update()).all()
        for approval in approvals:
            _expire_if_needed(session, approval, now)

        return {"approvals": [_serialize(approval) for approval in approvals]}

@router.get("/{approval_id}")
def get_approval(
    approval_id: str,
    actor: AdminUser = Depends(get_admin_user),
):
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

        if not actor.is_super_admin and approval.requested_by_admin_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для просмотра этой заявки.",
            )

        _expire_if_needed(session, approval, _now())
        return {"approval": _serialize(approval)}

@router.post("/{approval_id}/approve")
def approve_approval(
    approval_id: str,
    payload: ReviewApprovalPayload,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    comment = _normalize_optional(payload.comment)

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

        if approval.requested_by_admin_id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Инициатор не может одобрить собственную заявку.",
            )

        if _expire_if_needed(session, approval, _now()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Одобрить можно только заявку в статусе pending.",
            )

        before = _serialize(approval)
        approval.status = APPROVED
        approval.approved_by_admin_id = actor.id
        approval.approved_at = _now()
        approval.approval_comment = comment
        session.flush()

        after = _serialize(approval)
        _audit(
            session,
            actor=actor,
            action="admin_approval_request.approved",
            approval=approval,
            before=before,
            after=after,
            request=request,
        )
        return {"approval": after}

@router.post("/{approval_id}/reject")
def reject_approval(
    approval_id: str,
    payload: ReviewApprovalPayload,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    comment = _normalize_optional(payload.comment)

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

        if approval.requested_by_admin_id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Инициатор не может отклонить собственную заявку.",
            )

        if _expire_if_needed(session, approval, _now()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Отклонить можно только заявку в статусе pending.",
            )

        before = _serialize(approval)
        approval.status = REJECTED
        approval.rejected_by_admin_id = actor.id
        approval.rejected_at = _now()
        approval.rejection_comment = comment
        session.flush()

        after = _serialize(approval)
        _audit(
            session,
            actor=actor,
            action="admin_approval_request.rejected",
            approval=approval,
            before=before,
            after=after,
            request=request,
        )
        return {"approval": after}

@router.post("/{approval_id}/cancel")
def cancel_approval(
    approval_id: str,
    payload: CancelApprovalPayload,
    request: Request,
    actor: AdminUser = Depends(get_admin_user),
):
    """
    Cancel only the caller's own pending request.

    An approved request cannot be cancelled: it must either be executed by its
    dedicated domain executor or become expired. A new desired change requires
    a new immutable request snapshot.
    """
    reason = _normalize_required(payload.reason)

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

        if approval.requested_by_admin_id != actor.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Отменить можно только собственную заявку.",
            )

        if _expire_if_needed(session, approval, _now()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != PENDING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Отменить можно только заявку в статусе pending.",
            )

        before = _serialize(approval)
        approval.status = CANCELLED
        approval.cancelled_by_admin_id = actor.id
        approval.cancelled_at = _now()
        approval.cancellation_reason = reason
        session.flush()

        after = _serialize(approval)
        _audit(
            session,
            actor=actor,
            action="admin_approval_request.cancelled",
            approval=approval,
            before=before,
            after=after,
            request=request,
        )
        return {"approval": after}
