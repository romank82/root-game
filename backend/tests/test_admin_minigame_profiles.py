"""Admin Minigame Profiles — CRUD, уникальность, статусные переходы (Sprint 8.17).

Live SQLite + alembic upgrade head (паттерн test_admin_system_settings.py):
disposable БД со схемой из миграций (включая таблицу minigame_profiles,
FK в missions и admin permissions). Endpoint-функции вызываются напрямую с
реальными AdminUser из БД и замоканным SessionLocal модуля.
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
from app.admin_minigame_profiles import (
    MINIGAME_PROFILES_MANAGE_PERMISSION,
    MINIGAME_PROFILES_READ_PERMISSION,
    AdminMinigameProfileCreatePayload,
    AdminMinigameProfileUpdatePayload,
    archive_admin_minigame_profile,
    create_admin_minigame_profile,
    get_admin_minigame_profile,
    list_admin_minigame_profiles,
    publish_admin_minigame_profile,
    update_admin_minigame_profile,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AdminMinigameProfilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-minigame-profiles-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "admin.sqlite3"
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

        from app import admin_minigame_profiles

        cls.admin_minigame_profiles = admin_minigame_profiles
        cls._session_local_patch = patch.object(
            admin_minigame_profiles, "SessionLocal", cls.SessionLocal
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------------

    def _request(self) -> SimpleNamespace:
        return SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.9"),
            headers={},
            state=SimpleNamespace(),
        )

    def _make_admin(self):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                    is_deleted=False,
                )
            )
        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _grant(self, admin_id: str, permission_code: str) -> None:
        from app.models import AdminUserPermission

        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode=DIRECT_EXECUTION_MODE,
                    is_active=True,
                )
            )

    def _create(
        self,
        admin,
        *,
        name: str | None = None,
        game_type: str = "cipher",
        settings: dict | None = None,
    ):
        payload = AdminMinigameProfileCreatePayload(
            name=name or f"profile-{uuid.uuid4().hex[:8]}",
            game_type=game_type,
            settings=settings
            if settings is not None
            else {"drumCount": 3, "falseChoicesPerDrum": 4},
        )
        return create_admin_minigame_profile(
            payload=payload,
            request=self._request(),
            admin=admin,
        )["minigameProfile"]

    def _load_profile(self, profile_id: str):
        from app.models import MinigameProfile

        with self.SessionLocal() as session:
            return session.get(MinigameProfile, profile_id)

    def _count_audit(self, action: str, admin_id: str) -> int:
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return len(
                session.scalars(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == action,
                        AdminAuditLog.entity_type == "minigame_profile",
                        AdminAuditLog.admin_user_id == admin_id,
                    )
                ).all()
            )

    # ---- Тесты --------------------------------------------------------------

    def test_create_minigame_profile(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="Create-Profile")

        self.assertTrue(created["id"].startswith("minigame-profile-"))
        self.assertEqual(created["name"], "Create-Profile")
        self.assertEqual(created["gameType"], "cipher")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["settings"], {"drumCount": 3, "falseChoicesPerDrum": 4})

        stored = self._load_profile(created["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, "draft")
        self.assertEqual(
            self._count_audit("minigame_profile.created", admin.id), 1
        )

    def test_create_trims_name(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="  Trimmed  Profile  ")
        self.assertEqual(created["name"], "Trimmed  Profile")

    def test_create_duplicate_name_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        self._create(admin, name="Duplicate")

        with self.assertRaises(HTTPException) as caught:
            self._create(admin, name="Duplicate")
        self.assertEqual(caught.exception.status_code, 409)

    def test_create_invalid_game_type_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            self._create(admin, game_type="wormhole")
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("game_type", caught.exception.detail)

    def test_create_cipher_rejects_alphabet_combination_422(self) -> None:
        """Sprint 8.17.5: alphabet/combination нельзя сохранить в профиле.

        Их генерирует backend на каждую попытку.
        """
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin,
                name="Bad-Cipher",
                game_type="cipher",
                settings={
                    "drumCount": 3,
                    "alphabet": ["A", "B", "C"],
                    "combination": "ABC",
                },
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("alphabet", caught.exception.detail)
        self.assertIn("combination", caught.exception.detail)

    def test_create_cipher_invalid_drum_count_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin, name="Bad-Drums", game_type="cipher", settings={"drumCount": 1}
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("drumCount", caught.exception.detail)

    def test_create_blank_name_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            self._create(admin, name="   ")
        self.assertEqual(caught.exception.status_code, 422)

    def test_list_profiles_ordered_by_name(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_READ_PERMISSION)
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        self._create(admin, name="bravo")
        self._create(admin, name="alpha")
        self._create(admin, name="charlie")

        result = list_admin_minigame_profiles(_admin=admin)
        names = [p["name"] for p in result["minigameProfiles"]]
        self.assertEqual(names, sorted(names))
        self.assertIn("alpha", names)
        self.assertIn("charlie", names)

    def test_get_profile(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_READ_PERMISSION)
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="Get-Me")

        got = get_admin_minigame_profile(profile_id=created["id"], _admin=admin)
        self.assertEqual(got["minigameProfile"]["id"], created["id"])
        self.assertEqual(got["minigameProfile"]["name"], "Get-Me")

    def test_get_profile_404(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_READ_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            get_admin_minigame_profile(
                profile_id="minigame-profile-missing", _admin=admin
            )
        self.assertEqual(caught.exception.status_code, 404)

    def test_update_profile(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="Before", game_type="cipher")

        updated = update_admin_minigame_profile(
            profile_id=created["id"],
            payload=AdminMinigameProfileUpdatePayload(
                name="After",
                game_type="code_repair",
                settings={"maxBlocks": 8},
            ),
            request=self._request(),
            admin=admin,
        )["minigameProfile"]

        self.assertEqual(updated["name"], "After")
        self.assertEqual(updated["gameType"], "code_repair")
        self.assertEqual(updated["settings"], {"maxBlocks": 8})
        self.assertEqual(
            self._count_audit("minigame_profile.updated", admin.id), 1
        )

    def test_update_duplicate_name_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        first = self._create(admin, name="First")
        second = self._create(admin, name="Second")

        with self.assertRaises(HTTPException) as caught:
            update_admin_minigame_profile(
                profile_id=second["id"],
                payload=AdminMinigameProfileUpdatePayload(name="First"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._load_profile(first["id"]).name, "First")

    def test_update_invalid_game_type_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin)

        with self.assertRaises(HTTPException) as caught:
            update_admin_minigame_profile(
                profile_id=created["id"],
                payload=AdminMinigameProfileUpdatePayload(game_type="bogus"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_publish_draft(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="Publish-Me")

        published = publish_admin_minigame_profile(
            profile_id=created["id"],
            request=self._request(),
            admin=admin,
        )["minigameProfile"]

        self.assertEqual(published["status"], "published")
        self.assertEqual(self._load_profile(created["id"]).status, "published")
        self.assertEqual(
            self._count_audit("minigame_profile.published", admin.id), 1
        )

    def test_update_status_published(self) -> None:
        """Обновление полей опубликованного профиля разрешено."""
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="Published-Then-Edit")
        publish_admin_minigame_profile(
            profile_id=created["id"], request=self._request(), admin=admin
        )

        updated = update_admin_minigame_profile(
            profile_id=created["id"],
            payload=AdminMinigameProfileUpdatePayload(
                settings={"drumCount": 5, "falseChoicesPerDrum": 6}
            ),
            request=self._request(),
            admin=admin,
        )["minigameProfile"]

        self.assertEqual(updated["status"], "published")
        self.assertEqual(updated["settings"], {"drumCount": 5, "falseChoicesPerDrum": 6})

    def test_archive_published(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="Archive-Me")
        publish_admin_minigame_profile(
            profile_id=created["id"], request=self._request(), admin=admin
        )

        archived = archive_admin_minigame_profile(
            profile_id=created["id"],
            request=self._request(),
            admin=admin,
        )["minigameProfile"]

        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self._load_profile(created["id"]).status, "archived")
        self.assertEqual(
            self._count_audit("minigame_profile.archived", admin.id), 1
        )

    def test_publish_without_settings_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(
            admin, name="Empty-Settings", game_type="text_answer", settings={}
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_minigame_profile(
                profile_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("settings", caught.exception.detail)

    def test_publish_already_published_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, MINIGAME_PROFILES_MANAGE_PERMISSION)

        created = self._create(admin, name="Double-Publish")
        publish_admin_minigame_profile(
            profile_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_minigame_profile(
                profile_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()


