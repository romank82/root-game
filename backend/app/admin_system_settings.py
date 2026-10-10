from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.admin_access import (
    APPROVAL_EXECUTION_MODE,
    get_admin_user,
    get_permission_execution_mode,
    require_permission,
    require_super_admin,
)
from app.admin_approvals import (
    APPROVED,
    EXECUTED,
    EXECUTION_FAILED,
    EXPIRED,
    PENDING,
    _serialize as _serialize_approval,
)
from app.admin_audit import (
    build_admin_approval_audit_snapshot,
    write_admin_audit,
)
from app.datetime_utils import ensure_utc
from app.db import SessionLocal
from app.models import (
    AdminApprovalRequest,
    AdminAuditLog,
    AdminUser,
    SystemSetting,
)
from app.system_settings_catalog import (
    SYSTEM_SETTING_CATALOG,
    get_definition,
    validate_catalog_values,
)

router = APIRouter(
    prefix="/api/v1/admin/system-settings",
    tags=["admin-system-settings"],
)

SYSTEM_SETTINGS_READ_PERMISSION = "system_settings.read"
SYSTEM_SETTINGS_MANAGE_PERMISSION = "system_settings.manage"
ACTIVE = "active"


class UpdateSystemSettingPayload(BaseModel):
    value: Any
    reason: str | None = None


class CreateSensitiveSettingApprovalPayload(BaseModel):
    value: Any
    reason: str
    request_id: str
    expires_at: datetime


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _client_ip_address(request: Request) -> str | None:
    """Use direct peer address only; forwarded headers are not trusted."""
    return request.client.host if request.client else None


def _normalize_reason(reason: str | None) -> str | None:
    if reason is None:
        return None
    normalized = reason.strip()
    if not normalized:
        return None
    if len(normalized) > 4_000:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="reason не может превышать 4000 символов.",
        )
    return normalized


def _serialize(setting: SystemSetting) -> dict[str, Any]:
    return {
        "key": setting.key,
        "value": setting.value_json,
        "valueType": setting.value_type,
        "category": setting.category,
        "title": setting.title,
        "description": setting.description,
        "isSensitive": setting.is_sensitive,
        "status": setting.status,
        "createdByAdminId": setting.created_by_admin_id,
        "updatedByAdminId": setting.updated_by_admin_id,
        "createdAt": setting.created_at.isoformat() if setting.created_at else None,
        "updatedAt": setting.updated_at.isoformat() if setting.updated_at else None,
    }


def _audit_update(
    *,
    session: Any,
    actor: AdminUser,
    setting: SystemSetting,
    before: dict[str, Any],
    after: dict[str, Any],
    reason: str | None,
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=actor,
        action="system_setting.updated",
        entity_type="system_setting",
        entity_id=setting.key,
        request=request,
        permission_code=SYSTEM_SETTINGS_MANAGE_PERMISSION,
        before=before,
        after=after,
        metadata={
            "key": setting.key,
            "valueType": setting.value_type,
            "category": setting.category,
            "isSensitive": setting.is_sensitive,
            "reasonProvided": bool(reason),
        },
    )


def _require_catalog_key(key: str) -> None:
    if get_definition(key) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Системная настройка не найдена в утверждённом каталоге.",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        metadata=metadata or {
            "actionType": approval.action_type,
            "targetEntityType": approval.target_entity_type,
            "targetEntityId": approval.target_entity_id,
        },
    )


def _audit_approval_setting_update(
    *,
    session: Any,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    setting: SystemSetting,
    before: dict[str, Any],
    after: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=actor,
        action="system_setting.updated_via_approval",
        entity_type="system_setting",
        entity_id=setting.key,
        request=request,
        permission_code=SYSTEM_SETTINGS_MANAGE_PERMISSION,
        approval_request_id=approval.id,
        request_id=approval.request_id,
        before=before,
        after=after,
        metadata={
            "key": setting.key,
            "valueType": setting.value_type,
            "category": setting.category,
            "isSensitive": setting.is_sensitive,
            "actionType": approval.action_type,
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
    """Persist a final, sanitized execution failure in the current transaction."""
    before = _serialize_approval(approval)
    approval.status = EXECUTION_FAILED
    approval.executed_by_admin_id = actor.id
    approval.executed_at = _now()
    approval.execution_result = {
        "status": "failed",
        "errorCode": error_code,
    }
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


@router.get("")
def list_system_settings(
    _actor: AdminUser = Depends(require_permission(SYSTEM_SETTINGS_READ_PERMISSION)),
):
    with SessionLocal() as session:
        settings = session.scalars(
            select(SystemSetting).order_by(SystemSetting.category, SystemSetting.key)
        ).all()
        return {"settings": [_serialize(setting) for setting in settings]}


@router.get("/{key}")
def get_system_setting(
    key: str,
    _actor: AdminUser = Depends(require_permission(SYSTEM_SETTINGS_READ_PERMISSION)),
):
    _require_catalog_key(key)

    with SessionLocal() as session:
        setting = session.get(SystemSetting, key)
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Системная настройка отсутствует в базе данных.",
            )
        return {"setting": _serialize(setting)}


@router.put("/{key}")
def update_non_sensitive_system_setting(
    key: str,
    payload: UpdateSystemSettingPayload,
    request: Request,
    actor: AdminUser = Depends(
        require_permission(SYSTEM_SETTINGS_MANAGE_PERMISSION)
    ),
):
    """
    Update only an active, non-sensitive catalog setting.

    Sensitive changes intentionally use a dedicated approval-backed executor,
    implemented separately. This endpoint never creates or executes approvals.
    Sensitive settings: super-admin updates directly (with audit);
    other admins must use the approval workflow.
    """
    definition = get_definition(key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Системная настройка не найдена в утверждённом каталоге.",
        )

    if definition.is_sensitive and not actor.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Чувствительная настройка не может быть изменена напрямую. "
                "Используйте approval workflow."
            ),
        )

    reason = _normalize_reason(payload.reason)

    with SessionLocal.begin() as session:
        setting = session.scalar(
            select(SystemSetting)
            .where(SystemSetting.key == key)
            .with_for_update()
        )
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Системная настройка отсутствует в базе данных.",
            )

        if setting.status != ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Можно изменять только active системную настройку.",
            )

        # DB metadata must remain consistent with the approved code catalog.
        if (
            setting.value_type != definition.value_type
            or setting.is_sensitive != definition.is_sensitive
            or setting.category != definition.category
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Метаданные настройки не соответствуют утверждённому каталогу.",
            )

        active_settings = session.scalars(
            select(SystemSetting)
            .where(SystemSetting.status == ACTIVE)
            .with_for_update()
        ).all()
        effective_values = {
            current.key: current.value_json for current in active_settings
        }
        effective_values[key] = payload.value

        try:
            validate_catalog_values(effective_values)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

        before = _serialize(setting)
        setting.value_json = payload.value
        setting.updated_by_admin_id = actor.id
        session.flush()

        after = _serialize(setting)
        _audit_update(
            session=session,
            actor=actor,
            setting=setting,
            before=before,
            after=after,
            reason=reason,
            request=request,
        )

        return {"setting": after}

@router.post("/{key}/approval-requests", status_code=status.HTTP_201_CREATED)
def create_sensitive_setting_approval_request(
    key: str,
    payload: CreateSensitiveSettingApprovalPayload,
    request: Request,
    actor: AdminUser = Depends(get_admin_user),
):
    """
    Create an immutable, catalog-validated request for a sensitive setting.

    The generic approval endpoint deliberately rejects this action type, so an
    arbitrary payload cannot bypass setting type, sensitivity or schema checks.
    """
    definition = get_definition(key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Системная настройка не найдена в утверждённом каталоге.",
        )
    if not definition.is_sensitive:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Approval workflow предназначен только для sensitive settings.",
        )
    if actor.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Super-admin не создаёт sensitive-setting заявку; "
                "изменение требует инициатора с approval-mode permission."
            ),
        )

    execution_mode = get_permission_execution_mode(
        actor,
        SYSTEM_SETTINGS_MANAGE_PERMISSION,
    )
    if execution_mode != APPROVAL_EXECUTION_MODE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Для создания sensitive-setting заявки требуется активный "
                "system_settings.manage в режиме requires_super_admin_approval."
            ),
        )

    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")
    expires_at = _validate_expiry(payload.expires_at)

    with SessionLocal.begin() as session:
        setting = session.scalar(
            select(SystemSetting)
            .where(SystemSetting.key == key)
            .with_for_update()
        )
        if setting is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Системная настройка отсутствует в базе данных.",
            )
        if setting.status != ACTIVE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Создать заявку можно только для active настройки.",
            )
        if (
            setting.value_type != definition.value_type
            or setting.category != definition.category
            or setting.is_sensitive is not True
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Метаданные настройки не соответствуют утверждённому каталогу.",
            )

        active_settings = session.scalars(
            select(SystemSetting)
            .where(SystemSetting.status == ACTIVE)
            .order_by(SystemSetting.key)
            .with_for_update()
        ).all()
        effective_values = {
            current.key: current.value_json
            for current in active_settings
        }
        effective_values[key] = payload.value

        try:
            validate_catalog_values(effective_values)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error

        snapshot = {
            "settingKey": key,
            "proposedValue": payload.value,
            "valueType": definition.value_type,
        }
        expected = {
            "required_permission_code": SYSTEM_SETTINGS_MANAGE_PERMISSION,
            "action_type": "system_setting.change",
            "target_entity_type": "system_setting",
            "target_entity_id": key,
            "payload_snapshot": snapshot,
            "reason": reason,
            "expires_at": expires_at.isoformat(),
        }

        try:
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
                return {
                    "approval": _serialize_approval(existing),
                    "idempotent": True,
                }

            approval = AdminApprovalRequest(
                id=_new_id("admin-approval"),
                status=PENDING,
                requested_by_admin_id=actor.id,
                required_permission_code=SYSTEM_SETTINGS_MANAGE_PERMISSION,
                action_type="system_setting.change",
                target_entity_type="system_setting",
                target_entity_id=key,
                payload_snapshot=snapshot,
                reason=reason,
                request_ip_address=_client_ip_address(request),
                request_id=request_id,
                expires_at=expires_at,
                execution_result={},
            )
            session.add(approval)
            session.flush()

            serialized = _serialize_approval(approval)
            _audit_approval(
                session=session,
                actor=actor,
                approval=approval,
                action="admin_approval_request.created",
                before={},
                after=serialized,
                outcome="success",
                request=request,
            )
            return {"approval": serialized, "idempotent": False}
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности заявки. Используйте новый requestId.",
            ) from error


@router.post("/approval-requests/{approval_id}/execute")
def execute_sensitive_setting_approval(
    approval_id: str,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    """
    Dedicated domain executor for system_setting.change only.

    There is intentionally no generic approval execute endpoint. A validation
    or catalog conflict consumes the already-approved immutable request into
    execution_failed; retrying requires a new request and approval.
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

        if approval.action_type != "system_setting.change":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Этот executor принимает только system_setting.change.",
            )

        if approval.status == EXECUTED:
            return {
                "approval": _serialize_approval(approval),
                "idempotent": True,
            }

        if approval.requested_by_admin_id == actor.id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Инициатор не может исполнять собственную заявку.",
            )

        expires_at = ensure_utc(approval.expires_at)
        if approval.status == APPROVED and (
            expires_at is not None and expires_at <= _now()
        ):
            approval.status = EXPIRED
            session.flush()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Исполнить можно только заявку в статусе approved.",
            )

        snapshot = approval.payload_snapshot
        key = snapshot.get("settingKey") if isinstance(snapshot, dict) else None
        proposed_value = (
            snapshot.get("proposedValue")
            if isinstance(snapshot, dict)
            else None
        )
        definition = get_definition(key) if isinstance(key, str) else None

        if (
            definition is None
            or approval.required_permission_code != SYSTEM_SETTINGS_MANAGE_PERMISSION
            or approval.target_entity_type != "system_setting"
            or approval.target_entity_id != key
            or snapshot != {
                "settingKey": key,
                "proposedValue": proposed_value,
                "valueType": definition.value_type if definition else None,
            }
        ):
            failed = _mark_execution_failed(
                session=session,
                actor=actor,
                approval=approval,
                error_code="invalid_approval_snapshot",
                request=request,
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"approval": failed, "idempotent": False},
            )

        active_settings = session.scalars(
            select(SystemSetting)
            .where(SystemSetting.status == ACTIVE)
            .order_by(SystemSetting.key)
            .with_for_update()
        ).all()
        settings_by_key = {setting.key: setting for setting in active_settings}
        setting = settings_by_key.get(key)

        if setting is None:
            failed = _mark_execution_failed(
                session=session,
                actor=actor,
                approval=approval,
                error_code="setting_not_active",
                request=request,
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"approval": failed, "idempotent": False},
            )

        if (
            setting.value_type != definition.value_type
            or setting.category != definition.category
            or setting.is_sensitive is not True
        ):
            failed = _mark_execution_failed(
                session=session,
                actor=actor,
                approval=approval,
                error_code="setting_catalog_metadata_conflict",
                request=request,
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"approval": failed, "idempotent": False},
            )

        effective_values = {
            current.key: current.value_json
            for current in active_settings
        }
        effective_values[key] = proposed_value

        try:
            validate_catalog_values(effective_values)
        except ValueError:
            failed = _mark_execution_failed(
                session=session,
                actor=actor,
                approval=approval,
                error_code="setting_validation_failed",
                request=request,
            )
            return JSONResponse(
                status_code=status.HTTP_409_CONFLICT,
                content={"approval": failed, "idempotent": False},
            )

        before_setting = _serialize(setting)
        setting.value_json = proposed_value
        setting.updated_by_admin_id = actor.id
        session.flush()
        after_setting = _serialize(setting)

        before_approval = _serialize_approval(approval)
        approval.status = EXECUTED
        approval.executed_by_admin_id = actor.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "settingKey": key,
            "settingValue": proposed_value,
        }
        approval.execution_error = None
        session.flush()
        after_approval = _serialize_approval(approval)

        _audit_approval_setting_update(
            session=session,
            actor=actor,
            approval=approval,
            setting=setting,
            before=before_setting,
            after=after_setting,
            request=request,
        )
        _audit_approval(
            session=session,
            actor=actor,
            approval=approval,
            action="admin_approval_request.executed",
            before=before_approval,
            after=after_approval,
            outcome="success",
            request=request,
        )

        return {
            "approval": after_approval,
            "setting": after_setting,
            "idempotent": False,
        }
