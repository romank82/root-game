"""Sprint 8.9.d: сквозной integration-тест античита (accept -> proof).

Имитация подмены GPS: игрок берёт миссию (accept генерирует spawn), затем
spawn.generated_at «перематывается» на 10 секунд назад и отправляется
location-proof из точки в ~1.276 км от spawn. Скорость ~459 км/ч > порога
120 км/ч -> PlayerEvent("anticheat.flag") + immutable AdminAuditLog
("anticheat.flag", actor=None) + progress["anticheat"]["status"]="review".

Почему отдельный файл (а не test_solo_location_proof.py): solo-файл —
unit-style БЕЗ accept (PlayerMission там сеется напрямую), а 8.9.d проверяет
именно сквозной флоу accept -> spawn -> proof. Для accept нужна GeoZone с
search_radius_meters (без него accept -> 422), то есть расширение фикстуры
solo-файла, которое затронуло бы его 15 существующих тестов.

Детерминизм:
* generate_spawn_point случайный -> подменяем module-level функцию на
  фиксированный SpawnPoint (mission_engine импортирует её на уровне модуля,
  поэтому patch.object(mission_engine, "generate_spawn_point") работает).
* elapsed меряем диапазоном (9..12), а не точным значением 10.
* verified на 55.76/37.62 НЕ ассертим как True: is_inside_zone считает
  equirectangular без cos(latitude), точка в ~556 м > radius_meters=500.

Реальная Alembic-SQLite БД в tempdir по образцу test_solo_location_proof.py.
Подменяется атрибут модуля ``app.mission_engine.SessionLocal`` (entrypoint
использует module-level имя), а не ``app.db.SessionLocal``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AnticheatIntegrationTests(unittest.TestCase):
    """Sprint 8.9.d: accept (spawn) -> proof -> anticheat flag."""

    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173
    # spawn по умолчанию — та же точка, что в 8.9.b-тестах solo-файла:
    # spawn 55.75/37.61 -> proof 55.76/37.62 = 1.276 км за 10 с = 459.3 км/ч.
    SPAWN_LATITUDE = 55.75
    SPAWN_LONGITUDE = 37.61

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-anticheat-integration-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "anticheat-integration.sqlite3"
        )
        database_url = f"sqlite:///{cls.database_path}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url

        subprocess.run(
            [
                sys.executable, "-m", "alembic",
                "-c", str(BACKEND_ROOT / "alembic.ini"),
                "upgrade", "head",
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
        def enable_sqlite_foreign_keys(dbapi_connection, _):
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
        # module-level SessionLocal в mission_engine (не app.db).
        cls._session_local_patch = patch.object(
            mission_engine, "SessionLocal", cls.SessionLocal,
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures -------------------------------------------------------
    def _fixture(self) -> dict[str, str]:
        """Season -> GeoZone -> Mission (published) + GamePlayer.

        PlayerMission НЕ сеется: accept создаёт её через
        _synchronize_player_missions и сразу переводит в in_progress.
        """
        from app.models import GamePlayer, GeoZone, Mission, Season

        suffix = uuid.uuid4().hex
        season_id = f"season-{suffix}"
        zone_id = f"geo-zone-{suffix}"
        zone_slug = f"zone-{suffix}"
        mission_id = f"mission-{suffix}"
        player_id = f"player-{suffix}"

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=season_id,
                    slug=f"season-{suffix}",
                    title="Anti-cheat season",
                    description="Isolated 8.9.d fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                GeoZone(
                    id=zone_id,
                    slug=zone_slug,
                    title="Anti-cheat zone",
                    description="Isolated 8.9.d fixture",
                    zone_type="radius",
                    status="published",
                    sort_order=1,
                    latitude=self.PLAYER_LATITUDE,
                    longitude=self.PLAYER_LONGITUDE,
                    radius_meters=500,
                    # search_radius_meters обязателен для accept (иначе 422).
                    search_radius_meters=1500,
                    location_constraints={},
                    timezone="UTC",
                    max_location_accuracy_meters=None,
                    minimum_presence_seconds=0,
                )
            )
            session.flush()
            session.add(
                Mission(
                    id=mission_id,
                    season_id=season_id,
                    slug=f"mission-{suffix}",
                    mission_type="text_answer",
                    mission_category="solo",
                    title="Anti-cheat mission",
                    description="Isolated 8.9.d fixture",
                    content={"schemaVersion": 1},
                    validation_config={},
                    status="published",
                    sort_order=1,
                    geo_zone_id=zone_id,
                )
            )
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=f"Player-{suffix[:6]}",
                    auth_provider="test",
                    external_id=f"ac-{uuid.uuid4().hex}",
                    status="active",
                )
            )

        return {
            "player": player_id,
            "zone_id": zone_id,
            "zone_slug": zone_slug,
            "mission": mission_id,
        }

    # ---- Helpers --------------------------------------------------------
    def _accept(
        self,
        player_id: str,
        mission_id: str,
        *,
        latitude: float | None = None,
        longitude: float | None = None,
        spawn_latitude: float | None = None,
        spawn_longitude: float | None = None,
    ) -> dict:
        """accept_mission с детерминированным spawn (generate_spawn_point патч)."""
        from app.geo_spawn import SpawnPoint

        spawn_point = SpawnPoint(
            latitude=(
                self.SPAWN_LATITUDE if spawn_latitude is None else spawn_latitude
            ),
            longitude=(
                self.SPAWN_LONGITUDE if spawn_longitude is None else spawn_longitude
            ),
            distance_from_center_m=0.0,
        )
        with patch.object(
            self.mission_engine,
            "generate_spawn_point",
            return_value=spawn_point,
        ):
            return self.mission_engine.accept_mission(
                player_id=player_id,
                mission_id=mission_id,
                latitude=(
                    self.PLAYER_LATITUDE if latitude is None else latitude
                ),
                longitude=(
                    self.PLAYER_LONGITUDE if longitude is None else longitude
                ),
                accuracy=10.0,
            )

    def _rewind_spawn(
        self,
        player_id: str,
        mission_id: str,
        *,
        seconds_ago: int = 10,
    ) -> None:
        """«Перемотать» progress["spawn"]["generated_at"] на seconds_ago назад.

        Меняем ТОЛЬКО время: координаты spawn остаются теми, что записал accept.
        """
        from app.models import PlayerMission

        generated_at = (
            datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
        ).isoformat()
        with self.SessionLocal.begin() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == player_id,
                    PlayerMission.mission_id == mission_id,
                )
            )
            self.assertIsNotNone(player_mission)
            progress = dict(player_mission.progress or {})
            spawn = dict(progress.get("spawn") or {})
            self.assertTrue(spawn, "accept должен записать progress['spawn']")
            spawn["generated_at"] = generated_at
            progress["spawn"] = spawn
            player_mission.progress = progress

    def _player_mission(self, player_id: str, mission_id: str):
        from app.models import PlayerMission

        with self.SessionLocal() as session:
            return session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == player_id,
                    PlayerMission.mission_id == mission_id,
                )
            )

    def _anticheat_events(self, player_id: str) -> list:
        """Только anticheat.flag: accept пишет ещё mission.accepted."""
        from app.models import PlayerEvent

        with self.SessionLocal() as session:
            return list(
                session.scalars(
                    select(PlayerEvent).where(
                        PlayerEvent.player_id == player_id,
                        PlayerEvent.event_type == "anticheat.flag",
                    )
                ).all()
            )

    def _anticheat_audits(self, player_mission_id: str) -> list:
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return list(
                session.scalars(
                    select(AdminAuditLog).where(
                        AdminAuditLog.action == "anticheat.flag",
                        AdminAuditLog.entity_type == "player_mission",
                        AdminAuditLog.entity_id == player_mission_id,
                    )
                ).all()
            )

    def _call_proof(
        self,
        player_id: str,
        mission_id: str,
        latitude: float,
        longitude: float,
        accuracy: float = 10.0,
    ) -> dict:
        return self.mission_engine.submit_solo_location_proof_entrypoint(
            player_id,
            mission_id,
            latitude,
            longitude,
            accuracy,
        )

    # ---- 8.9.d: сценарии ------------------------------------------------
    def test_accept_then_teleport_proof_flags_velocity(self) -> None:
        """accept (spawn) -> перемотка -10 с -> proof далеко -> velocity-флаг."""
        ids = self._fixture()
        accepted = self._accept(
            ids["player"],
            ids["mission"],
            spawn_latitude=self.SPAWN_LATITUDE,
            spawn_longitude=self.SPAWN_LONGITUDE,
        )

        # accept-контракт: spawn создан сервером из GeoZone-шаблона.
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["spawn"]["latitude"], self.SPAWN_LATITUDE)
        self.assertEqual(accepted["spawn"]["longitude"], self.SPAWN_LONGITUDE)
        self.assertEqual(accepted["spawn"]["searchRadiusMeters"], 1500)
        self.assertEqual(accepted["spawn"]["zoneRadiusMeters"], 500)
        self.assertIsNotNone(accepted["spawn"]["generatedAt"])

        self._rewind_spawn(ids["player"], ids["mission"], seconds_ago=10)

        # spawn 55.75/37.61 -> proof 55.76/37.62 = 1.276 км за ~10 с.
        result = self._call_proof(
            ids["player"], ids["mission"], 55.76, 37.62, 10.0,
        )
        # 556 м от центра зоны > radius_meters=500 (equirectangular без cos).
        self.assertIs(result["verified"], False)
        self.assertEqual(result["zoneId"], ids["zone_slug"])

        events = self._anticheat_events(ids["player"])
        self.assertEqual(len(events), 1)
        event = events[0]
        payload = event.payload_json or {}
        self.assertEqual(payload["mode"], "flag")
        self.assertEqual(payload["playerId"], ids["player"])
        self.assertEqual(payload["missionId"], ids["mission"])
        self.assertEqual(payload["zoneId"], ids["zone_slug"])
        signals = payload["signals"]
        self.assertEqual([signal["signal"] for signal in signals], ["velocity"])
        self.assertEqual(signals[0]["thresholdKmh"], 120)
        self.assertGreater(signals[0]["speedKmh"], 120)
        self.assertAlmostEqual(signals[0]["distanceKm"], 1.276, places=2)
        self.assertGreaterEqual(signals[0]["elapsedSeconds"], 9)
        self.assertLessEqual(signals[0]["elapsedSeconds"], 12)
        self.assertIsNone(event.correlation_id)

        player_mission = self._player_mission(ids["player"], ids["mission"])
        self.assertIsNotNone(player_mission)

        audits = self._anticheat_audits(player_mission.id)
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertIsNone(audit.admin_user_id)
        self.assertIsNone(audit.admin_username_snapshot)
        self.assertTrue(audit.correlation_id)
        self.assertTrue(audit.correlation_id.startswith("cli:"))
        self.assertEqual(audit.outcome, "success")
        self.assertIsNone(audit.reason)
        self.assertEqual(
            [signal["signal"] for signal in audit.metadata_json["signals"]],
            ["velocity"],
        )

        anticheat = (player_mission.progress or {})["anticheat"]
        self.assertEqual(anticheat["status"], "review")
        self.assertEqual(anticheat["signals"][0]["signal"], "velocity")

        # Контракт безопасности: сырых координат в логе/аудите нет.
        for serialized in (json.dumps(payload), json.dumps(audit.metadata_json)):
            self.assertNotIn('"latitude"', serialized)
            self.assertNotIn('"longitude"', serialized)
            self.assertNotIn('"generated_from_lat"', serialized)
            self.assertNotIn('"generated_from_lng"', serialized)

    # ---- 8.9.d-2: proof в зоне (без телепорта) --------------------------
    def test_proof_inside_zone_no_flag(self) -> None:
        """Та же точка, что spawn — distance=0, accuracy=10 > 3: нет флагов."""
        ids = self._fixture()
        self._accept(
            ids["player"],
            ids["mission"],
            spawn_latitude=self.PLAYER_LATITUDE,
            spawn_longitude=self.PLAYER_LONGITUDE,
        )
        self._rewind_spawn(ids["player"], ids["mission"], seconds_ago=10)

        result = self._call_proof(
            ids["player"], ids["mission"],
            self.PLAYER_LATITUDE, self.PLAYER_LONGITUDE, 10.0,
        )
        self.assertIs(result["verified"], True)

        self.assertEqual(self._anticheat_events(ids["player"]), [])
        player_mission = self._player_mission(ids["player"], ids["mission"])
        self.assertIsNotNone(player_mission)
        self.assertNotIn("anticheat", player_mission.progress or {})
        self.assertEqual(self._anticheat_audits(player_mission.id), [])

    # ---- 8.9.d-3: accuracy anomaly --------------------------------------
    def test_accuracy_anomaly_after_accept_flags(self) -> None:
        """accuracy 1 м <= ANTICHEAT_ACCURACY_MIN_METERS (3): accuracy-флаг."""
        ids = self._fixture()
        self._accept(
            ids["player"],
            ids["mission"],
            spawn_latitude=self.PLAYER_LATITUDE,
            spawn_longitude=self.PLAYER_LONGITUDE,
        )
        self._rewind_spawn(ids["player"], ids["mission"], seconds_ago=10)

        result = self._call_proof(
            ids["player"], ids["mission"],
            self.PLAYER_LATITUDE, self.PLAYER_LONGITUDE, 1.0,
        )
        self.assertIs(result["verified"], True)

        events = self._anticheat_events(ids["player"])
        self.assertEqual(len(events), 1)
        signals = events[0].payload_json["signals"]
        self.assertEqual([signal["signal"] for signal in signals], ["accuracy"])
        self.assertEqual(signals[0]["accuracyMeters"], 1.0)
        self.assertEqual(signals[0]["thresholdMeters"], 3)

        player_mission = self._player_mission(ids["player"], ids["mission"])
        self.assertIsNotNone(player_mission)
        audits = self._anticheat_audits(player_mission.id)
        self.assertEqual(len(audits), 1)
        anticheat = (player_mission.progress or {})["anticheat"]
        self.assertEqual(anticheat["status"], "review")
        self.assertEqual(
            [signal["signal"] for signal in anticheat["signals"]],
            ["accuracy"],
        )


if __name__ == "__main__":
    unittest.main()
