"""Sprint Trans-4a: bootstrap с ?lang= — резолв перевода контента миссии.

Два уровня проверки:

1. Чистые функции резолва (`_resolve_mission_translation`,
   `_localize_mission_content`) — без БД, на объекте Mission в памяти.
2. Сквозной `get_bootstrap(player, lang=...)` на одноразовой SQLite-БД
   (alembic upgrade head, паттерн test_mission_engine_accept).
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

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def _memory_mission(**overrides):
    """Mission в памяти: без БД читаются только объявленные поля."""
    from app.models import Mission

    data = {
        "id": "mission-memory",
        "season_id": "season-memory",
        "slug": "mission-memory",
        "mission_type": "text_answer",
        "title": "Русское название",
        "description": "Русское описание",
        "content": {
            "schemaVersion": 1,
            "ui": {"label": "Метка", "question": "Вопрос?", "alphabet": ["R"]},
        },
        "validation_config": {},
        "translations": {
            "en": {
                "title": "English title",
                "description": "English description",
                "contentUi": {"label": "Label"},
            }
        },
    }
    data.update(overrides)
    return Mission(**data)


class MissionTranslationResolveTests(unittest.TestCase):
    """Чистый резолв: переведённый язык, fallback ru, частичный перевод."""

    def test_resolves_requested_language(self) -> None:
        from app.mission_engine import _resolve_mission_translation

        resolved = _resolve_mission_translation(_memory_mission(), "en")

        self.assertEqual(resolved["title"], "English title")
        self.assertEqual(resolved["description"], "English description")
        self.assertEqual(resolved["contentUi"], {"label": "Label"})

    def test_falls_back_to_ru_for_base_language(self) -> None:
        from app.mission_engine import _resolve_mission_translation

        for lang in ("ru", "", "zh"):
            with self.subTest(lang=lang):
                resolved = _resolve_mission_translation(_memory_mission(), lang)
                self.assertEqual(resolved["title"], "Русское название")
                self.assertEqual(resolved["description"], "Русское описание")
                self.assertEqual(resolved["contentUi"]["label"], "Метка")

    def test_falls_back_to_ru_without_translations(self) -> None:
        from app.mission_engine import _resolve_mission_translation

        resolved = _resolve_mission_translation(
            _memory_mission(translations=None),
            "en",
        )

        self.assertEqual(resolved["title"], "Русское название")

    def test_missing_title_in_entry_falls_back_per_field(self) -> None:
        from app.mission_engine import _resolve_mission_translation

        mission = _memory_mission(
            translations={"en": {"description": "Only description"}}
        )

        resolved = _resolve_mission_translation(mission, "en")

        self.assertEqual(resolved["title"], "Русское название")
        self.assertEqual(resolved["description"], "Only description")

    def test_localize_content_merges_ui_and_keeps_technical_keys(self) -> None:
        from app.mission_engine import _localize_mission_content

        mission = _memory_mission()

        localized = _localize_mission_content(mission, "en")

        self.assertEqual(localized["ui"]["label"], "Label")
        # Не переведённые ключи и технические поля остаются оригинальными.
        self.assertEqual(localized["ui"]["question"], "Вопрос?")
        self.assertEqual(localized["ui"]["alphabet"], ["R"])
        self.assertEqual(localized["schemaVersion"], 1)
        # Исходный content миссии не мутирован.
        self.assertEqual(mission.content["ui"]["label"], "Метка")

    def test_localize_content_without_translation_returns_original(self) -> None:
        from app.mission_engine import _localize_mission_content

        mission = _memory_mission()

        localized = _localize_mission_content(mission, "zh")

        self.assertEqual(localized["ui"]["label"], "Метка")


class MissionBootstrapLangTests(unittest.TestCase):
    """Сквозной bootstrap: title/description/content.ui зависят от lang."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-bootstrap-lang-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "bootstrap-lang.sqlite3"
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

        from app import mission_engine

        cls.mission_engine = mission_engine
        cls._session_local_patch = patch.object(
            mission_engine,
            "SessionLocal",
            cls.SessionLocal,
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _fixture(self) -> dict[str, str]:
        from app.models import GamePlayer, Mission, Season

        suffix = uuid.uuid4().hex
        ids = {
            "player": f"player-{suffix}",
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "mission": f"mission-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="Translation bootstrap season",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                GamePlayer(
                    id=ids["player"],
                    display_name=f"Bootstrap Player-{suffix[:6]}",
                    auth_provider="telegram",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
            session.flush()
            session.add(
                Mission(
                    id=ids["mission"],
                    season_id=ids["season"],
                    slug=f"mission-{suffix}",
                    mission_type="text_answer",
                    mission_category="solo",
                    title="Название миссии",
                    description="Описание миссии",
                    content={
                        "schemaVersion": 1,
                        "ui": {"label": "Метка", "question": "Вопрос?"},
                    },
                    validation_config={},
                    status="published",
                    sort_order=1,
                    translations={
                        "en": {
                            "title": "Mission title",
                            "description": "Mission description",
                            "contentUi": {"label": "Label"},
                        }
                    },
                    translation_status="partial",
                )
            )

        return ids

    def _mission_payload(self, bootstrap: dict, mission_id: str) -> dict:
        for mission in bootstrap["missions"]:
            if mission["id"] == mission_id:
                return mission
        raise AssertionError(f"Миссия {mission_id} отсутствует в bootstrap")

    def test_bootstrap_defaults_to_ru(self) -> None:
        ids = self._fixture()

        bootstrap = self.mission_engine.get_bootstrap(ids["player"])
        mission = self._mission_payload(bootstrap, ids["mission"])

        self.assertEqual(mission["title"], "Название миссии")
        self.assertEqual(mission["description"], "Описание миссии")
        self.assertEqual(mission["content"]["ui"]["label"], "Метка")

    def test_bootstrap_uses_english_translation(self) -> None:
        ids = self._fixture()

        bootstrap = self.mission_engine.get_bootstrap(ids["player"], lang="en")
        mission = self._mission_payload(bootstrap, ids["mission"])

        self.assertEqual(mission["title"], "Mission title")
        self.assertEqual(mission["description"], "Mission description")
        self.assertEqual(mission["content"]["ui"]["label"], "Label")
        # Не переведённый ключ остаётся оригинальным.
        self.assertEqual(mission["content"]["ui"]["question"], "Вопрос?")

    def test_bootstrap_falls_back_to_ru_without_translation(self) -> None:
        ids = self._fixture()

        bootstrap = self.mission_engine.get_bootstrap(ids["player"], lang="zh")
        mission = self._mission_payload(bootstrap, ids["mission"])

        self.assertEqual(mission["title"], "Название миссии")
        self.assertEqual(mission["content"]["ui"]["label"], "Метка")


if __name__ == "__main__":
    unittest.main()
