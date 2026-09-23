from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.admin_access import (
    DIRECT_EXECUTION_MODE,
    VALID_EXECUTION_MODES,
    require_super_admin,
)
from app.admin_auth import (
    AdminAuthError,
    normalize_admin_username,
    password_hasher,
    validate_new_password,
)
from app.db import SessionLocal
from app.models import (
    AdminAuditLog,
    AdminPermission,
    AdminSession,
    AdminUser,
    AdminUserPermission,
)


router = APIRouter(prefix="/api/v1/admin/admins", tags=["admin-management"])


class AdminCreatePayload(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12, max_length=1024)


class PermissionGrantPayload(BaseModel):
    permission_code: str = Field(min_length=3, max_length=128)
    execution_mode: str = Field(default=DIRECT_EXECUTION_MODE, max_length=64)
    reason: str | None = Field(default=None, max_length=4_000)


class DeactivateAdminPayload(BaseModel):
    reason: str = Field(min_length=3, max_length=4_000)


class ReactivateAdminPayload(BaseModel):
    reason: str | None = Field(default=None, max_length=4_000)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _client_ip_address(request: Request) -> str | None:
    """Use the direct peer address; do not trust arbitrary forwarded headers."""
    return request.client.host if request.client else None


def _normalize_optional_reason(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _serialize_permission(
    permission: AdminUserPermission,
) -> dict[str, Any]:
    return {
        "permissionCode": permission.permission_code,
        "executionMode": permission.execution_mode,
        "isActive": permission.is_active,
        "grantedByAdminId": permission.granted_by_admin_id,
        "grantedAt": (
            permission.granted_at.isoformat()
            if permission.granted_at is not None
            else None
        ),
        "revokedByAdminId": permission.revoked_by_admin_id,
        "revokedAt": (
            permission.revoked_at.isoformat()
            if permission.revoked_at is not None
            else None
        ),
        "reason": permission.reason,
    }


def _serialize_admin(
    session: Session,
    admin: AdminUser,
) -> dict[str, Any]:
    grants = session.scalars(
        select(AdminUserPermission)
        .where(AdminUserPermission.admin_user_id == admin.id)
        .order_by(AdminUserPermission.permission_code)
    ).all()

    return {
        "id": admin.id,
        "username": admin.username,
        # role remains in the response solely for legacy compatibility visibility.
        "role": admin.role,
        "isSuperAdmin": admin.is_super_admin,
        "isActive": admin.is_active,
        "isDeleted": admin.is_deleted,
        "createdByAdminId": admin.created_by_admin_id,
        "createdAt": admin.created_at.isoformat() if admin.created_at else None,
        "updatedAt": admin.updated_at.isoformat() if admin.updated_at else None,
        "lastLoginAt": admin.last_login_at.isoformat() if admin.last_login_at else None,
        "deactivatedAt": (
            admin.deactivated_at.isoformat()
            if admin.deactivated_at is not None
            else None
        ),
        "deactivationReason": admin.deactivation_reason,
        "permissions": [_serialize_permission(grant) for grant in grants],
    }


def _audit(
    session: Session,
    *,
    actor: AdminUser,
    action: str,
    entity_type: str,
    entity_id: str | None,
    permission_code: str | None,
    reason: str | None,
    before: dict[str, Any],
    after: dict[str, Any],
    metadata: dict[str, Any],
    ip_address: str | None,
) -> None:
    session.add(
        AdminAuditLog(
            id=_new_id("admin-audit"),
            admin_user_id=actor.id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            permission_code=permission_code,
            reason=reason,
            before_json=before,
            after_json=after,
            outcome="success",
            metadata_json=metadata,
            ip_address=ip_address,
        )
    )


def _active_super_admin_count(session: Session) -> int:
    return int(
        session.scalar(
            select(func.count(AdminUser.id)).where(
                AdminUser.is_super_admin.is_(True),
                AdminUser.is_active.is_(True),
                AdminUser.is_deleted.is_(False),
            )
        )
        or 0
    )


@router.get("")
def list_admins(
    _actor: AdminUser = Depends(require_super_admin),
):
    """Return all administrator accounts, including inactive and deleted records."""
    with SessionLocal() as session:
        admins = session.scalars(
            select(AdminUser).order_by(AdminUser.username)
        ).all()
        return {"admins": [_serialize_admin(session, admin) for admin in admins]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin(
    payload: AdminCreatePayload,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    """
    Create a normal administrator.

    This endpoint intentionally cannot create a super-admin. Elevated access
    must remain under separate, explicitly reviewed operational control.
    """
    try:
        username = normalize_admin_username(payload.username)
        validate_new_password(payload.password)
    except AdminAuthError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    with SessionLocal.begin() as session:
        existing = session.scalar(
            select(AdminUser.id).where(AdminUser.username == username)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Администратор с таким логином уже существует.",
            )

        admin = AdminUser(
            id=_new_id("admin"),
            username=username,
            password_hash=password_hasher.hash(payload.password),
            # Legacy field: new authorization is permission-based.
            role="admin",
            is_super_admin=False,
            is_active=True,
            is_deleted=False,
            created_by_admin_id=actor.id,
        )
        session.add(admin)
        session.flush()

        _audit(
            session,
            actor=actor,
            action="admin_user.created",
            entity_type="admin_user",
            entity_id=admin.id,
            permission_code="admins.manage",
            reason=None,
            before={},
            after={
                "username": admin.username,
                "role": admin.role,
                "isSuperAdmin": False,
                "isActive": True,
            },
            metadata={"createdVia": "admin_api"},
            ip_address=_client_ip_address(request),
        )

        return {"admin": _serialize_admin(session, admin)}


@router.post("/{admin_id}/permissions")
def grant_or_update_permission(
    admin_id: str,
    payload: PermissionGrantPayload,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    """Grant or reactivate one individual permission for a normal admin."""
    permission_code = payload.permission_code.strip()
    execution_mode = payload.execution_mode.strip()
    reason = _normalize_optional_reason(payload.reason)

    if execution_mode not in VALID_EXECUTION_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Недопустимый executionMode. Допустимы: "
                + ", ".join(sorted(VALID_EXECUTION_MODES))
                + "."
            ),
        )

    with SessionLocal.begin() as session:
        target = session.get(AdminUser, admin_id)
        if target is None or target.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Администратор не найден.",
            )

        if target.is_super_admin:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Индивидуальные permissions не назначаются супер-администратору: "
                    "он уже имеет полный прямой доступ."
                ),
            )

        permission = session.scalar(
            select(AdminPermission).where(
                AdminPermission.code == permission_code,
                AdminPermission.is_active.is_(True),
            )
        )
        if permission is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Permission не существует или отключён.",
            )

        grant = session.scalar(
            select(AdminUserPermission).where(
                AdminUserPermission.admin_user_id == target.id,
                AdminUserPermission.permission_code == permission_code,
            )
        )

        before = _serialize_permission(grant) if grant is not None else {}

        if grant is None:
            grant = AdminUserPermission(
                id=_new_id("admin-permission"),
                admin_user_id=target.id,
                permission_code=permission_code,
                execution_mode=execution_mode,
                is_active=True,
                granted_by_admin_id=actor.id,
                reason=reason,
            )
            session.add(grant)
            action = "admin_permission.granted"
        else:
            grant.execution_mode = execution_mode
            grant.is_active = True
            grant.granted_by_admin_id = actor.id
            grant.granted_at = datetime.now(timezone.utc)
            grant.revoked_by_admin_id = None
            grant.revoked_at = None
            grant.reason = reason
            action = "admin_permission.updated"

        session.flush()

        _audit(
            session,
            actor=actor,
            action=action,
            entity_type="admin_user_permission",
            entity_id=grant.id,
            permission_code=permission_code,
            reason=reason,
            before=before,
            after=_serialize_permission(grant),
            metadata={"targetAdminId": target.id},
            ip_address=_client_ip_address(request),
        )

        return {"admin": _serialize_admin(session, target)}


@router.delete("/{admin_id}/permissions/{permission_code}")
def revoke_permission(
    admin_id: str,
    permission_code: str,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    """Soft-revoke an individual permission while retaining an audit trail."""
    with SessionLocal.begin() as session:
        target = session.get(AdminUser, admin_id)
        if target is None or target.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Администратор не найден.",
            )

        if target.is_super_admin:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Индивидуальные permissions супер-администратора не изменяются.",
            )

        grant = session.scalar(
            select(AdminUserPermission).where(
                AdminUserPermission.admin_user_id == target.id,
                AdminUserPermission.permission_code == permission_code,
            )
        )
        if grant is None or not grant.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Активный permission администратора не найден.",
            )

        before = _serialize_permission(grant)
        grant.is_active = False
        grant.revoked_by_admin_id = actor.id
        grant.revoked_at = datetime.now(timezone.utc)
        session.flush()

        _audit(
            session,
            actor=actor,
            action="admin_permission.revoked",
            entity_type="admin_user_permission",
            entity_id=grant.id,
            permission_code=grant.permission_code,
            reason=None,
            before=before,
            after=_serialize_permission(grant),
            metadata={"targetAdminId": target.id},
            ip_address=_client_ip_address(request),
        )

        return {"admin": _serialize_admin(session, target)}


@router.post("/{admin_id}/deactivate")
def deactivate_admin(
    admin_id: str,
    payload: DeactivateAdminPayload,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    """Deactivate an admin and revoke all of their server-side sessions."""
    reason = payload.reason.strip()

    if actor.id == admin_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нельзя деактивировать собственную учётную запись.",
        )

    with SessionLocal.begin() as session:
        target = session.scalar(
            select(AdminUser)
            .where(AdminUser.id == admin_id)
            .with_for_update()
        )
        if target is None or target.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Администратор не найден.",
            )

        if not target.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Администратор уже деактивирован.",
            )

        if target.is_super_admin and _active_super_admin_count(session) <= 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Нельзя деактивировать последнего активного супер-администратора.",
            )

        before = {
            "isActive": target.is_active,
            "deactivatedAt": None,
            "deactivationReason": None,
        }
        target.is_active = False
        target.deactivated_at = datetime.now(timezone.utc)
        target.deactivation_reason = reason

        revoked_session_count = session.execute(
            delete(AdminSession).where(AdminSession.admin_user_id == target.id)
        ).rowcount or 0

        session.flush()

        _audit(
            session,
            actor=actor,
            action="admin_user.deactivated",
            entity_type="admin_user",
            entity_id=target.id,
            permission_code="admins.manage",
            reason=reason,
            before=before,
            after={
                "isActive": target.is_active,
                "deactivatedAt": target.deactivated_at.isoformat(),
                "deactivationReason": target.deactivation_reason,
            },
            metadata={"revokedSessionCount": revoked_session_count},
            ip_address=_client_ip_address(request),
        )

        return {"admin": _serialize_admin(session, target)}


@router.post("/{admin_id}/reactivate")
def reactivate_admin(
    admin_id: str,
    payload: ReactivateAdminPayload,
    request: Request,
    actor: AdminUser = Depends(require_super_admin),
):
    """Reactivate a previously deactivated, non-deleted normal admin account."""
    reason = _normalize_optional_reason(payload.reason)

    with SessionLocal.begin() as session:
        target = session.get(AdminUser, admin_id)
        if target is None or target.is_deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Администратор не найден.",
            )

        if target.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Администратор уже активен.",
            )

        before = {
            "isActive": target.is_active,
            "deactivatedAt": (
                target.deactivated_at.isoformat()
                if target.deactivated_at is not None
                else None
            ),
            "deactivationReason": target.deactivation_reason,
        }
        target.is_active = True
        target.deactivated_at = None
        target.deactivation_reason = None
        session.flush()

        _audit(
            session,
            actor=actor,
            action="admin_user.reactivated",
            entity_type="admin_user",
            entity_id=target.id,
            permission_code="admins.manage",
            reason=reason,
            before=before,
            after={
                "isActive": target.is_active,
                "deactivatedAt": None,
                "deactivationReason": None,
            },
            metadata={},
            ip_address=_client_ip_address(request),
        )

        return {"admin": _serialize_admin(session, target)}
