from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from app.admin_access import require_permission
from app.db import SessionLocal
from app.models import AdminAuditLog, AdminUser, SystemSetting
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
    session.add(
        AdminAuditLog(
            id=_new_id("admin-audit"),
            admin_user_id=actor.id,
            action="system_setting.updated",
            entity_type="system_setting",
            entity_id=setting.key,
            permission_code=SYSTEM_SETTINGS_MANAGE_PERMISSION,
            reason=reason,
            before_json=before,
            after_json=after,
            outcome="success",
            metadata_json={
                "key": setting.key,
                "valueType": setting.value_type,
                "category": setting.category,
                "isSensitive": setting.is_sensitive,
            },
            ip_address=_client_ip_address(request),
        )
    )


def _require_catalog_key(key: str) -> None:
    if get_definition(key) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Системная настройка не найдена в утверждённом каталоге.",
        )


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
    """
    definition = get_definition(key)
    if definition is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Системная настройка не найдена в утверждённом каталоге.",
        )

    if definition.is_sensitive:
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
