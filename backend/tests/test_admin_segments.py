"""Admin Segments — CRUD, FK chapter_id, фильтры списка (Sprint 8.23).

Live SQLite + alembic upgrade head (паттерн test_admin_chapters.py): disposable
БД со схемой из миграций. Endpoint-функции вызываются напрямую с реальными
AdminUser из БД и замоканным SessionLocal модуля admin_segments.

Покрывает Sprint 8.23 (Этап 1, часть 2a):
  - GET /api/v1/admin/segments?chapter_id=... — только сегменты этой главы;
  - несуществующая глава -> 404;
  - без параметра — все сегменты (обратная совместимость).
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
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.admin_access import DIRECT_EXECUTION_MODE
from app.admin_segments import (
    SEGMENT_MANAGE_PERMISSION,
    SEGMENT_READ_PERMISSION,
    AdminSegmentCreatePayload,
    create_admin_segment,
    list_admin_segments,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AdminSegmentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-segments-tests-"
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

        from app import admin_segments

        cls.admin_segments = admin_segments
        cls._session_local_patch = patch.object(
            admin_segments, "SessionLocal", cls.SessionLocal
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

    def _make_chapter(
        self,
        *,
        season_id: str,
        slug: str,
        title: str | None = None,
        status: str = "draft",
        sort_order: int = 0,
    ) -> str:
        from app.models import Chapter

        chapter_id = f"chapter-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Chapter(
                    id=chapter_id,
                    season_id=season_id,
                    slug=slug,
                    title=title or f"Глава {slug}",
                    description=None,
                    status=status,
                    sort_order=sort_order,
                )
            )
        return chapter_id

    def _create_segment(
        self,
        admin,
        *,
        chapter_id: str,
        slug: str | None = None,
        title: str | None = None,
        sort_order: int = 0,
    ):
        payload = AdminSegmentCreatePayload(
            chapter_id=chapter_id,
            slug=slug or f"segment-{uuid.uuid4().hex[:8]}",
            title=title or f"Сегмент {uuid.uuid4().hex[:6]}",
            sort_order=sort_order,
        )
        return create_admin_segment(
            payload=payload,
            request=self._request(),
            admin=admin,
        )["segment"]


# ---- Тесты --------------------------------------------------------------

    def test_list_segments_chapter_filter(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEGMENT_READ_PERMISSION)
        self._grant(admin.id, SEGMENT_MANAGE_PERMISSION)

        season_one = self._make_season(slug="seg-season-one", status="published")
        season_two = self._make_season(slug="seg-season-two", status="published")
        chapter_one = self._make_chapter(
            season_id=season_one, slug="chapter-s1", title="S1 глава"
        )
        chapter_two = self._make_chapter(
            season_id=season_two, slug="chapter-s2", title="S2 глава"
        )

        self._create_segment(
            admin,
            chapter_id=chapter_one,
            slug="segment-s1",
            title="S1 сегмент",
            sort_order=1,
        )
        self._create_segment(
            admin,
            chapter_id=chapter_two,
            slug="segment-s2",
            title="S2 сегмент",
            sort_order=2,
        )

        filtered = list_admin_segments(chapter_id=chapter_one, _admin=admin)
        slugs = [segment["slug"] for segment in filtered["segments"]]
        self.assertIn("segment-s1", slugs)
        self.assertNotIn("segment-s2", slugs)

        with self.assertRaises(HTTPException) as caught:
            list_admin_segments(chapter_id="chapter-nonexistent", _admin=admin)
        self.assertEqual(caught.exception.status_code, 404)

    def test_list_segments_no_filter_returns_all(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEGMENT_READ_PERMISSION)
        self._grant(admin.id, SEGMENT_MANAGE_PERMISSION)

        season = self._make_season(slug="seg-season-all", status="published")
        chapter_one = self._make_chapter(
            season_id=season, slug="chapter-all-1", title="Глава A"
        )
        chapter_two = self._make_chapter(
            season_id=season, slug="chapter-all-2", title="Глава B"
        )

        self._create_segment(
            admin,
            chapter_id=chapter_one,
            slug="segment-all-1",
            title="Сегмент A",
            sort_order=1,
        )
        self._create_segment(
            admin,
            chapter_id=chapter_two,
            slug="segment-all-2",
            title="Сегмент B",
            sort_order=2,
        )

        # Без параметра chapter_id — оба сегмента в списке (обратная
        # совместимость; в списке могут быть и сегменты из других тестов).
        result = list_admin_segments(_admin=admin)
        slug_set = {segment["slug"] for segment in result["segments"]}
        self.assertIn("segment-all-1", slug_set)
        self.assertIn("segment-all-2", slug_set)

    def test_create_segment_without_slug_generates_from_title(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEGMENT_READ_PERMISSION)
        self._grant(admin.id, SEGMENT_MANAGE_PERMISSION)

        season = self._make_season(slug="seg-season-autoslug", status="published")
        chapter_id = self._make_chapter(
            season_id=season,
            slug="chapter-autoslug",
            title="Глава для автогенерации",
        )

        created = create_admin_segment(
            payload=AdminSegmentCreatePayload(
                chapter_id=chapter_id,
                slug=None,
                title="Тестовый сегмент",
                sort_order=0,
            ),
            request=self._request(),
            admin=admin,
        )["segment"]

        # "Тестовый сегмент" -> транслит "testovyy-segment", суффикс не нужен.
        self.assertEqual(created["slug"], "testovyy-segment")

    def test_create_segment_with_same_title_appends_suffix(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, SEGMENT_READ_PERMISSION)
        self._grant(admin.id, SEGMENT_MANAGE_PERMISSION)

        season = self._make_season(slug="seg-season-suffix", status="published")
        chapter_id = self._make_chapter(
            season_id=season,
            slug="chapter-suffix",
            title="Глава для суффиксов",
        )

        # Уникальный маркер в title — БД класса общая, изолируем от других тестов.
        marker = uuid.uuid4().hex[:6]

        def _create_with_title(title: str) -> dict:
            return create_admin_segment(
                payload=AdminSegmentCreatePayload(
                    chapter_id=chapter_id,
                    slug=None,
                    title=title,
                    sort_order=0,
                ),
                request=self._request(),
                admin=admin,
            )["segment"]

        first = _create_with_title(f"Тест-сегмент-{marker}")
        second = _create_with_title(f"Тест-сегмент-{marker}")

        self.assertEqual(first["slug"], f"test-segment-{marker}")
        self.assertEqual(second["slug"], f"test-segment-{marker}-2")


if __name__ == "__main__":
    unittest.main()