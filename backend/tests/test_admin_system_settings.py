"""Admin System Settings — sensitive updates (settings-fix-1a).

Live SQLite + alembic upgrade head (паттерн test_admin_teams.py):
disposable БД, все настройки каталога сиируются миграциями.
Endpoint-функция update_non_sensitive_system_setting вызывается напрямую
с реальными AdminUser из БД и замоканным SessionLocal.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_access import DIRECT_EXECUTION_MODE
from app.admin_system_settings import (
    SYSTEM_SETTINGS_MANAGE_PERMISSION,
    UpdateSystemSettingPayload,
    update_non_sensitive_system_setting,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Чувствительная настройка из foundation-сида (is_sensitive=True, integer).
SENSITIVE_KEY = "economy.daily_transfer_limit"


class AdminSystemSettingsTests(unittest.TestCase):
    """settings-fix-1a: супер-админ меняет sensitive напрямую, обычный — 422."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-system-settings-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "admin-system-settings.sqlite3"
        )
        database_url = f"sqlite:///{cls.database_path}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url

        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND_ROOT / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        cls.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(cls.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        from app import admin_access, admin_system_settings

        cls.admin_system_settings = admin_system_settings
        cls._session_local_patch = patch.object(
            admin_system_settings, "SessionLocal", cls.SessionLocal
        )
        cls._session_local_patch.start()
        cls._access_session_local_patch = patch.object(
            admin_access, "SessionLocal", cls.SessionLocal
        )
        cls._access_session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._access_session_local_patch.stop()
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------------

    def _request(self) -> SimpleNamespace:
        return SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.7"),
            headers={},
            state=SimpleNamespace(),
        )

    def _make_admin(self, *, username: str | None = None, super_admin: bool = False):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=username or f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin" if super_admin else "admin",
                    is_super_admin=super_admin,
                    is_active=True,
                    is_deleted=False,
                )
            )
        return self._load_admin(admin_id)

    def _load_admin(self, admin_id: str):
        from app.models import AdminUser

        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _grant(
        self,
        admin_id: str,
        permission_code: str,
        *,
        execution_mode: str = DIRECT_EXECUTION_MODE,
    ) -> None:
        from app.models import AdminUserPermission

        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode=execution_mode,
                    is_active=True,
                )
            )

    def _get_setting(self, key: str):
        from app.models import SystemSetting

        with self.SessionLocal() as session:
            return session.get(SystemSetting, key)

    def _count_setting_audit(self, key: str, admin_user_id: str) -> int:
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return len(
                session.scalars(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == "system_setting.updated",
                        AdminAuditLog.entity_id == key,
                        AdminAuditLog.admin_user_id == admin_user_id,
                    )
                ).all()
            )

    # ---- Тесты --------------------------------------------------------------

    def test_super_admin_updates_sensitive_setting_directly(self) -> None:
        super_admin = self._make_admin(super_admin=True)

        before = self._get_setting(SENSITIVE_KEY)
        self.assertTrue(before.is_sensitive)
        self.assertNotEqual(before.value_json, 60000)

        result = update_non_sensitive_system_setting(
            key=SENSITIVE_KEY,
            payload=UpdateSystemSettingPayload(
                value=60000,
                reason="прямое изменение супер-админом (тест)",
            ),
            request=self._request(),
            actor=super_admin,
        )

        self.assertEqual(result["setting"]["key"], SENSITIVE_KEY)
        self.assertEqual(result["setting"]["value"], 60000)
        self.assertEqual(result["setting"]["isSensitive"], True)
        self.assertEqual(result["setting"]["updatedByAdminId"], super_admin.id)

        after = self._get_setting(SENSITIVE_KEY)
        self.assertEqual(after.value_json, 60000)
        self.assertEqual(after.updated_by_admin_id, super_admin.id)

        # docstring: "with audit" — изменение супер-админа фиксируется в аудите.
        self.assertEqual(
            self._count_setting_audit(SENSITIVE_KEY, super_admin.id), 1
        )

    def test_non_super_admin_blocked_on_sensitive_setting(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SYSTEM_SETTINGS_MANAGE_PERMISSION)

        before = self._get_setting(SENSITIVE_KEY).value_json

        with self.assertRaises(HTTPException) as caught:
            update_non_sensitive_system_setting(
                key=SENSITIVE_KEY,
                payload=UpdateSystemSettingPayload(
                    value=65_000,
                    reason="попытка обычного админа (тест)",
                ),
                request=self._request(),
                actor=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)

        unchanged = self._get_setting(SENSITIVE_KEY)
        self.assertEqual(unchanged.value_json, before)
        self.assertEqual(
            self._count_setting_audit(SENSITIVE_KEY, admin.id), 0,
        )


if __name__ == "__main__":
    unittest.main()