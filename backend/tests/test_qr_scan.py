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

from app.mission_engine import MissionEngineError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class QrScanTests(unittest.TestCase):
    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-qr-scan-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "qr-scan.sqlite3"
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
        cls._session_local_patch = patch.object(
            mission_engine, "SessionLocal", cls.SessionLocal,
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _fixture(self, *, mission_status: str = "published") -> dict[str, str]:
        from app.models import (
            ARObject, Chapter, GamePlayer, GeoZone, Mission, Season,
        )

        suffix = uuid.uuid4().hex
        ids = {
            "player": f"player-{suffix}",
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "zone": f"zone-{suffix}",
            "ar_object": f"ar-object-{suffix}",
            "mission": f"mission-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            session.add(Season(
                id=ids["season"], slug=f"season-{suffix}",
                title="Test", status="published", sort_order=1,
            ))
            session.flush()
            session.add_all([
                Chapter(
                    id=ids["chapter"], season_id=ids["season"],
                    slug=f"chapter-{suffix}", title="Test",
                    status="published", sort_order=1,
                ),
                GamePlayer(
                    id=ids["player"], display_name="Test",
                    auth_provider="telegram",
                    external_id=f"tg-{suffix}",
                    status="active",
                ),
            ])
            session.flush()
            session.add(GeoZone(
                id=ids["zone"], slug=f"zone-{suffix}", title="Test",
                zone_type="radius", status="published", sort_order=1,
                radius_meters=50, search_radius_meters=3000,
                location_constraints={}, timezone="UTC",
            ))
            session.flush()
            session.add(ARObject(
                id=ids["ar_object"], slug=f"ar-{suffix}", title="Test",
                status="published", sort_order=1, geo_zone_id=ids["zone"],
                object_type="cube",
                asset_uri=f"https://example.test/{suffix}.glb",
                scale_meters=1.0, orientation="free",
                discovery_scenario={}, minigame_config={},
                validation_config={},
            ))
            session.flush()
            session.add(Mission(
                id=ids["mission"], chapter_id=ids["chapter"],
                slug=f"mission-{suffix}", mission_type="text_answer",
                mission_category="solo", title="Test",
                content={"schemaVersion": 1},
                validation_config={"validator": "normalized_text_match", "acceptedAnswers": ["x"]},
                status=mission_status, sort_order=1,
                geo_zone_id=ids["zone"], ar_object_id=ids["ar_object"],
            ))

        return ids

    def _accept(self, ids: dict[str, str]) -> None:
        self.mission_engine.accept_mission(
            ids["player"], ids["mission"],
            self.PLAYER_LATITUDE, self.PLAYER_LONGITUDE,
        )

    def _build_payload(self, ids: dict[str, str]) -> str:
        from app.qr_service import generate_qr_payload
        gen = generate_qr_payload(
            player_id=ids["player"], mission_id=ids["mission"],
        )
        return f"{gen['payload']}.{gen['hmac']}"

    def test_scan_success(self) -> None:
        ids = self._fixture()
        self._accept(ids)
        raw = self._build_payload(ids)

        result = self.mission_engine.process_qr_scan(
            ids["player"], ids["mission"], raw,
        )

        self.assertIs(result["accepted"], True)
        self.assertEqual(result["missionId"], ids["mission"])
        self.assertIsInstance(result["scannedAt"], str)
        self.assertEqual(result["miniGame"]["missionType"], "text_answer")
        self.assertIn("content", result["miniGame"])

    def test_scan_persists_progress_fields(self) -> None:
        from app.models import PlayerMission
        from sqlalchemy import select

        ids = self._fixture()
        self._accept(ids)
        raw = self._build_payload(ids)

        self.mission_engine.process_qr_scan(ids["player"], ids["mission"], raw)

        with self.SessionLocal() as session:
            pm = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["mission"],
                )
            ).first()
            progress = pm.progress or {}
            self.assertIn("lastScanAt", progress)
            self.assertIn("lastScanNonce", progress)

    def test_scan_rejects_bad_format(self) -> None:
        ids = self._fixture()
        self._accept(ids)

        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.process_qr_scan(
                ids["player"], ids["mission"], "no-dot-here",
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_scan_rejects_tampered_hmac(self) -> None:
        ids = self._fixture()
        self._accept(ids)
        raw = self._build_payload(ids)
        tampered = raw[:-4] + "AAAA"

        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.process_qr_scan(
                ids["player"], ids["mission"], tampered,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_scan_rejects_other_player(self) -> None:
        ids = self._fixture()
        self._accept(ids)

        # Payload для другого игрока.
        from app.qr_service import generate_qr_payload
        other = generate_qr_payload(
            player_id="other-player", mission_id=ids["mission"],
        )
        raw = f"{other['payload']}.{other['hmac']}"

        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.process_qr_scan(
                ids["player"], ids["mission"], raw,
            )
        self.assertEqual(ctx.exception.status_code, 422)

    def test_scan_rejects_non_in_progress(self) -> None:
        ids = self._fixture()
        # Не делаем accept — PlayerMission в статусе 'available' или отсутствует.
        # Сначала вызовем bootstrap-подобную синхронизацию через accept? Нет,
        # accept переведёт в in_progress. Значит миссия 'locked'/'available'.

        # Загружаем PlayerMission напрямую, чтобы создать без accept.
        from app.models import PlayerMission
        with self.SessionLocal.begin() as session:
            session.add(PlayerMission(
                id=f"pm-{uuid.uuid4().hex}",
                player_id=ids["player"], mission_id=ids["mission"],
                status="available", attempt_count=0, progress={},
            ))

        raw = self._build_payload(ids)
        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.process_qr_scan(
                ids["player"], ids["mission"], raw,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_scan_rejects_when_mission_not_found(self) -> None:
        with self.assertRaises(MissionEngineError) as ctx:
            self.mission_engine.process_qr_scan(
                "no-player", "no-mission", "aaa.bbb",
            )
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()