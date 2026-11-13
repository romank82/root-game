"""Sprint 8.6.c: подписанный QR-payload миссии.

Два уровня проверки:

1. ``QrServiceUnitTests`` — чистая логика ``app.qr_service`` (HMAC,
   domain separation, свежесть, индивидуальность, ошибки конфигурации)
   без БД и без сети.
2. ``MissionQrPayloadEntrypointTests`` — доменный вход
   ``mission_engine.get_mission_qr_payload`` на изолированной SQLite
   (alembic upgrade head): QR выдаётся только владельцу миссии в
   ``in_progress``, чужой игрок payload не подтверждает, вход read-only
   (PlayerMission не создаётся, статусы не меняются).

Секрет в тестах подменяется через patch модуля: значение из .env не
используется и не печатается.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.config import settings as real_settings
from app.mission_engine import MissionEngineError
from app.qr_service import (
    QR_SCHEMA_VERSION,
    QR_TTL_SECONDS,
    generate_qr_payload,
    get_qr_ttl_seconds,
    verify_qr_payload,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Только для тестов: не совпадает с GAME_SESSION_SECRET из окружения.
TEST_SECRET = "unit-test-qr-secret-0123456789"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _payload_bytes(payload_b64: str) -> bytes:
    padding = "=" * (-len(payload_b64) % 4)
    return base64.urlsafe_b64decode((payload_b64 + padding).encode("ascii"))


def _decode_payload(payload_b64: str) -> dict[str, Any]:
    return json.loads(_payload_bytes(payload_b64).decode("utf-8"))


class QrServiceUnitTests(unittest.TestCase):
    """Подпись и проверка payload без БД."""

    def setUp(self) -> None:
        import app.qr_service as qr_service_module

        self.qr_service = qr_service_module
        self._settings_patch = patch.object(
            qr_service_module,
            "settings",
            replace(real_settings, game_session_secret=TEST_SECRET),
        )
        self._settings_patch.start()

    def tearDown(self) -> None:
        self._settings_patch.stop()

    def _generate(
        self,
        *,
        player_id: str = "player-qr-a",
        mission_id: str = "mission-qr-a",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return generate_qr_payload(
            player_id=player_id,
            mission_id=mission_id,
            now=now,
        )

    def _verify(
        self,
        issued: dict[str, Any],
        *,
        player_id: str = "player-qr-a",
        mission_id: str = "mission-qr-a",
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return verify_qr_payload(
            payload_b64=issued["payload"],
            hmac_b64=issued["hmac"],
            expected_player_id=player_id,
            expected_mission_id=mission_id,
            now=now,
        )

    # ---- Контракт payload -------------------------------------------
    def test_ttl_is_five_minutes(self) -> None:
        self.assertEqual(QR_TTL_SECONDS, 300)
        self.assertEqual(get_qr_ttl_seconds(), 300)

    def test_roundtrip_returns_signed_body(self) -> None:
        body = self._verify(self._generate())

        self.assertEqual(body["v"], QR_SCHEMA_VERSION)
        self.assertEqual(body["playerId"], "player-qr-a")
        self.assertEqual(body["missionId"], "mission-qr-a")
        self.assertEqual(len(body["nonce"]), 32)  # uuid4().hex
        self.assertEqual(body["exp"] - body["iat"], QR_TTL_SECONDS)

    def test_payload_is_canonical_json_without_padding(self) -> None:
        issued = self._generate()
        body = _decode_payload(issued["payload"])
        canonical = json.dumps(
            body,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        self.assertNotIn("=", issued["payload"])
        self.assertNotIn("=", issued["hmac"])
        self.assertEqual(issued["payload"], _b64url(canonical))

    def test_expires_at_matches_signed_exp(self) -> None:
        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)

        issued = self._generate(now=now)
        body = _decode_payload(issued["payload"])

        self.assertEqual(body["iat"], int(now.timestamp()))
        self.assertEqual(
            datetime.fromisoformat(issued["expiresAt"]),
            now + timedelta(seconds=QR_TTL_SECONDS),
        )

    def test_nonce_is_unique_per_call(self) -> None:
        first = _decode_payload(self._generate()["payload"])
        second = _decode_payload(self._generate()["payload"])

        self.assertNotEqual(first["nonce"], second["nonce"])
        self.assertNotEqual(first["nonce"], "")
    # ---- Подпись ----------------------------------------------------
    def test_signature_uses_domain_separated_key(self) -> None:
        issued = self._generate()
        raw_secret_signature = hmac.new(
            TEST_SECRET.encode("utf-8"),
            _payload_bytes(issued["payload"]),
            hashlib.sha256,
        ).digest()

        self.assertNotEqual(issued["hmac"], _b64url(raw_secret_signature))

        with self.assertRaises(ValueError) as context:
            verify_qr_payload(
                payload_b64=issued["payload"],
                hmac_b64=_b64url(raw_secret_signature),
                expected_player_id="player-qr-a",
                expected_mission_id="mission-qr-a",
            )

        self.assertEqual(str(context.exception), "invalid_hmac")

    def test_tampered_payload_rejected(self) -> None:
        issued = self._generate()
        body = _decode_payload(issued["payload"])
        body["missionId"] = "mission-qr-evil"
        tampered = json.dumps(
            body,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        with self.assertRaises(ValueError) as context:
            verify_qr_payload(
                payload_b64=_b64url(tampered),
                hmac_b64=issued["hmac"],
                expected_player_id="player-qr-a",
                expected_mission_id="mission-qr-evil",
            )

        self.assertEqual(str(context.exception), "invalid_hmac")

    def test_other_player_payload_rejected(self) -> None:
        issued = self._generate(player_id="player-qr-a")

        with self.assertRaises(ValueError) as context:
            self._verify(issued, player_id="player-qr-b")

        self.assertEqual(str(context.exception), "player_mismatch")

    def test_other_mission_payload_rejected(self) -> None:
        issued = self._generate(mission_id="mission-qr-a")

        with self.assertRaises(ValueError) as context:
            self._verify(issued, mission_id="mission-qr-b")

        self.assertEqual(str(context.exception), "mission_mismatch")

    # ---- Свежесть ---------------------------------------------------
    def test_valid_until_expiry_and_rejected_after(self) -> None:
        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
        issued = self._generate(now=now)

        self._verify(issued, now=now + timedelta(seconds=QR_TTL_SECONDS - 1))

        with self.assertRaises(ValueError) as context:
            self._verify(issued, now=now + timedelta(seconds=QR_TTL_SECONDS + 1))

        self.assertEqual(str(context.exception), "expired")

    # ---- Некорректный вход ------------------------------------------
    def test_malformed_base64_rejected(self) -> None:
        with self.assertRaises(ValueError) as context:
            verify_qr_payload(
                payload_b64="AAAAA",
                hmac_b64="AAAA",
                expected_player_id="player-qr-a",
                expected_mission_id="mission-qr-a",
            )

        self.assertEqual(str(context.exception), "invalid_base64")

    def test_non_json_body_rejected(self) -> None:
        derived_key = hmac.new(
            TEST_SECRET.encode("utf-8"),
            b"qr:v1",
            hashlib.sha256,
        ).digest()
        raw = b"not-a-json-body"

        with self.assertRaises(ValueError) as context:
            verify_qr_payload(
                payload_b64=_b64url(raw),
                hmac_b64=_b64url(
                    hmac.new(derived_key, raw, hashlib.sha256).digest()
                ),
                expected_player_id="player-qr-a",
                expected_mission_id="mission-qr-a",
            )

        self.assertEqual(str(context.exception), "invalid_payload_json")

    def test_unsupported_schema_version_rejected(self) -> None:
        now = datetime(2026, 10, 13, 12, 0, 0, tzinfo=timezone.utc)
        derived_key = hmac.new(
            TEST_SECRET.encode("utf-8"),
            b"qr:v1",
            hashlib.sha256,
        ).digest()
        raw = json.dumps(
            {
                "v": QR_SCHEMA_VERSION + 1,
                "playerId": "player-qr-a",
                "missionId": "mission-qr-a",
                "nonce": "0" * 32,
                "iat": int(now.timestamp()),
                "exp": int((now + timedelta(seconds=60)).timestamp()),
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

        with self.assertRaises(ValueError) as context:
            verify_qr_payload(
                payload_b64=_b64url(raw),
                hmac_b64=_b64url(
                    hmac.new(derived_key, raw, hashlib.sha256).digest()
                ),
                expected_player_id="player-qr-a",
                expected_mission_id="mission-qr-a",
                now=now,
            )

        self.assertEqual(str(context.exception), "unsupported_schema_version")

    # ---- Конфигурация ----------------------------------------------
    def test_missing_secret_fails_safely(self) -> None:
        without_secret = replace(real_settings, game_session_secret="")

        with patch.object(self.qr_service, "settings", without_secret):
            with self.assertRaises(RuntimeError):
                generate_qr_payload(
                    player_id="player-qr-a",
                    mission_id="mission-qr-a",
                )

            with self.assertRaises(RuntimeError):
                verify_qr_payload(
                    payload_b64="e30",
                    hmac_b64="e30",
                    expected_player_id="player-qr-a",
                    expected_mission_id="mission-qr-a",
                )



class MissionQrPayloadEntrypointTests(unittest.TestCase):
    """8.6.c: доменный вход QR-payload на изолированной SQLite.

    Схема поднимается настоящими миграциями (alembic upgrade head), секрет
    подписи подменяется на тестовый, чтобы результат не зависел от .env.
    """

    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-qr-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "mission-qr.sqlite3"
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

        import app.qr_service as qr_service_module

        cls.qr_service = qr_service_module
        cls._settings_patch = patch.object(
            qr_service_module,
            "settings",
            replace(real_settings, game_session_secret=TEST_SECRET),
        )
        cls._settings_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._settings_patch.stop()
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()


    # ---- Fixtures и хелперы -------------------------------------------
    def _fixture(self, *, players: int = 1) -> dict[str, Any]:
        from app.models import GamePlayer, GeoZone, Mission, Season

        suffix = uuid.uuid4().hex
        ids: dict[str, Any] = {
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "zone": f"zone-{suffix}",
            "mission": f"mission-{suffix}",
            "players": [f"player-{suffix}-{index}" for index in range(players)],
        }

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="QR test season",
                    description="Isolated qr fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()

            session.add(
                GeoZone(
                    id=ids["zone"],
                    slug=f"zone-{suffix}",
                    title="QR test zone",
                    description="Isolated qr fixture",
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

            session.add_all(
                [
                    GamePlayer(
                        id=player_id,
                        display_name=f"QR Player-{index}",
                        auth_provider="telegram",
                        external_id=f"tg-{uuid.uuid4().hex}",
                        status="active",
                    )
                    for index, player_id in enumerate(ids["players"])
                ]
            )
            session.flush()

            session.add(
                Mission(
                    id=ids["mission"],
                    season_id=ids["season"],
                    slug=f"mission-{suffix}",
                    mission_type="text_answer",
                    mission_category="solo",
                    title="QR test mission",
                    description="Isolated qr fixture",
                    content={"schemaVersion": 1},
                    validation_config={},
                    status="published",
                    sort_order=1,
                    geo_zone_id=ids["zone"],
                )
            )

        return ids

    def _accept(self, player_id: str, mission_id: str) -> dict[str, Any]:
        return self.mission_engine.accept_mission(
            player_id,
            mission_id,
            self.PLAYER_LATITUDE,
            self.PLAYER_LONGITUDE,
        )

    def _set_player_mission_status(
        self,
        player_id: str,
        mission_id: str,
        status: str,
    ) -> None:
        from app.models import PlayerMission

        with self.SessionLocal.begin() as session:
            player_mission = session.scalars(
                select(PlayerMission).where(
                    PlayerMission.player_id == player_id,
                    PlayerMission.mission_id == mission_id,
                )
            ).one()
            player_mission.status = status

    def _set_mission_status(self, mission_id: str, status: str) -> None:
        from app.models import Mission

        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, mission_id)
            assert mission is not None
            mission.status = status

    def _player_mission_count(self, player_id: str) -> int:
        from app.models import PlayerMission

        with self.SessionLocal() as session:
            count = session.scalar(
                select(func.count())
                .select_from(PlayerMission)
                .where(PlayerMission.player_id == player_id)
            )

        return int(count or 0)


    # ---- 8.6.c: сценарии ----------------------------------------------
    def test_qr_requires_in_progress(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]

        # До accept миссии ещё нет у игрока; повтор внутри цикла проверяет,
        # что ошибка не создаёт PlayerMission (read-only инвариант).
        for _ in range(2):
            with self.assertRaises(MissionEngineError) as context:
                self.mission_engine.get_mission_qr_payload(
                    player_id=player_id,
                    mission_id=ids["mission"],
                )

            self.assertEqual(context.exception.status_code, 409)

        self.assertEqual(self._player_mission_count(player_id), 0)

    def test_qr_available_after_accept(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]
        self._accept(player_id, ids["mission"])

        response = self.mission_engine.get_mission_qr_payload(
            player_id=player_id,
            mission_id=ids["mission"],
        )

        self.assertEqual(
            set(response),
            {"missionId", "payload", "hmac", "expiresAt", "ttlSeconds"},
        )
        self.assertEqual(response["missionId"], ids["mission"])
        self.assertEqual(response["ttlSeconds"], QR_TTL_SECONDS)
        self.assertNotEqual(response["payload"], "")
        self.assertNotEqual(response["hmac"], "")

        expires_at = datetime.fromisoformat(response["expiresAt"])
        self.assertIsNotNone(expires_at.tzinfo)
        now = datetime.now(timezone.utc)
        self.assertGreater(expires_at, now)
        self.assertLessEqual(
            expires_at,
            now + timedelta(seconds=QR_TTL_SECONDS + 5),
        )

        body = verify_qr_payload(
            payload_b64=response["payload"],
            hmac_b64=response["hmac"],
            expected_player_id=player_id,
            expected_mission_id=ids["mission"],
        )
        self.assertEqual(body["v"], QR_SCHEMA_VERSION)
        self.assertEqual(body["playerId"], player_id)
        self.assertEqual(body["missionId"], ids["mission"])
        self.assertEqual(body["exp"], int(expires_at.timestamp()))

    def test_qr_rotates_payload_per_call(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]
        self._accept(player_id, ids["mission"])

        first = self.mission_engine.get_mission_qr_payload(
            player_id=player_id,
            mission_id=ids["mission"],
        )
        second = self.mission_engine.get_mission_qr_payload(
            player_id=player_id,
            mission_id=ids["mission"],
        )

        self.assertNotEqual(first["payload"], second["payload"])
        self.assertNotEqual(first["hmac"], second["hmac"])

        # Предыдущий payload остаётся валидным до собственного exp:
        # инвалидация произойдёт только при скане (8.8), где nonce проверяется.
        for issued in (first, second):
            verify_qr_payload(
                payload_b64=issued["payload"],
                hmac_b64=issued["hmac"],
                expected_player_id=player_id,
                expected_mission_id=ids["mission"],
            )


    def test_qr_rejected_for_unknown_mission(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]

        with self.assertRaises(MissionEngineError) as context:
            self.mission_engine.get_mission_qr_payload(
                player_id=player_id,
                mission_id="mission-does-not-exist",
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_qr_rejected_when_mission_not_published(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]
        self._accept(player_id, ids["mission"])
        self._set_mission_status(ids["mission"], "draft")

        with self.assertRaises(MissionEngineError) as context:
            self.mission_engine.get_mission_qr_payload(
                player_id=player_id,
                mission_id=ids["mission"],
            )

        self.assertEqual(context.exception.status_code, 404)

    def test_qr_rejected_when_locked(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]
        self._accept(player_id, ids["mission"])
        self._set_player_mission_status(player_id, ids["mission"], "locked")

        with self.assertRaises(MissionEngineError) as context:
            self.mission_engine.get_mission_qr_payload(
                player_id=player_id,
                mission_id=ids["mission"],
            )

        self.assertEqual(context.exception.status_code, 403)

    def test_qr_rejected_after_completion(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]
        self._accept(player_id, ids["mission"])
        self._set_player_mission_status(player_id, ids["mission"], "completed")

        with self.assertRaises(MissionEngineError) as context:
            self.mission_engine.get_mission_qr_payload(
                player_id=player_id,
                mission_id=ids["mission"],
            )

        self.assertEqual(context.exception.status_code, 409)

    def test_qr_rejected_when_cancelled(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]
        self._accept(player_id, ids["mission"])
        self._set_player_mission_status(player_id, ids["mission"], "cancelled")

        with self.assertRaises(MissionEngineError) as context:
            self.mission_engine.get_mission_qr_payload(
                player_id=player_id,
                mission_id=ids["mission"],
            )

        self.assertEqual(context.exception.status_code, 409)

    def test_qr_is_player_specific(self) -> None:
        ids = self._fixture(players=2)
        first_player, second_player = ids["players"]
        self._accept(first_player, ids["mission"])
        self._accept(second_player, ids["mission"])

        first_qr = self.mission_engine.get_mission_qr_payload(
            player_id=first_player,
            mission_id=ids["mission"],
        )
        second_qr = self.mission_engine.get_mission_qr_payload(
            player_id=second_player,
            mission_id=ids["mission"],
        )

        # Скриншот чужого QR не сработает: playerId входит в подпись.
        self.assertNotEqual(first_qr["payload"], second_qr["payload"])
        self.assertNotEqual(first_qr["hmac"], second_qr["hmac"])

        with self.assertRaises(ValueError) as context:
            verify_qr_payload(
                payload_b64=first_qr["payload"],
                hmac_b64=first_qr["hmac"],
                expected_player_id=second_player,
                expected_mission_id=ids["mission"],
            )

        self.assertEqual(str(context.exception), "player_mismatch")

    def test_qr_missing_secret_returns_503(self) -> None:
        ids = self._fixture()
        player_id = ids["players"][0]
        self._accept(player_id, ids["mission"])

        without_secret = replace(real_settings, game_session_secret="")

        with patch.object(self.qr_service, "settings", without_secret):
            with self.assertRaises(MissionEngineError) as context:
                self.mission_engine.get_mission_qr_payload(
                    player_id=player_id,
                    mission_id=ids["mission"],
                )

        self.assertEqual(context.exception.status_code, 503)

