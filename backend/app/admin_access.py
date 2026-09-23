from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select

from app.admin_auth import (
    ADMIN_SESSION_COOKIE_NAME,
    AdminAuthError,
    get_current_admin,
)
from app.db import SessionLocal
from app.models import AdminPermission, AdminUser, AdminUserPermission


DIRECT_EXECUTION_MODE = "direct"
APPROVAL_EXECUTION_MODE = "requires_super_admin_approval"
VALID_EXECUTION_MODES = {
    DIRECT_EXECUTION_MODE,
    APPROVAL_EXECUTION_MODE,
}


def get_admin_user(request: Request) -> AdminUser:
    """FastAPI dependency resolving the active admin from the HttpOnly cookie."""
    try:
        return get_current_admin(
            request.cookies.get(ADMIN_SESSION_COOKIE_NAME, "")
        )
    except AdminAuthError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


def require_super_admin(
    admin: AdminUser = Depends(get_admin_user),
) -> AdminUser:
    """Allow only an active, non-deleted super-admin."""
    if not admin.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Для этого действия требуются права супер-администратора.",
        )
    return admin


def get_permission_execution_mode(
    admin: AdminUser,
    permission_code: str,
) -> str | None:
    """
    Return the effective execution mode for an active permission.

    Super-admins have every permission directly. For normal admins, both the
    permission catalog entry and their personal grant must be active.
    """
    if admin.is_super_admin:
        return DIRECT_EXECUTION_MODE

    with SessionLocal() as session:
        permission_is_active = session.scalar(
            select(AdminPermission.code).where(
                AdminPermission.code == permission_code,
                AdminPermission.is_active.is_(True),
            )
        )
        if permission_is_active is None:
            return None

        return session.scalar(
            select(AdminUserPermission.execution_mode).where(
                AdminUserPermission.admin_user_id == admin.id,
                AdminUserPermission.permission_code == permission_code,
                AdminUserPermission.is_active.is_(True),
            )
        )


def require_permission(permission_code: str) -> Callable[[AdminUser], AdminUser]:
    """
    Create a dependency for actions which may be performed directly.

    Approval-mode grants are intentionally not treated as direct authority.
    The approval-request workflow will consume those grants in a later module.
    """
    def dependency(
        admin: AdminUser = Depends(get_admin_user),
    ) -> AdminUser:
        execution_mode = get_permission_execution_mode(admin, permission_code)

        if execution_mode is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        if execution_mode != DIRECT_EXECUTION_MODE:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "Для этого действия требуется одобрение супер-администратора. "
                    "Модуль заявок будет подключён отдельно."
                ),
            )

        return admin

    return dependency
