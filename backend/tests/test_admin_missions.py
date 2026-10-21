"""Admin API tests for mission participation category (mission_category).

Integration-style: the real endpoint functions are called directly against an
Alembic-created disposable SQLite database, mirroring the harness used by
test_admin_mission_runtime_policies. The endpoints are decorated with the
appropriate HTTP status codes, so a direct success return corresponds to
201/200 and an HTTPException to 422 in the wire contract.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_missions import (
    AdminMissionCreatePayload,
    AdminMissionUpdatePayload,
    create_admin_mission,
    list_admin_missions,
    update_admin_mission,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def _create_payload(**overrides) -> AdminMissionCreatePayload:
    data = {
        "chapter_id": "chapter-fixture",
        "slug": f"mission-{uuid.uuid4().hex[:10]}",
        "mission_type": "text_answer",
        "mission_category": "solo",
        "title": "Category test mission",
        "description": "Mission created by test_admin_missions",
        "content": {},
        "validation_config": {},
        "sort_order": 1,
        "rewards": [],
    }
    data.update(overrides)
    return AdminMissionCreatePayload(**data)


class AdminMissionsCategoryApiTests(unittest.TestCase):
    """Create/update a mission through the admin API with mission_category."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-mission-category-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "missions.sqlite3"
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

        import app.admin_missions as router_module

        cls.router_module = router_module
        cls._session_local_patch = patch.object(
            router_module,
            "SessionLocal",
            cls.SessionLocal,
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _references_fixture(self) -> dict[str, str]:
        """Seed Season, Chapter and a super-admin to satisfy the create path."""
        from app.models import AdminUser, Chapter, Season

        suffix = uuid.uuid4().hex
        ids = {
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "admin": f"admin-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="Mission category season",
                    description="Isolated integration fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                Chapter(
                    id=ids["chapter"],
                    season_id=ids["season"],
                    slug=f"chapter-{suffix}",
                    title="Mission category chapter",
                    description="Isolated integration fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                AdminUser(
                    id=ids["admin"],
                    username=f"mission-admin-{suffix[:8]}",
                    password_hash="not-a-real-hash",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                )
            )
        return ids

    def _admin(self, admin_id: str):
        from app.models import AdminUser

        with self.SessionLocal.begin() as session:
            return session.get(AdminUser, admin_id)

    def test_create_mission_with_category(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        payload = _create_payload(chapter_id=ids["chapter"])

        created = create_admin_mission(payload, request=None, admin=admin)[
            "mission"
        ]

        self.assertEqual(created["missionType"], "text_answer")
        self.assertEqual(created["missionCategory"], "solo")

    def test_create_mission_invalid_category_returns_422(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        payload = _create_payload(
            chapter_id=ids["chapter"],
            mission_category="bogus",
        )

        with self.assertRaises(HTTPException) as context:
            create_admin_mission(payload, request=None, admin=admin)

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn(
            "Неизвестная категория миссии",
            context.exception.detail,
        )

    def test_update_mission_category(self) -> None:
        from app.models import Mission

        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        mission_id = create_admin_mission(
            _create_payload(chapter_id=ids["chapter"]),
            request=None,
            admin=admin,
        )["mission"]["id"]

        updated = update_admin_mission(
            mission_id,
            AdminMissionUpdatePayload(mission_category="team"),
            request=None,
            admin=admin,
        )["mission"]

        self.assertEqual(updated["missionCategory"], "team")

        with self.SessionLocal.begin() as session:
            stored_category = session.scalar(
                select(Mission.mission_category).where(Mission.id == mission_id)
            )

            self.assertEqual(stored_category, "team")

    def test_create_mission_with_minigame_profile(self) -> None:
        from app.models import MinigameProfile, Mission

        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        profile_id = f"minigame-profile-{uuid.uuid4().hex[:10]}"
        with self.SessionLocal.begin() as session:
            session.add(
                MinigameProfile(
                    id=profile_id,
                    name=f"cipher-profile-{uuid.uuid4().hex[:8]}",
                    game_type="cipher",
                    settings={
                        "drumCount": 4,
                        "alphabet": ["R", "O", "T", "G", "A", "M", "E"],
                        "falseChoicesPerDrum": 2,
                    },
                    status="published",
                )
            )

        payload = _create_payload(
            chapter_id=ids["chapter"],
            minigame_profile_id=profile_id,
        )

        created = create_admin_mission(payload, request=None, admin=admin)[
            "mission"
        ]

        self.assertEqual(created["minigameProfileId"], profile_id)

        with self.SessionLocal.begin() as session:
            stored_profile_id = session.scalar(
                select(Mission.minigame_profile_id).where(Mission.id == created["id"])
            )
            self.assertEqual(stored_profile_id, profile_id)

    def test_create_mission_invalid_minigame_profile_returns_422(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        payload = _create_payload(
            chapter_id=ids["chapter"],
            minigame_profile_id="minigame-profile-does-not-exist",
        )

        with self.assertRaises(HTTPException) as context:
            create_admin_mission(payload, request=None, admin=admin)

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn(
            "профиль мини-игры",
            context.exception.detail,
        )

    def test_update_mission_minigame_profile(self) -> None:
        from app.models import MinigameProfile, Mission

        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        mission_id = create_admin_mission(
            _create_payload(chapter_id=ids["chapter"]),
            request=None,
            admin=admin,
        )["mission"]["id"]

        profile_id = f"minigame-profile-{uuid.uuid4().hex[:10]}"
        with self.SessionLocal.begin() as session:
            session.add(
                MinigameProfile(
                    id=profile_id,
                    name=f"cipher-profile-{uuid.uuid4().hex[:8]}",
                    game_type="cipher",
                    settings={},
                    status="published",
                )
            )

        updated = update_admin_mission(
            mission_id,
            AdminMissionUpdatePayload(minigame_profile_id=profile_id),
            request=None,
            admin=admin,
        )["mission"]

        self.assertEqual(updated["minigameProfileId"], profile_id)

        with self.SessionLocal.begin() as session:
            stored_profile_id = session.scalar(
                select(Mission.minigame_profile_id).where(Mission.id == mission_id)
            )
            self.assertEqual(stored_profile_id, profile_id)

    def test_update_mission_invalid_minigame_profile_returns_422(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        mission_id = create_admin_mission(
            _create_payload(chapter_id=ids["chapter"]),
            request=None,
            admin=admin,
        )["mission"]["id"]

        with self.assertRaises(HTTPException) as context:
            update_admin_mission(
                mission_id,
                AdminMissionUpdatePayload(
                    minigame_profile_id="minigame-profile-does-not-exist"
                ),
                request=None,
                admin=admin,
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn(
            "профиль мини-игры",
            context.exception.detail,
        )

    def test_list_missions_chapter_filter(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        # Вторая глава в том же сезоне — напрямую через модель (этот стиль
        # уже используется в тестах файла для MinigameProfile).
        from app.models import Chapter

        second_chapter_id = f"chapter-second-{uuid.uuid4().hex[:10]}"
        with self.SessionLocal.begin() as session:
            session.add(
                Chapter(
                    id=second_chapter_id,
                    season_id=ids["season"],
                    slug=f"chapter-second-{uuid.uuid4().hex[:10]}",
                    title="Second chapter",
                    description="Isolated integration fixture",
                    status="published",
                    sort_order=2,
                )
            )

        mission_one = create_admin_mission(
            _create_payload(chapter_id=ids["chapter"], title="Mission one"),
            request=None,
            admin=admin,
        )["mission"]
        mission_two = create_admin_mission(
            _create_payload(chapter_id=second_chapter_id, title="Mission two"),
            request=None,
            admin=admin,
        )["mission"]

        filtered = list_admin_missions(chapter_id=ids["chapter"], _admin=admin)
        filtered_ids = [mission["id"] for mission in filtered["missions"]]
        self.assertIn(mission_one["id"], filtered_ids)
        self.assertNotIn(mission_two["id"], filtered_ids)

        with self.assertRaises(HTTPException) as caught:
            list_admin_missions(chapter_id="chapter-nonexistent", _admin=admin)
        self.assertEqual(caught.exception.status_code, 404)

        # Обратная совместимость: без chapter_id обе миссии в списке
        # (в списке могут быть и миссии из других тестов).
        all_missions = list_admin_missions(_admin=admin)["missions"]
        all_ids = [mission["id"] for mission in all_missions]
        self.assertIn(mission_one["id"], all_ids)
        self.assertIn(mission_two["id"], all_ids)