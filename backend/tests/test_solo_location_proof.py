"""Sprint 8.5-4: тесты solo location-proof.

Покрывает ``submit_solo_location_proof_entrypoint`` (POST
/api/v1/engine/missions/{id}/location-proof) и общий примитив
``has_fresh_verified_proof``.

Unit-style (как test_qr_scan.py / test_mission_engine_accept.py): реальная
Alembic-SQLite БД в tempdir, БЕЗ accept_mission — PlayerMission сеется напрямую.

ВАЖНО: подменяется атрибут модуля ``app.mission_engine.SessionLocal``, а не
``app.db.SessionLocal``: entrypoint использует module-level имя, поэтому подмена
``app.db`` не перехватила бы вызов и тест писал бы в dev-БД.
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

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class SoloLocationProofTests(unittest.TestCase):
    """Sprint 8.5-2/8.5-4: solo location proof + has_fresh_verified_proof."""

    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-solo-location-proof-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "solo-location-proof.sqlite3"
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
    def _seed_player(self) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=f"Player-{player_id[-6:]}",
                    auth_provider="telegram",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _seed_geo_zone(
        self,
        *,
        max_accuracy: int | None = None,
        latitude: float = 55.7558,
        longitude: float = 37.6173,
        radius_meters: int = 500,
        status: str = "published",
    ) -> tuple[str, str]:
        """Создать зону. Возвращает (zone_id, zone_slug) — оба нужны:
        Mission.geo_zone_id ссылается на id, а LocationProof.zone_id — на slug.
        """
        from app.models import GeoZone

        suffix = uuid.uuid4().hex
        zone_id = f"geo-zone-{suffix}"
        zone_slug = f"zone-{suffix}"
        with self.SessionLocal.begin() as session:
            session.add(
                GeoZone(
                    id=zone_id,
                    slug=zone_slug,
                    title="Solo proof test zone",
                    description="Isolated solo location-proof fixture",
                    zone_type="radius",
                    status=status,
                    sort_order=0,
                    latitude=latitude,
                    longitude=longitude,
                    radius_meters=radius_meters,
                    polygon_coordinates=None,
                    timezone="UTC",
                    starts_at=None,
                    ends_at=None,
                    max_location_accuracy_meters=max_accuracy,
                    minimum_presence_seconds=0,
                )
            )
        return zone_id, zone_slug

    def _seed_mission(
        self,
        zone_id: str | None,
        *,
        mission_type: str = "text_answer",
        mission_category: str = "solo",
        status: str = "published",
    ) -> str:
        from app.models import Mission, Season

        suffix = uuid.uuid4().hex
        season_id = f"season-{suffix}"
        mission_id = f"mission-{suffix}"
        with self.SessionLocal.begin() as session:
            session.add(
                Season(id=season_id, slug=f"season-{suffix}", title="Season")
            )
            session.flush()
            session.add(
                Mission(
                    id=mission_id,
                    season_id=season_id,
                    slug=f"mission-{suffix}",
                    mission_type=mission_type,
                    mission_category=mission_category,
                    title="Solo location-proof mission",
                    description="Isolated solo location-proof fixture",
                    content={"schemaVersion": 1},
                    validation_config={},
                    status=status,
                    sort_order=0,
                    geo_zone_id=zone_id,
                )
            )
        return mission_id

    def _seed_player_mission(
        self,
        player_id: str,
        mission_id: str,
        *,
        status: str = "in_progress",
    ) -> None:
        from app.models import PlayerMission

        with self.SessionLocal.begin() as session:
            session.add(
                PlayerMission(
                    id=f"player-mission-{uuid.uuid4().hex}",
                    player_id=player_id,
                    mission_id=mission_id,
                    status=status,
                    progress={},
                )
            )

    def _fixture(
        self,
        *,
        max_accuracy: int | None = None,
        pm_status: str = "in_progress",
        mission_type: str = "text_answer",
        mission_category: str = "solo",
        mission_status: str = "published",
        zone_status: str = "published",
        with_zone: bool = True,
        with_mission: bool = True,
        with_player_mission: bool = True,
    ) -> dict[str, str]:
        player_id = self._seed_player()
        zone_id = ""
        zone_slug = ""
        if with_zone:
            zone_id, zone_slug = self._seed_geo_zone(
                max_accuracy=max_accuracy,
                status=zone_status,
            )
        mission_id = ""
        if with_mission:
            mission_id = self._seed_mission(
                zone_id or None,
                mission_type=mission_type,
                mission_category=mission_category,
                status=mission_status,
            )
        if with_player_mission and mission_id:
            self._seed_player_mission(player_id, mission_id, status=pm_status)
        return {
            "player": player_id,
            "zone_id": zone_id,
            "zone_slug": zone_slug,
            "mission": mission_id,
        }

    def _call(
        self,
        ids: dict[str, str],
        *,
        lat: float | None = None,
        lon: float | None = None,
        accuracy: float = 10.0,
    ) -> dict:
        return self.mission_engine.submit_solo_location_proof_entrypoint(
            ids["player"],
            ids["mission"],
            self.PLAYER_LATITUDE if lat is None else lat,
            self.PLAYER_LONGITUDE if lon is None else lon,
            accuracy,
        )

    def _proof_count(self, player_id: str) -> int:
        from app.geo_team_runtime_models import LocationProof

        with self.SessionLocal() as session:
            return int(
                session.scalar(
                    select(func.count())
                    .select_from(LocationProof)
                    .where(LocationProof.player_id == player_id)
                )
                or 0
            )

    def _latest_proof(self, player_id: str) -> dict | None:
        from app.geo_team_runtime_models import LocationProof

        with self.SessionLocal() as session:
            proof = session.scalar(
                select(LocationProof)
                .where(LocationProof.player_id == player_id)
                .order_by(LocationProof.issued_at.desc())
                .limit(1)
            )
            if proof is None:
                return None
            return {
                "status": proof.status,
                "provider": proof.provider,
                "verifier_reference": proof.verifier_reference,
                "zone_id": proof.zone_id,
                "expires_at": proof.expires_at,
            }

    # ---- 8.9.b: anticheat helpers ---------------------------------------
    def _seed_spawn(
        self,
        ids: dict[str, str],
        *,
        latitude: float = 55.75,
        longitude: float = 37.61,
        seconds_ago: int = 10,
    ) -> None:
        """Записать progress["spawn"] так же, как это делает accept (8.2)."""
        from app.models import PlayerMission

        generated_at = (
            datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
        ).isoformat()
        with self.SessionLocal.begin() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            )
            self.assertIsNotNone(player_mission)
            progress = dict(player_mission.progress or {})
            progress["spawn"] = {
                "latitude": latitude,
                "longitude": longitude,
                "search_radius_m": 3000,
                "zone_radius_m": 500,
                "ar_object_id": None,
                "generated_at": generated_at,
                "generated_from_lat": latitude,
                "generated_from_lng": longitude,
            }
            player_mission.progress = progress

    def _player_mission(self, ids: dict[str, str]):
        from app.models import PlayerMission

        with self.SessionLocal() as session:
            return session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            )

    def _anticheat_events(self, player_id: str) -> list:
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

    # ---- T1-T6: основные сценарии ---------------------------------------
    def test_verified_inside_zone_creates_verified_proof(self) -> None:
        ids = self._fixture()
        result = self._call(ids)

        self.assertIs(result["verified"], True)
        self.assertEqual(result["missionId"], ids["mission"])
        self.assertEqual(result["zoneId"], ids["zone_slug"])
        self.assertIsNotNone(result["expiresAt"])

        proof = self._latest_proof(ids["player"]) or {}
        self.assertEqual(proof.get("status"), "verified")
        self.assertEqual(proof.get("provider"), "dev_mock")
        self.assertIsNone(proof.get("verifier_reference"))
        self.assertEqual(proof.get("zone_id"), ids["zone_slug"])
        self.assertIsNotNone(proof.get("expires_at"))

    def test_accuracy_worse_than_limit_is_rejected(self) -> None:
        ids = self._fixture(max_accuracy=10)
        result = self._call(ids, accuracy=50.0)

        self.assertIs(result["verified"], False)
        proof = self._latest_proof(ids["player"]) or {}
        self.assertEqual(proof.get("status"), "rejected")

    def test_outside_zone_is_rejected(self) -> None:
        ids = self._fixture()  # radius 500 m
        result = self._call(ids, lat=self.PLAYER_LATITUDE + 0.1)

        self.assertIs(result["verified"], False)
        proof = self._latest_proof(ids["player"]) or {}
        self.assertEqual(proof.get("status"), "rejected")

    def test_accuracy_limit_not_set_is_ignored(self) -> None:
        ids = self._fixture(max_accuracy=None)
        result = self._call(ids, accuracy=5000.0)

        self.assertIs(result["verified"], True)

    def test_not_in_progress_returns_409(self) -> None:
        ids = self._fixture(pm_status="available")

        with self.assertRaises(MissionEngineError) as captured:
            self._call(ids)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail, "Миссия не в процессе выполнения."
        )
        self.assertEqual(self._proof_count(ids["player"]), 0)

    def test_missing_mission_or_player_returns_404(self) -> None:
        # (a) нет PlayerMission -> 404
        no_pm = self._fixture(with_player_mission=False)
        with self.assertRaises(MissionEngineError) as captured_a:
            self._call(no_pm)
        self.assertEqual(captured_a.exception.status_code, 404)
        self.assertEqual(
            captured_a.exception.detail, "Прогресс миссии не найден."
        )

        # (b) нет Mission -> 404
        no_mission = self._fixture(with_mission=False)
        with self.assertRaises(MissionEngineError) as captured_b:
            self._call(no_mission)
        self.assertEqual(captured_b.exception.status_code, 404)
        self.assertEqual(
            captured_b.exception.detail, "Миссия не найдена или не опубликована."
        )

        # (c) командная миссия -> 409
        team = self._fixture(mission_type="team", mission_category="team")
        with self.assertRaises(MissionEngineError) as captured_c:
            self._call(team)
        self.assertEqual(captured_c.exception.status_code, 409)

        # (d) у миссии нет геозоны -> 422
        no_zone = self._fixture(with_zone=False)
        with self.assertRaises(MissionEngineError) as captured_d:
            self._call(no_zone)
        self.assertEqual(captured_d.exception.status_code, 422)
        self.assertEqual(
            captured_d.exception.detail, "У миссии не настроена геозона."
        )

        # (e) геозона не published -> 409
        draft_zone = self._fixture(zone_status="draft")
        with self.assertRaises(MissionEngineError) as captured_e:
            self._call(draft_zone)
        self.assertEqual(captured_e.exception.status_code, 409)
        self.assertEqual(captured_e.exception.detail, "Геозона недоступна.")

        for player_id in (
            no_pm["player"],
            no_mission["player"],
            team["player"],
            no_zone["player"],
            draft_zone["player"],
        ):
            self.assertEqual(self._proof_count(player_id), 0)

    # ---- B1-B2: бонусы ---------------------------------------------------
    def test_has_fresh_verified_proof_finds_slug_zone(self) -> None:
        from app.geo_location_proof import has_fresh_verified_proof

        ids = self._fixture()
        self._call(ids)

        with self.SessionLocal() as session:
            self.assertIs(
                has_fresh_verified_proof(
                    session,
                    player_id=ids["player"],
                    zone_id=ids["zone_slug"],
                ),
                True,
            )
            # zone_id — PK зоны, а не slug: solo пишет slug, поэтому по PK
            # proof не находится (единое пространство значений с team).
            self.assertIs(
                has_fresh_verified_proof(
                    session,
                    player_id=ids["player"],
                    zone_id=ids["zone_id"],
                ),
                False,
            )

    def test_raw_coordinates_not_persisted(self) -> None:
        from app.geo_team_runtime_models import LocationProof
        from app.models import PlayerMission

        column_names = {
            column.name for column in LocationProof.__table__.columns
        }
        self.assertNotIn("latitude", column_names)
        self.assertNotIn("longitude", column_names)

        ids = self._fixture()
        self._call(ids)

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            )
            self.assertIsNotNone(player_mission)
            progress = (player_mission.progress if player_mission else {}) or {}
            # Sprint 8.9.b: в progress разрешён только безопасный раздел
            # anticheat (review-состояние). Сырых координат быть не должно.
            self.assertLessEqual(set(progress), {"anticheat"})
            for forbidden in (
                "latitude",
                "longitude",
                "generated_from_lat",
                "generated_from_lng",
            ):
                self.assertNotIn(forbidden, progress)
            serialized = json.dumps(progress)
            for forbidden in (
                '"latitude"',
                '"longitude"',
                '"generated_from_lat"',
                '"generated_from_lng"',
            ):
                self.assertNotIn(forbidden, serialized)

    # ---- 8.9.b: anti-cheat flags (velocity/accuracy) ---------------------
    def test_velocity_teleport_creates_flag(self) -> None:
        ids = self._fixture()
        self._seed_spawn(ids)
        # spawn 55.75/37.61 -> current 55.76/37.62 за ~10 с = телепорт.
        self._call(ids, lat=55.76, lon=37.62, accuracy=10.0)

        events = self._anticheat_events(ids["player"])
        self.assertEqual(len(events), 1)
        signals = events[0].payload_json["signals"]
        self.assertEqual(signals[0]["signal"], "velocity")
        self.assertGreater(signals[0]["speedKmh"], 120)

        player_mission = self._player_mission(ids)
        self.assertIsNotNone(player_mission)
        anticheat = (player_mission.progress or {})["anticheat"]
        self.assertEqual(anticheat["status"], "review")
        self.assertEqual(anticheat["signals"][0]["signal"], "velocity")

        audits = self._anticheat_audits(player_mission.id)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].action, "anticheat.flag")
        self.assertIsNone(audits[0].admin_user_id)

    def test_no_spawn_no_velocity_flag(self) -> None:
        ids = self._fixture()  # progress={}, spawn отсутствует
        self._call(ids, accuracy=10.0)  # accuracy 10 > порога 3

        self.assertEqual(self._anticheat_events(ids["player"]), [])
        player_mission = self._player_mission(ids)
        self.assertNotIn("anticheat", player_mission.progress or {})
        self.assertEqual(self._anticheat_audits(player_mission.id), [])

    def test_accuracy_anomaly_creates_flag(self) -> None:
        ids = self._fixture()
        self._call(ids, accuracy=1.0)  # <= ANTICHEAT_ACCURACY_MIN_METERS

        events = self._anticheat_events(ids["player"])
        self.assertEqual(len(events), 1)
        self.assertEqual(
            [s["signal"] for s in events[0].payload_json["signals"]],
            ["accuracy"],
        )
        player_mission = self._player_mission(ids)
        self.assertEqual(
            (player_mission.progress or {})["anticheat"]["status"], "review"
        )
        self.assertEqual(len(self._anticheat_audits(player_mission.id)), 1)

    def test_mode_off_writes_nothing(self) -> None:
        from app.models import SystemSetting

        ids = self._fixture()
        self._seed_spawn(ids)
        # Sprint 8.9.e-4: режим читается из CMS (geo.anticheat_mode), а не из
        # константы модуля — временно пишем "off", затем возвращаем "flag".
        with self.SessionLocal.begin() as session:
            setting = session.get(SystemSetting, "geo.anticheat_mode")
            self.assertIsNotNone(setting)
            setting.value_json = "off"

        try:
            self._call(ids, lat=55.76, lon=37.62, accuracy=10.0)
            self.assertEqual(self._anticheat_events(ids["player"]), [])
            player_mission = self._player_mission(ids)
            self.assertNotIn("anticheat", player_mission.progress or {})
            self.assertEqual(self._anticheat_audits(player_mission.id), [])
        finally:
            with self.SessionLocal.begin() as session:
                setting = session.get(SystemSetting, "geo.anticheat_mode")
                if setting is not None:
                    setting.value_json = "flag"

    def test_payload_no_raw_coordinates(self) -> None:
        ids = self._fixture()
        self._seed_spawn(ids)
        self._call(ids, lat=55.76, lon=37.62, accuracy=10.0)

        events = self._anticheat_events(ids["player"])
        player_mission = self._player_mission(ids)
        audits = self._anticheat_audits(player_mission.id)
        self.assertEqual(len(events), 1)
        self.assertEqual(len(audits), 1)

        serialized_event = json.dumps(events[0].payload_json)
        serialized_audit = json.dumps(audits[0].metadata_json)
        for forbidden in (
            '"latitude"',
            '"longitude"',
            '"generated_from_lat"',
            '"generated_from_lng"',
        ):
            self.assertNotIn(forbidden, serialized_event)
            self.assertNotIn(forbidden, serialized_audit)
        self.assertIn('"speedKmh"', serialized_event)

    def test_audit_actor_none_and_correlation(self) -> None:
        ids = self._fixture()
        self._seed_spawn(ids)
        # request не передаётся -> request=None -> cli-correlation.
        self._call(ids, lat=55.76, lon=37.62, accuracy=10.0)

        player_mission = self._player_mission(ids)
        audits = self._anticheat_audits(player_mission.id)
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertIsNone(audit.admin_user_id)
        self.assertIsNone(audit.admin_username_snapshot)
        self.assertTrue(audit.correlation_id)
        self.assertTrue(audit.correlation_id.startswith("cli:"))
        self.assertEqual(audit.outcome, "success")
        self.assertIsNone(audit.reason)

    def _set_valid_answer(self, mission_id: str) -> None:
        from app.models import Mission

        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, mission_id)
            mission.validation_config = {
                "validator": "normalized_text_match",
                "acceptedAnswers": ["answer"],
            }

    # ---- 8.5-2b: гейт geo.solo_proof_mode в submit_mission ----------------
    def test_enforce_mode_requires_fresh_proof(self) -> None:
        from app.models import SystemSetting

        def write_mode(value: str, status: str = "active") -> None:
            with self.SessionLocal.begin() as session:
                row = session.get(SystemSetting, "geo.solo_proof_mode")
                if row is None:
                    session.add(
                        SystemSetting(
                            key="geo.solo_proof_mode",
                            value_json=value,
                            value_type="string",
                            category="geo",
                            title="Гейт solo location-proof",
                            description=(
                                "Sprint 8.5: solo location-proof gate (off|enforce)."
                            ),
                            is_sensitive=False,
                            status=status,
                        )
                    )
                else:
                    row.value_json = value
                    row.status = status

        # (1) нет записи -> default off -> гейт не мешает (accepted=True).
        ids = self._fixture()
        self._set_valid_answer(ids["mission"])
        result = self.mission_engine.submit_mission(
            ids["player"], ids["mission"], "answer", None,
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(self._proof_count(ids["player"]), 0)

        # (2) enforce + нет свежего proof -> 409, proof не создаётся.
        write_mode("enforce")
        ids = self._fixture()
        self._set_valid_answer(ids["mission"])
        with self.assertRaises(MissionEngineError) as captured:
            self.mission_engine.submit_mission(
                ids["player"], ids["mission"], "answer", None,
            )
        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Подтвердите присутствие в локации (location proof).",
        )
        self.assertEqual(self._proof_count(ids["player"]), 0)

        # (3) enforce + свежий verified proof (по slug) -> гейт проходит.
        self._call(ids)
        result = self.mission_engine.submit_mission(
            ids["player"], ids["mission"], "answer", None,
        )
        self.assertTrue(result["accepted"])

        # (4) off явно -> гейт не включается.
        write_mode("off")
        ids = self._fixture()
        self._set_valid_answer(ids["mission"])
        result = self.mission_engine.submit_mission(
            ids["player"], ids["mission"], "answer", None,
        )
        self.assertTrue(result["accepted"])

        # (5) статус не active -> гейт не включается (хелпер).
        write_mode("enforce", status="archived")
        with self.SessionLocal() as session:
            self.assertFalse(self.mission_engine._solo_proof_mode_enforced(session))

        # cleanup: удалить строку, чтобы не влиять на следующие тесты класса.
        with self.SessionLocal.begin() as session:
            row = session.get(SystemSetting, "geo.solo_proof_mode")
            if row is not None:
                session.delete(row)


if __name__ == "__main__":
    unittest.main()
