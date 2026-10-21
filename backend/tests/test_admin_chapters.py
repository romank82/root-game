"""Admin Chapters — CRUD, FK season_id, статусные переходы (Sprint 8.22).

Live SQLite + alembic upgrade head (паттерн test_admin_seasons.py): disposable
БД со схемой из миграций (включая таблицы seasons/chapters и admin
permissions chapters.read/chapters.manage). Endpoint-функции вызываются
напрямую с реальными AdminUser из БД и замоканным SessionLocal модуля.

Покрытые согласованные решения (Sprint 8.22, D3):
(а) create в archived-сезон -> 422; (б) смена season_id у published-главы -> 409;
(в) повторный publish published-главы -> 422.
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
from app.admin_chapters import (
    CHAPTERS_MANAGE_PERMISSION,
    CHAPTERS_READ_PERMISSION,
    ChapterCreatePayload,
    ChapterUpdatePayload,
    archive_admin_chapter,
    create_admin_chapter,
    get_admin_chapter,
    list_admin_chapters,
    publish_admin_chapter,
    update_admin_chapter,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AdminChaptersTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-chapters-tests-"
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

        from app import admin_chapters

        cls.admin_chapters = admin_chapters
        cls._session_local_patch = patch.object(
            admin_chapters, "SessionLocal", cls.SessionLocal
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

    def _make_season(
        self,
        *,
        slug: str,
        title: str | None = None,
        status: str = "draft",
        sort_order: int = 0,
    ) -> str:
        from app.models import Season

        season_id = f"season-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=season_id,
                    slug=slug,
                    title=title or f"Сезон {slug}",
                    status=status,
                    sort_order=sort_order,
                )
            )
        return season_id

    def _create(self, admin, *, season_id, slug=None, title=None, **kwargs):
        payload = ChapterCreatePayload(
            season_id=season_id,
            slug=slug,
            title=title or f"Глава {uuid.uuid4().hex[:6]}",
            **kwargs,
        )
        return create_admin_chapter(
            payload=payload,
            request=self._request(),
            admin=admin,
        )["chapter"]

    def _load_chapter(self, chapter_id: str):
        from app.models import Chapter

        with self.SessionLocal() as session:
            return session.get(Chapter, chapter_id)

    def _count_audit(self, action: str, admin_id: str) -> int:
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return len(
                session.scalars(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == action,
                        AdminAuditLog.entity_type == "chapter",
                        AdminAuditLog.admin_user_id == admin_id,
                    )
                ).all()
            )


# ---- Тесты --------------------------------------------------------------

    def test_create_chapter_in_published_season(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-create", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="chapter-one", title="Глава первая"
        )

        self.assertTrue(created["id"].startswith("chapter-"))
        self.assertEqual(created["slug"], "chapter-one")
        self.assertEqual(created["title"], "Глава первая")
        self.assertEqual(created["seasonId"], season_id)
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["sortOrder"], 0)

        stored = self._load_chapter(created["id"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, "draft")
        self.assertEqual(stored.season_id, season_id)
        self.assertEqual(self._count_audit("chapter.created", admin.id), 1)

    def test_create_autoslug_from_russian_title(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-autoslug", status="published"
        )

        created = self._create(admin, season_id=season_id, title="ГЛАВА 2: ПЕРЕХОД")

        self.assertEqual(created["slug"], "glava-2-perekhod")

    def test_create_missing_season_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin, season_id="season-not-exists", slug="no-season", title="Нет сезона"
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_create_in_archived_season_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-archived", status="archived"
        )

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin, season_id=season_id, slug="archived-host", title="В архиве"
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_create_duplicate_slug_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-dup", status="published"
        )

        first = self._create(
            admin, season_id=season_id, slug="duplicated", title="Первый"
        )

        with self.assertRaises(HTTPException) as caught:
            self._create(
                admin, season_id=season_id, slug="duplicated", title="Второй"
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._load_chapter(first["id"]).slug, "duplicated")

    def test_publish_in_draft_season_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(slug="ch-season-draft", status="draft")

        created = self._create(
            admin, season_id=season_id, slug="draft-home", title="Сезон в черновике"
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_chapter(
                chapter_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self._load_chapter(created["id"]).status, "draft")

    def test_publish_in_published_season_ok(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-pub", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="publish-me", title="Опубликовать"
        )

        published = publish_admin_chapter(
            chapter_id=created["id"],
            request=self._request(),
            admin=admin,
        )["chapter"]

        self.assertEqual(published["status"], "published")
        self.assertEqual(self._load_chapter(created["id"]).status, "published")
        self.assertEqual(self._count_audit("chapter.published", admin.id), 1)

    def test_publish_twice_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-twice", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="double-publish", title="Двойная публикация"
        )
        publish_admin_chapter(
            chapter_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            publish_admin_chapter(
                chapter_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)


    def test_archive_published_ok(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-archive", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="archive-me", title="Архивировать"
        )
        publish_admin_chapter(
            chapter_id=created["id"], request=self._request(), admin=admin
        )

        archived = archive_admin_chapter(
            chapter_id=created["id"],
            request=self._request(),
            admin=admin,
        )["chapter"]

        self.assertEqual(archived["status"], "archived")
        self.assertEqual(self._load_chapter(created["id"]).status, "archived")
        self.assertEqual(self._count_audit("chapter.archived", admin.id), 1)

    def test_archive_draft_422(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-draft2", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="archive-draft", title="Архив черновика"
        )

        with self.assertRaises(HTTPException) as caught:
            archive_admin_chapter(
                chapter_id=created["id"],
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 422)

    def test_update_published_change_season_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_a = self._make_season(
            slug="ch-season-a", status="published"
        )
        season_b = self._make_season(
            slug="ch-season-b", status="published"
        )

        created = self._create(
            admin, season_id=season_a, slug="frozen-home", title="Закреплённая"
        )
        publish_admin_chapter(
            chapter_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            update_admin_chapter(
                chapter_id=created["id"],
                payload=ChapterUpdatePayload(season_id=season_b),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(
            self._load_chapter(created["id"]).season_id, season_a
        )

    def test_update_archived_409(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-frozen", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="frozen", title="Замороженная"
        )
        publish_admin_chapter(
            chapter_id=created["id"], request=self._request(), admin=admin
        )
        archive_admin_chapter(
            chapter_id=created["id"], request=self._request(), admin=admin
        )

        with self.assertRaises(HTTPException) as caught:
            update_admin_chapter(
                chapter_id=created["id"],
                payload=ChapterUpdatePayload(title="Нельзя изменить"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(self._load_chapter(created["id"]).title, "Замороженная")


    def test_get_chapter_and_404(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_READ_PERMISSION)
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-get", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="get-me", title="Get-Me"
        )

        got = get_admin_chapter(chapter_id=created["id"], _admin=admin)
        self.assertEqual(got["chapter"]["id"], created["id"])
        self.assertEqual(got["chapter"]["title"], "Get-Me")
        self.assertEqual(got["chapter"]["seasonId"], season_id)

        with self.assertRaises(HTTPException) as caught:
            get_admin_chapter(chapter_id="chapter-missing", _admin=admin)
        self.assertEqual(caught.exception.status_code, 404)

    def test_list_chapters_ordered_and_status_filter(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_READ_PERMISSION)
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-list", status="published"
        )

        self._create(
            admin, season_id=season_id, slug="chapter-b", title="B-глава", sort_order=2
        )
        first = self._create(
            admin, season_id=season_id, slug="chapter-a", title="A-глава", sort_order=1
        )
        publish_admin_chapter(
            chapter_id=first["id"], request=self._request(), admin=admin
        )

        result = list_admin_chapters(_admin=admin)
        slugs = [chapter["slug"] for chapter in result["chapters"]]
        self.assertIn("chapter-a", slugs)
        self.assertIn("chapter-b", slugs)
        self.assertLess(slugs.index("chapter-a"), slugs.index("chapter-b"))

        published = list_admin_chapters(status="published", _admin=admin)
        published_slugs = [chapter["slug"] for chapter in published["chapters"]]
        self.assertIn("chapter-a", published_slugs)
        self.assertNotIn("chapter-b", published_slugs)

        with self.assertRaises(HTTPException) as caught:
            list_admin_chapters(status="unknown", _admin=admin)
        self.assertEqual(caught.exception.status_code, 422)

    def test_list_chapters_season_filter(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_READ_PERMISSION)
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)

        season_one = self._make_season(
            slug="ch-season-one", status="published"
        )
        season_two = self._make_season(
            slug="ch-season-two", status="published"
        )

        self._create(
            admin,
            season_id=season_one,
            slug="chapter-s1",
            title="S1 глава",
            sort_order=1,
        )
        self._create(
            admin,
            season_id=season_two,
            slug="chapter-s2",
            title="S2 глава",
            sort_order=2,
        )

        filtered = list_admin_chapters(season_id=season_one, _admin=admin)
        slugs = [chapter["slug"] for chapter in filtered["chapters"]]
        self.assertIn("chapter-s1", slugs)
        self.assertNotIn("chapter-s2", slugs)

        with self.assertRaises(HTTPException) as caught:
            list_admin_chapters(season_id="season-nonexistent", _admin=admin)
        self.assertEqual(caught.exception.status_code, 404)

    def test_lifecycle_writes_audit_records(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, CHAPTERS_MANAGE_PERMISSION)
        season_id = self._make_season(
            slug="ch-season-audit", status="published"
        )

        created = self._create(
            admin, season_id=season_id, slug="lifecycle", title="Жизненный цикл"
        )
        publish_admin_chapter(
            chapter_id=created["id"], request=self._request(), admin=admin
        )
        archive_admin_chapter(
            chapter_id=created["id"], request=self._request(), admin=admin
        )

        self.assertEqual(self._count_audit("chapter.created", admin.id), 1)
        self.assertEqual(self._count_audit("chapter.published", admin.id), 1)
        self.assertEqual(self._count_audit("chapter.archived", admin.id), 1)


if __name__ == "__main__":
    unittest.main()