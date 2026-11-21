"""8.x-player-cancel: отказ игрока в льготном окне — НЕ поражение.

Проверяем три вещи, из-за которых карточка писала «ПРОВАЛЕНО» и сажала на
перерыв после добровольного отказа:

1. внутри окна (cancel_deadline_at > now) миссия получает 'abandoned',
   available_again_at НЕ ставится, попытка не тратится;
2. после окна поведение прежнее — 'expired' + cooldown;
3. 'abandoned' сразу возвращается в 'available' синхронизацией, поэтому
   игрок может взять миссию снова, и повторный отказ идемпотентен.

База — временный SQLite через alembic head, движок подменяется на тестовую
сессию (как в test_mission_engine_accept.py).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class MissionPlayerCancelTests(unittest.TestCase):
    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-cancel-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "cancel-tests.sqlite3"
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
            database_url, connect_args={"check_same_thread": False}
        )

        @event.listens_for(cls.engine, "connect")
        def _fk_on(dbapi_connection, _record) -> None:
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
        from unittest.mock import patch

        cls.mission_engine = mission_engine
        cls._patch = patch.object(
            mission_engine, "SessionLocal", cls.SessionLocal
        )
        cls._patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixture -------------------------------------------------------
    def _fixture(
        self,
        *,
        reentry_cooldown_seconds: int = 300,
        entry_root_atomic: int = 0,
        publish_policy: bool = True,
    ) -> dict[str, str]:
        from app.geo_team_runtime_models import MissionRuntimePolicy
        from app.models import ARObject, GamePlayer, GeoZone, Mission, Season

        suffix = uuid.uuid4().hex
        ids = {
            "player": f"player-{suffix}",
            "season": f"season-{suffix}",
            "zone": f"zone-{suffix}",
            "ar_object": f"ar-object-{suffix}",
            "mission": f"mission-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="Cancel test season",
                    description="Isolated cancel fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                GamePlayer(
                    id=ids["player"],
                    display_name=f"Cancel Player-{suffix[:6]}",
                    auth_provider="telegram",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
            session.flush()
            session.add(
                GeoZone(
                    id=ids["zone"],
                    slug=f"zone-{suffix}",
                    title="Cancel test zone",
                    description="Isolated cancel fixture",
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
                    title="Cancel test AR object",
                    description="Isolated cancel fixture",
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
                    instruction_text="Cancel test instruction",
                    validation_config={},
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
                    title="Cancel test mission",
                    description="Isolated cancel fixture",
                    content={"schemaVersion": 1},
                    validation_config={},
                    status="published",
                    sort_order=1,
                    geo_zone_id=ids["zone"],
                    ar_object_id=ids["ar_object"],
                    execution_time_limit_seconds=None,
                    reentry_cooldown_seconds=reentry_cooldown_seconds,
                )
            )
            session.flush()

            if publish_policy:
                session.add(
                    MissionRuntimePolicy(
                        id=f"policy-{suffix}",
                        mission_id=ids["mission"],
                        version=1,
                        status="published",
                        entry_root_atomic=entry_root_atomic,
                        max_attempts=3,
                        repeatability_policy="after_terminal",
                        required_items_json={"schemaVersion": 1, "items": []},
                        challenge_policy_json={},
                        reward_policy_json={},
                        fallback_policy_json=None,
                        feature_flags_json={},
                    )
                )

        return ids

    def _accept(self, ids: dict[str, str]) -> dict:
        return self.mission_engine.accept_mission(
            ids["player"],
            ids["mission"],
            self.PLAYER_LATITUDE,
            self.PLAYER_LONGITUDE,
        )

    def _read(self, ids: dict[str, str]):
        from app.models import PlayerMission

        with self.SessionLocal.begin() as session:
            return session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()

    def _shift_cancel_deadline(self, ids: dict[str, str], seconds: int) -> None:
        """Сдвинуть окно отмены в прошлое (имитация «окно закрылось»)."""
        from app.models import PlayerMission

        with self.SessionLocal.begin() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            pm.cancel_deadline_at = pm.cancel_deadline_at - timedelta(
                seconds=seconds
            )

    # ---- 1. Отказ внутри окна ------------------------------------------
    def test_cancel_inside_window_is_abandoned_without_cooldown(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=300)
        self._accept(ids)

        response = self.mission_engine.expire_mission(
            ids["player"], ids["mission"]
        )

        self.assertTrue(response["cancelled"])
        self.assertFalse(response["expired"])
        self.assertEqual(response["status"], "abandoned")
        # Главное: никакого перерыва за добровольный отказ.
        self.assertIsNone(response["availableAgainAt"])

        pm = self._read(ids)
        self.assertEqual(pm.status, "abandoned")
        self.assertIsNone(pm.available_again_at)
        # Отказ не тратит попытку.
        self.assertEqual(pm.attempt_count, 0)

    def test_cancel_inside_window_does_not_charge_attempt(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=0)
        self._accept(ids)

        before = self._read(ids).attempt_count
        self.mission_engine.expire_mission(ids["player"], ids["mission"])
        after = self._read(ids).attempt_count

        self.assertEqual(before, after, "отказ не должен сжигать попытку")

    # ---- 2. Отказ после окна — прежнее поведение -----------------------
    def test_cancel_after_window_is_expired_with_cooldown(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=300)
        self._accept(ids)
        # Окно отмены закрыто.
        self._shift_cancel_deadline(ids, seconds=600)

        response = self.mission_engine.expire_mission(
            ids["player"], ids["mission"]
        )

        self.assertTrue(response["expired"])
        self.assertFalse(response["cancelled"])
        self.assertEqual(response["status"], "expired")
        self.assertIsNotNone(response["availableAgainAt"])

    # ---- 3. Возврат в available ----------------------------------------
    def test_abandoned_returns_to_available_on_next_sync(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=300)
        self._accept(ids)
        self.mission_engine.expire_mission(ids["player"], ids["mission"])

        bootstrap = self.mission_engine.get_bootstrap(ids["player"])
        mission = next(
            m for m in bootstrap["missions"] if m["id"] == ids["mission"]
        )

        self.assertEqual(mission["status"], "available")
        self.assertIsNone(mission["availableAgainAt"])

    def test_abandoned_allows_taking_mission_again(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=300)
        self._accept(ids)
        self.mission_engine.expire_mission(ids["player"], ids["mission"])

        # Повторное взятие сразу, без ожидания перерыва.
        response = self._accept(ids)
        self.assertTrue(response["accepted"])
        self.assertEqual(response["status"], "in_progress")

    def test_abandoned_does_not_reset_attempt_count(self) -> None:
        """Дыра для накрутки: отказ не должен обнулять историю попыток."""
        from app.models import PlayerMission

        ids = self._fixture(reentry_cooldown_seconds=0)
        self._accept(ids)
        with self.SessionLocal.begin() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            pm.attempt_count = 2
        self.mission_engine.expire_mission(ids["player"], ids["mission"])
        self.mission_engine.get_bootstrap(ids["player"])

        pm = self._read(ids)
        self.assertEqual(pm.status, "available")
        self.assertEqual(pm.attempt_count, 2, "счётчик попыток не сбрасывается")

    # ---- 4. Идемпотентность --------------------------------------------
    def test_cancel_is_idempotent(self) -> None:
        ids = self._fixture(reentry_cooldown_seconds=300)
        self._accept(ids)

        first = self.mission_engine.expire_mission(
            ids["player"], ids["mission"]
        )
        second = self.mission_engine.expire_mission(
            ids["player"], ids["mission"]
        )

        self.assertTrue(first["cancelled"])
        self.assertTrue(second["cancelled"])
        self.assertEqual(second["status"], "abandoned")

    def test_expire_on_available_mission_still_rejected(self) -> None:
        ids = self._fixture()
        # Миссию не брали — отменять нечего.
        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.expire_mission(ids["player"], ids["mission"])
        self.assertIn(ctx.exception.status_code, (404, 409))


if __name__ == "__main__":
    unittest.main()
