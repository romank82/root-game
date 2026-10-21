"""Admin Seasons — CRUD, уникальность slug, статусные переходы (Sprint 8.21).

Live SQLite + alembic upgrade head (паттерн test_admin_minigame_profiles.py):
disposable БД со схемой из миграций (включая таблицу seasons и admin
permissions seasons.read/seasons.manage). Endpoint-функции вызываются напрямую
с реальными AdminUser из БД и замоканным SessionLocal модуля.
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
from app.admin_seasons import (
    SEASONS_MANAGE_PERMISSION,
    SEASONS_READ_PERMISSION,
    SeasonCreatePayload,
    SeasonUpdatePayload,
    archive_admin_season,
    create_admin_season,
    get_admin_season,
    list_admin_seasons,
    publish_admin_season,
    update_admin_season,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AdminSeasonsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-seasons-tests-"
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

        from app import admin_seasons

        cls.admin_seasons = admin_seasons
        cls._session_local_patch = patch.object(
            admin_seasons, "SessionLocal", cls.SessionLocal
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

    def _create(self, admin, *, slug=None, title=None, **kwargs):
        payload = SeasonCreatePayload(
            slug=slug,
            title=title or f"Сезон {uuid.uuid4().hex[:6]}",
            **kwargs,
        )
        return create_admin_season(
            payload=payload,
            request=self._request(),
            admin=admin,
        )["season"]

    def _load_season(self, season_id: str):
        from app.models import Season

        with self.SessionLocal() as session:
            return session.get(Season, season_id)

    def _count_audit(self, action: str, admin_id: str) -> int:
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return len(
                session.scalars(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == action,
                        AdminAuditLog.entity_type == "season",
                        AdminAuditLog.admin_user_id == admin_id,
                    )
                ).all()
            )

# ---- Тесты --------------------------------------------------------------

    def test_create_season(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="season-prologue", title="ПРОЛОГ")

        self.assertTrue(created["id"].startswith("season-"))
        self.assertEqual(created["slug"], "season-prologue")
        self.assertEqual(created["title"], "ПРОЛОГ")
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["sortOrder"], 0)

        stored = self._load_season(created["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, "draft")
        self.assertEqual(self._count_audit("season.created", admin.id), 1)

    def test_create_without_slug_generates_from_title(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, title="СЕЗОН: ПРОТОКОЛ 02")

        self.assertEqual(created["slug"], "sezon-protokol-02")

    def test_create_duplicate_slug_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        first = self._create(admin, slug="duplicated", title="Первый")

        with self.assertRaises(HTTPException) as caught:
            self._create(admin, slug="duplicated", title="Второй")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._load_season(first["id"]).slug, "duplicated")

    def test_create_blank_title_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            self._create(admin, slug="blank-title", title="   ")
        self.assertEqual(caught.exception.status_code, 422)

    def test_get_season_and_404(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_READ_PERMISSION)
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="get-me", title="Get-Me")

        got = get_admin_season(season_id=created["id"], _admin=admin)
        self.assertEqual(got["season"]["id"], created["id"])
        self.assertEqual(got["season"]["title"], "Get-Me")

        with self.assertRaises(HTTPException) as caught:
            get_admin_season(season_id="season-missing", _admin=admin)
        self.assertEqual(caught.exception.status_code, 404)

    def test_list_seasons_ordered_and_status_filter(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_READ_PERMISSION)
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        second = self._create(admin, slug="season-b", title="B-сезон", sort_order=2)
        first = self._create(admin, slug="season-a", title="A-сезон", sort_order=1)
        publish_admin_season(
            season_id=first["id"], request=self._request(), admin=admin
        )

        result = list_admin_seasons(_admin=admin)
        slugs = [season["slug"] for season in result["seasons"]]
        self.assertIn("season-a", slugs)
        self.assertIn("season-b", slugs)
        self.assertLess(slugs.index("season-a"), slugs.index("season-b"))

        published = list_admin_seasons(status="published", _admin=admin)
        published_slugs = [season["slug"] for season in published["seasons"]]
        self.assertIn("season-a", published_slugs)
        self.assertNotIn("season-b", published_slugs)

        with self.assertRaises(HTTPException) as caught:
            list_admin_seasons(status="unknown", _admin=admin)
        self.assertEqual(caught.exception.status_code, 422)

    def test_update_season(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(
            admin, slug="before", title="До", description="old"
        )

        updated = update_admin_season(
            season_id=created["id"],
            payload=SeasonUpdatePayload(
                title="После",
                description="new",
                sort_order=5,
            ),
            request=self._request(),
            admin=admin,
        )["season"]

        self.assertEqual(updated["title"], "После")
        self.assertEqual(updated["description"], "new")
        self.assertEqual(updated["sortOrder"], 5)
        self.assertEqual(self._count_audit("season.updated", admin.id), 1)

    def test_update_duplicate_slug_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        first = self._create(admin, slug="first", title="Первый")
        second = self._create(admin, slug="second", title="Второй")

        with self.assertRaises(HTTPException) as caught:
            update_admin_season(
                season_id=second["id"],
                payload=SeasonUpdatePayload(slug="first"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._load_season(first["id"]).slug, "first")

    def test_publish_season(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="publish-me", title="Опубликовать")

        published = publish_admin_season(
            season_id=created["id"],
            request=self._request(),
            admin=admin,
        )["season"]

        self.assertEqual(published["status"], "published")
        self.assertEqual(self._load_season(created["id"]).status, "published")
        self.assertEqual(self._count_audit("season.published", admin.id), 1)

    def test_publish_already_published_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(
            admin, slug="double-publish", title="Двойная публикация"
        )
        publish_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_season(
                season_id=created["id"], request=self._request(), admin=admin
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_archive_published(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="archive-me", title="Архивировать")
        publish_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )

        archived = archive_admin_season(
            season_id=created["id"],
            request=self._request(),
            admin=admin,
        )["season"]

        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self._load_season(created["id"]).status, "archived")
        self.assertEqual(self._count_audit("season.archived", admin.id), 1)

    def test_archive_draft_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="archive-draft", title="Архив черновика")

        with self.assertRaises(HTTPException) as caught:
            archive_admin_season(
                season_id=created["id"], request=self._request(), admin=admin
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_archive_already_archived_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="double-archive", title="Двойная архивация")
        publish_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )
        archive_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            archive_admin_season(
                season_id=created["id"], request=self._request(), admin=admin
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_update_archived_season_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="frozen", title="Замороженный")
        publish_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )
        archive_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            update_admin_season(
                season_id=created["id"],
                payload=SeasonUpdatePayload(title="Нельзя изменить"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._load_season(created["id"]).title, "Замороженный")

    def test_publish_archived_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEASONS_MANAGE_PERMISSION)

        created = self._create(admin, slug="no-resurrect", title="Не воскресить")
        publish_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )
        archive_admin_season(
            season_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_season(
                season_id=created["id"], request=self._request(), admin=admin
            )
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()