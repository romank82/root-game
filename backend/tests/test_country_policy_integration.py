"""13.2-b-3-b — интеграция страновых гейтов (blocked/restricted).

Покрывает четыре точки входа, где работают гейты 13.2-b:

  1. test_blocked_gate_on_entry — get_current_player_id (main.py, вход):
     политика RU=blocked, игрок country='RU' -> HTTPException 403
     «Доступ из вашей страны ограничен.». Прямой вызов функции с mock
     Request (SimpleNamespace с одной кукой chimera_session) и честным
     подписанным токеном: create_session_token / verify_session_token —
     без TestClient и без зависимости от роутеров.
  2. test_restricted_transfer_gate — transfer_root (transfer_service.py):
     DE=restricted + ['transfer'] -> MissionEngineError 403
     «Переводы из вашей страны ограничены.».
  3. test_restricted_mission_gate — accept_mission (mission_engine.py):
     FR=restricted + ['mission'] -> MissionEngineError 403
     «Миссии из вашей страны ограничены.».
  4. test_restricted_team_gate — _submit_location (team_missions_service.py):
     IT=restricted + ['team'] -> MissionEngineError 403
     «Командные миссии из вашей страны ограничены.».
     TeamSession ОСОЗНАННО не создаётся: в _submit_location страновой гейт
     стоит ДО проверки существования сессии (сразу после «игрок есть и
     active»), поэтому тест доказывает, что 403 выброшен именно гейтом:
     иначе с отсутствующей сессией упало бы 404 «Командная сессия не
     найдена», а не 403.

Инфраструктура — по образцу test_transfer_pg_10_5 / test_mission_engine_accept:
реальная SQLite + alembic upgrade head; SessionLocal патчится там, где сервис
открывает сессию сам (app.main.get_current_player_id,
mission_engine.accept_mission) плюс app.db.SessionLocal для «ленивых»
импортов (team_missions_service). transfer_root и _submit_location принимают
session аргументом, поэтому им патч не обязателен.

В приложении ничего не меняется: страна игрока и политики создаются только
в изолированной тестовой базе.
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

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


class CountryPolicyIntegrationTests(unittest.TestCase):
    """Интеграция страновых гейтов на реальной SQLite (alembic head)."""

    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-country-policy-integration-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "integration.sqlite3"
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

        from app import main, mission_engine

        cls._session_local_patches = [
            patch("app.db.SessionLocal", cls.SessionLocal),
            patch.object(main, "SessionLocal", cls.SessionLocal),
            patch.object(mission_engine, "SessionLocal", cls.SessionLocal),
        ]
        for session_local_patch in cls._session_local_patches:
            session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        for session_local_patch in cls._session_local_patches:
            session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------

    def _make_player(
        self,
        session,
        country: str | None,
        status: str = "active",
    ) -> str:
        """Игрок GamePlayer с произвольной страной (по умолчанию active)."""
        from app.models import GamePlayer

        # id обязан начинаться с "player-": verify_session_token отклоняет
        # иные профили («Игровая сессия содержит неверный профиль.»).
        player_id = f"player-country-{uuid.uuid4().hex[:10]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name=f"Country Integration Player-{player_id[-6:]}",
                auth_provider="telegram",
                external_id=f"tg-{uuid.uuid4().hex}",
                status=status,
                country=country,
            )
        )
        session.flush()
        return player_id

    # ---- Fixtures и хелперы -------------------------------------------

    def _make_policy(
        self,
        session,
        country_code: str,
        policy: str,
        restricted_features: list[str] | None = None,
    ) -> None:
        """Запись CountryPolicy (blocked/restricted + features)."""
        from app.models import CountryPolicy

        session.add(
            CountryPolicy(
                id=f"country-policy-{uuid.uuid4().hex[:24]}",
                country_code=country_code,
                policy=policy,
                restricted_features=restricted_features,
                reason=None,
            )
        )
        session.flush()

    # ---- Fixtures и хелперы -------------------------------------------

    def _make_mission_fixture(self, session, suffix: str) -> dict[str, str]:
        """Season -> Chapter -> GeoZone -> ARObject -> Mission (published)."""
        from app.models import ARObject, Chapter, GeoZone, Mission, Season

        ids = {
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "zone": f"zone-{suffix}",
            "ar_object": f"ar-object-{suffix}",
            "mission": f"mission-{suffix}",
        }
        session.add(
            Season(
                id=ids["season"],
                slug=f"season-{suffix}",
                title="Country integration season",
                description="Isolated country gate fixture",
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
                title="Country integration chapter",
                description="Isolated country gate fixture",
                status="published",
                sort_order=1,
            )
        )
        session.flush()

        session.add(
            GeoZone(
                id=ids["zone"],
                slug=f"zone-{suffix}",
                title="Country integration zone",
                description="Isolated country gate fixture",
                zone_type="radius",
                status="published",
                sort_order=1,
                radius_meters=50,
                search_radius_meters=3000,
                location_constraints={"avoid_buildings": True},
                timezone="UTC",
            )
        )
        session.flush()

        session.add(
            ARObject(
                id=ids["ar_object"],
                slug=f"ar-object-{suffix}",
                title="Country integration AR object",
                description="Isolated country gate fixture",
                status="published",
                sort_order=1,
                geo_zone_id=ids["zone"],
                object_type="collectible",
                asset_uri=f"https://example.test/assets/{suffix}.glb",
                asset_mime_type="model/gltf-binary",
                scene_preset="default",
                scale_meters=1.0,
                orientation="upright",
                discovery_scenario={},
                minigame_config={},
                instruction_text="Country integration instruction",
                validation_config={},
            )
        )
        session.flush()

        session.add(
            Mission(
                id=ids["mission"],
                chapter_id=ids["chapter"],
                slug=f"mission-{suffix}",
                mission_type="text_answer",
                mission_category="solo",
                title="Country integration mission",
                description="Isolated country gate fixture",
                content={"schemaVersion": 1},
                validation_config={},
                status="published",
                sort_order=1,
                geo_zone_id=ids["zone"],
                ar_object_id=ids["ar_object"],
                execution_time_limit_seconds=None,
                reentry_cooldown_seconds=0,
                unlock_after_mission_id=None,
            )
        )
        session.flush()
        return ids

    # ---- Тесты ----------------------------------------------------------

    def test_blocked_gate_on_entry(self) -> None:
        """blocked-страна -> HTTPException 403 на идентификации игрока."""
        from types import SimpleNamespace

        from fastapi import HTTPException

        from app.config import settings
        from app.main import SESSION_COOKIE_NAME, get_current_player_id
        from app.telegram_auth import create_session_token

        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, country="RU")
            self._make_policy(session, "RU", "blocked")

        token = create_session_token(
            player_id=player_id,
            session_secret=settings.game_session_secret,
            lifetime_seconds=3600,
        )
        request = SimpleNamespace(cookies={SESSION_COOKIE_NAME: token})

        with self.assertRaises(HTTPException) as ctx:
            get_current_player_id(request)

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Доступ из вашей страны ограничен.", ctx.exception.detail)

    def test_restricted_transfer_gate(self) -> None:
        """restricted + ['transfer'] -> MissionEngineError 403 в transfer_root."""
        from app.mission_engine import MissionEngineError
        from app.transfer_service import transfer_root

        with self.SessionLocal.begin() as session:
            from_player_id = self._make_player(session, country="DE")
            to_player_id = self._make_player(session, country="US")
            self._make_policy(session, "DE", "restricted", ["transfer"])

        with self.SessionLocal() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(
                    session,
                    from_player_id=from_player_id,
                    to_player_id=to_player_id,
                    amount=1000,
                    request_id=f"transfer-{uuid.uuid4().hex}",
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Переводы из вашей страны ограничены.", ctx.exception.detail)

    def test_restricted_mission_gate(self) -> None:
        """restricted + ['mission'] -> MissionEngineError 403 в accept_mission."""
        from app.mission_engine import MissionEngineError, accept_mission

        suffix = uuid.uuid4().hex
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, country="FR")
            self._make_policy(session, "FR", "restricted", ["mission"])
            mission_ids = self._make_mission_fixture(session, suffix)

        with self.assertRaises(MissionEngineError) as ctx:
            accept_mission(
                player_id=player_id,
                mission_id=mission_ids["mission"],
                latitude=self.PLAYER_LATITUDE,
                longitude=self.PLAYER_LONGITUDE,
                accuracy=10.0,
            )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Миссии из вашей страны ограничены.", ctx.exception.detail)

    def test_restricted_team_gate(self) -> None:
        """restricted + ['team'] -> MissionEngineError 403 в _submit_location.

        TeamSession намеренно НЕ создаётся: страновой гейт стоит в
        _submit_location ДО проверки существования сессии, поэтому 403
        может быть выброшен только гейтом (иначе был бы 404 «Командная
        сессия не найдена»).
        """
        from app.mission_engine import MissionEngineError
        from app.team_missions_service import _submit_location

        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, country="IT")
            self._make_policy(session, "IT", "restricted", ["team"])

        with self.SessionLocal() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                _submit_location(
                    session,
                    player_id=player_id,
                    session_id="team-session-absent",
                    latitude=self.PLAYER_LATITUDE,
                    longitude=self.PLAYER_LONGITUDE,
                    accuracy_meters=10.0,
                )

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Командные миссии из вашей страны ограничены.", ctx.exception.detail)