from __future__ import annotations

import hashlib
import os
import secrets
import sys
import termios
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy import delete, select

from app.config import settings
from app.db import SessionLocal
from app.models import AdminAuditLog, AdminSession, AdminUser


ADMIN_SESSION_COOKIE_NAME = "chimera_admin_session"

# Argon2id: password never appears in the database in plaintext.
password_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=2,
)


class AdminAuthError(Exception):
    """Expected authentication/authorization error for admin endpoints."""

    def __init__(self, detail: str, status_code: int = 401) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def normalize_admin_username(value: str) -> str:
    """Return a normalized ASCII admin login or raise a safe validation error."""
    username = value.strip().lower()

    if not 3 <= len(username) <= 64:
        raise AdminAuthError(
            "Логин администратора должен содержать от 3 до 64 символов.",
            status_code=422,
        )

    if not all(
        character.isascii()
        and (character.isalnum() or character in "._-")
        for character in username
    ):
        raise AdminAuthError(
            "Логин может содержать только латинские буквы, цифры, '.', '_' и '-'.",
            status_code=422,
        )

    return username


def validate_new_password(password: str) -> None:
    """Minimal server-side password policy for manually created admin accounts."""
    if len(password) < 12:
        raise AdminAuthError(
            "Пароль администратора должен содержать минимум 12 символов.",
            status_code=422,
        )


def hash_session_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def create_admin_user(
    username: str,
    password: str,
    role: str = "owner",
) -> AdminUser:
    """Create one local admin user. Intended for controlled CLI provisioning."""
    normalized_username = normalize_admin_username(username)
    validate_new_password(password)

    if role not in {"owner", "editor", "viewer"}:
        raise AdminAuthError("Недопустимая роль администратора.", status_code=422)

    with SessionLocal.begin() as session:
        existing = session.scalar(
            select(AdminUser).where(AdminUser.username == normalized_username)
        )
        if existing is not None:
            raise AdminAuthError(
                "Администратор с таким логином уже существует.",
                status_code=409,
            )

        admin = AdminUser(
            id=_new_id("admin"),
            username=normalized_username,
            password_hash=password_hasher.hash(password),
            role=role,
            is_active=True,
        )
        session.add(admin)
        # AdminAuditLog has a foreign key to this new user. Flush the user first,
        # because these models intentionally do not declare ORM relationships.
        session.flush()

        session.add(
            AdminAuditLog(
                id=_new_id("admin-audit"),
                admin_user_id=admin.id,
                action="admin_user.created",
                entity_type="admin_user",
                entity_id=admin.id,
                metadata_json={
                    "username": admin.username,
                    "role": admin.role,
                    "created_via": "cli",
                },
                ip_address=None,
            )
        )
        session.flush()
        return admin


def authenticate_admin(username: str, password: str, ip_address: str | None) -> str:
    """
    Verify password and create an opaque server-side session.

    Return only the raw cookie token. Its SHA-256 hash is stored in PostgreSQL.
    """
    normalized_username = normalize_admin_username(username)

    with SessionLocal.begin() as session:
        admin = session.scalar(
            select(AdminUser).where(AdminUser.username == normalized_username)
        )

        # Return a generic error: never reveal whether a username exists.
        if admin is None or not admin.is_active:
            raise AdminAuthError("Неверный логин или пароль.")

        try:
            password_is_valid = password_hasher.verify(admin.password_hash, password)
        except (InvalidHashError, VerificationError, VerifyMismatchError):
            password_is_valid = False

        if not password_is_valid:
            raise AdminAuthError("Неверный логин или пароль.")

        # Upgrade Argon2 parameters transparently after a successful login.
        if password_hasher.check_needs_rehash(admin.password_hash):
            admin.password_hash = password_hasher.hash(password)

        now = datetime.now(timezone.utc)
        raw_token = secrets.token_urlsafe(32)

        # Clean up expired records opportunistically.
        session.execute(
            delete(AdminSession).where(AdminSession.expires_at <= now)
        )

        admin.last_login_at = now
        admin_session = AdminSession(
            id=_new_id("admin-session"),
            admin_user_id=admin.id,
            token_hash=hash_session_token(raw_token),
            expires_at=now + timedelta(
                seconds=settings.admin_session_lifetime_seconds
            ),
        )
        session.add(admin_session)
        # Flush the session first: audit_log.entity_id refers to this new session
        # and the models intentionally do not define ORM relationships.
        session.flush()
        session.add(
            AdminAuditLog(
                id=_new_id("admin-audit"),
                admin_user_id=admin.id,
                action="admin_auth.login",
                entity_type="admin_session",
                entity_id=admin_session.id,
                metadata_json={"username": admin.username},
                ip_address=ip_address,
            )
        )

        return raw_token


def get_current_admin(raw_token: str) -> AdminUser:
    """Resolve an active administrator from the opaque cookie token."""
    if not raw_token:
        raise AdminAuthError("Требуется вход в админ-панель.")

    token_hash = hash_session_token(raw_token)
    now = datetime.now(timezone.utc)

    with SessionLocal.begin() as session:
        row = session.execute(
            select(AdminSession, AdminUser)
            .join(AdminUser, AdminUser.id == AdminSession.admin_user_id)
            .where(
                AdminSession.token_hash == token_hash,
                AdminSession.expires_at > now,
                AdminUser.is_active.is_(True),
            )
        ).one_or_none()

        if row is None:
            # Safe cleanup if this token belongs to an expired session.
            session.execute(
                delete(AdminSession).where(
                    AdminSession.token_hash == token_hash,
                    AdminSession.expires_at <= now,
                )
            )
            raise AdminAuthError("Сессия админ-панели недействительна или истекла.")

        _, admin = row
        return admin


def revoke_admin_session(raw_token: str, ip_address: str | None) -> None:
    """Delete a server-side admin session during logout."""
    if not raw_token:
        return

    token_hash = hash_session_token(raw_token)

    with SessionLocal.begin() as session:
        admin_session = session.scalar(
            select(AdminSession).where(AdminSession.token_hash == token_hash)
        )

        if admin_session is None:
            return

        session.add(
            AdminAuditLog(
                id=_new_id("admin-audit"),
                admin_user_id=admin_session.admin_user_id,
                action="admin_auth.logout",
                entity_type="admin_session",
                entity_id=admin_session.id,
                metadata_json={},
                ip_address=ip_address,
            )
        )
        session.delete(admin_session)


def _create_admin_from_cli() -> None:
    """Interactive command: python -m app.admin_auth create-admin <username>."""
    if len(sys.argv) != 3 or sys.argv[1] != "create-admin":
        raise SystemExit(
            "Использование: python -m app.admin_auth create-admin <username>"
        )

    import getpass

    username = sys.argv[2]
    password = getpass.getpass(
        "Введите пароль администратора (минимум 12 символов): "
    )
    password_confirmation = getpass.getpass("Повторите пароль: ")

    if password != password_confirmation:
        raise SystemExit("Пароли не совпадают. Администратор не создан.")

    try:
        admin = create_admin_user(username=username, password=password, role="owner")
    except AdminAuthError as error:
        raise SystemExit(error.detail) from error

    print(f"Администратор '{admin.username}' создан с ролью '{admin.role}'.")


if __name__ == "__main__":
    _create_admin_from_cli()
