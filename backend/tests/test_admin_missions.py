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
    MissionTranslationsPayload,
    create_admin_mission,
    get_mission_translations,
    list_admin_missions,
    publish_admin_mission,
    put_mission_translations,
    update_admin_mission,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def _create_payload(**overrides) -> AdminMissionCreatePayload:
    data = {
        "season_id": "season-fixture",
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


class AdminMissionsApiTests(unittest.TestCase):
    """Admin missions API: mission_category, профиль мини-игры, переводы контента."""

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
        """Seed Season and a super-admin to satisfy the create path."""
        from app.models import AdminUser, Season

        suffix = uuid.uuid4().hex
        ids = {
            "season": f"season-{suffix}",
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
        payload = _create_payload(season_id=ids["season"])

        created = create_admin_mission(payload, request=None, admin=admin)[
            "mission"
        ]

        self.assertEqual(created["missionType"], "text_answer")
        self.assertEqual(created["missionCategory"], "solo")

    def test_create_mission_invalid_category_returns_422(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        payload = _create_payload(
            season_id=ids["season"],
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
            _create_payload(season_id=ids["season"]),
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
            season_id=ids["season"],
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
            season_id=ids["season"],
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
            _create_payload(season_id=ids["season"]),
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
            _create_payload(season_id=ids["season"]),
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

    def test_list_missions_season_filter(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        # Второй сезон — напрямую через модель (стиль файла для MinigameProfile).
        from app.models import Season

        second_season_id = f"season-second-{uuid.uuid4().hex[:10]}"
        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=second_season_id,
                    slug=f"season-second-{uuid.uuid4().hex[:10]}",
                    title="Second season",
                    description="Isolated integration fixture",
                    status="published",
                    sort_order=2,
                )
            )

        mission_one = create_admin_mission(
            _create_payload(season_id=ids["season"], title="Mission one"),
            request=None,
            admin=admin,
        )["mission"]
        mission_two = create_admin_mission(
            _create_payload(season_id=second_season_id, title="Mission two"),
            request=None,
            admin=admin,
        )["mission"]

        filtered = list_admin_missions(season_id=ids["season"], _admin=admin)
        filtered_ids = [mission["id"] for mission in filtered["missions"]]
        self.assertIn(mission_one["id"], filtered_ids)
        self.assertNotIn(mission_two["id"], filtered_ids)

        with self.assertRaises(HTTPException) as caught:
            list_admin_missions(season_id="season-nonexistent", _admin=admin)
        self.assertEqual(caught.exception.status_code, 404)

        # Обратная совместимость: без season_id обе миссии в списке
        # (в списке могут быть и миссии из других тестов).
        all_missions = list_admin_missions(_admin=admin)["missions"]
        all_ids = [mission["id"] for mission in all_missions]
        self.assertIn(mission_one["id"], all_ids)
        self.assertIn(mission_two["id"], all_ids)

    def test_create_mission_without_slug_generates_from_title(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        created = create_admin_mission(
            _create_payload(
                season_id=ids["season"],
                slug=None,
                title="Тестовая миссия",
            ),
            request=None,
            admin=admin,
        )["mission"]

        # "Тестовая миссия" -> транслит "testovaya-missiya", суффикс не нужен.
        self.assertEqual(created["slug"], "testovaya-missiya")

    def test_create_mission_with_same_title_appends_suffix(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])

        def _create_with_title(title: str) -> dict:
            return create_admin_mission(
                _create_payload(
                    season_id=ids["season"],
                    slug=None,
                    title=title,
                ),
                request=None,
                admin=admin,
            )["mission"]

        first = _create_with_title("Транслит-миссия")
        second = _create_with_title("Транслит-миссия")

        self.assertEqual(first["slug"], "translit-missiya")
        self.assertEqual(second["slug"], "translit-missiya-2")

    # ---- Sprint Trans-2b-2: перевод контента миссии ------------------------

    def _publication_targets(self) -> dict[str, str]:
        """GeoZone + ARObject: обязательные привязки для публикации миссии."""
        from app.models import ARObject, GeoZone

        suffix = uuid.uuid4().hex[:10]
        ids = {
            "geo_zone": f"geo-zone-{suffix}",
            "ar_object": f"ar-object-{suffix}",
        }
        with self.SessionLocal.begin() as session:
            session.add(
                GeoZone(
                    id=ids["geo_zone"],
                    slug=f"geo-zone-{suffix}",
                    title="Translation test zone",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                ARObject(
                    id=ids["ar_object"],
                    slug=f"ar-object-{suffix}",
                    title="Translation test object",
                    status="published",
                    sort_order=1,
                    geo_zone_id=ids["geo_zone"],
                    object_type="marker",
                    asset_uri="models/marker.glb",
                )
            )
        return ids

    def _publishable_mission(self, ids: dict[str, str], admin) -> str:
        """Миссия, проходящая все прочие проверки publish (без переводов)."""
        targets = self._publication_targets()
        return create_admin_mission(
            _create_payload(
                season_id=ids["season"],
                geo_zone_id=targets["geo_zone"],
                ar_object_id=targets["ar_object"],
                content={
                    "schemaVersion": 1,
                    "ui": {"label": "Метка", "question": "Вопрос?"},
                },
                validation_config={
                    "validator": "normalized_text_match",
                    "acceptedAnswers": ["ключ"],
                },
            ),
            request=None,
            admin=admin,
        )["mission"]["id"]

    def test_get_mission_translations_defaults(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        mission_id = create_admin_mission(
            _create_payload(
                season_id=ids["season"],
                content={"schemaVersion": 1, "ui": {"label": "Метка"}},
            ),
            request=None,
            admin=admin,
        )["mission"]["id"]

        result = get_mission_translations(mission_id, _admin=admin)

        self.assertEqual(result["missionId"], mission_id)
        self.assertEqual(result["translations"], {})
        self.assertEqual(result["translationStatus"], "none")
        self.assertEqual(result["supportedLanguages"], ["ru", "en", "zh"])
        self.assertEqual(result["requiredContentUiKeys"], ["label"])

    def test_put_mission_translations_complete(self) -> None:
        from app.models import Mission

        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        mission_id = create_admin_mission(
            _create_payload(
                season_id=ids["season"],
                content={"schemaVersion": 1, "ui": {"label": "Метка"}},
            ),
            request=None,
            admin=admin,
        )["mission"]["id"]

        result = put_mission_translations(
            mission_id,
            MissionTranslationsPayload(
                translations={
                    "en": {
                        "title": "Label mission",
                        "description": "English description",
                        "contentUi": {"label": "Label"},
                    },
                    "zh": {
                        "title": "标签任务",
                        "description": "中文描述",
                        "contentUi": {"label": "标签"},
                    },
                }
            ),
            request=None,
            admin=admin,
        )

        self.assertEqual(result["translationStatus"], "complete")
        self.assertEqual(sorted(result["translations"]), ["en", "zh"])

        with self.SessionLocal.begin() as session:
            stored = session.get(Mission, mission_id)
            self.assertEqual(stored.translation_status, "complete")
            self.assertEqual(
                stored.translations["en"]["title"],
                "Label mission",
            )
            self.assertEqual(
                stored.translations["zh"]["contentUi"]["label"],
                "标签",
            )

    def test_put_mission_translations_partial_when_language_missing(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        mission_id = create_admin_mission(
            _create_payload(
                season_id=ids["season"],
                content={"schemaVersion": 1, "ui": {"label": "Метка"}},
            ),
            request=None,
            admin=admin,
        )["mission"]["id"]

        result = put_mission_translations(
            mission_id,
            MissionTranslationsPayload(
                translations={
                    "en": {
                        "title": "Only English",
                        "description": "English description",
                        "contentUi": {"label": "Label"},
                    }
                }
            ),
            request=None,
            admin=admin,
        )

        self.assertEqual(result["translationStatus"], "partial")
        self.assertEqual(sorted(result["translations"]), ["en"])

    def test_put_mission_translations_rejects_unsupported_language(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        mission_id = create_admin_mission(
            _create_payload(season_id=ids["season"]),
            request=None,
            admin=admin,
        )["mission"]["id"]

        with self.assertRaises(HTTPException) as context:
            put_mission_translations(
                mission_id,
                MissionTranslationsPayload(
                    translations={
                        "de": {"title": "Titel", "description": "Beschreibung"}
                    }
                ),
                request=None,
                admin=admin,
            )

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("не поддерживается", context.exception.detail)

    def test_publish_requires_complete_translations(self) -> None:
        ids = self._references_fixture()
        admin = self._admin(ids["admin"])
        mission_id = self._publishable_mission(ids, admin)

        with self.assertRaises(HTTPException) as context:
            publish_admin_mission(mission_id, request=None, admin=admin)

        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("Перевод не завершён", context.exception.detail)

        put_mission_translations(
            mission_id,
            MissionTranslationsPayload(
                translations={
                    "en": {
                        "title": "Label mission",
                        "description": "English description",
                        "contentUi": {"label": "Label", "question": "Question?"},
                    },
                    "zh": {
                        "title": "标签任务",
                        "description": "中文描述",
                        "contentUi": {"label": "标签", "question": "问题?"},
                    },
                }
            ),
            request=None,
            admin=admin,
        )

        published = publish_admin_mission(
            mission_id,
            request=None,
            admin=admin,
        )["mission"]

        self.assertEqual(published["status"], "published")
        self.assertEqual(published["translationStatus"], "complete")
