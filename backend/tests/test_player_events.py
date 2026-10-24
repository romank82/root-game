"""13.3 — PlayerEvent: record_player_event + 5 интеграционных точек.

Покрывает:

  1. test_record_player_event_creates — record_player_event создаёт запись
     (id, player_id, event_type, payload_json, correlation_id).
  2. test_auth_login_event_written — auth.login из authenticate_telegram
     (main.py): мокается ТОЛЬКО verify_init_data (внешняя крипто-проверка
     подписи Telegram не является предметом теста), весь остальной путь —
     реальный upsert игрока + реальная запись PlayerEvent.
  3. test_mission_accepted_event_written — mission.accepted из
     accept_mission (mission_engine.py).
  4. test_mission_completed_event_written — mission.completed из
     submit_mission (mission_engine.py).
  5. test_transfer_completed_event_written — transfer.completed из
     transfer_root (transfer_service.py).
  6. test_gas_purchased_event_written — gas.purchased из
     handle_successful_payment (stars_service.py).

Инфраструктура — по образцу test_country_policy_integration /
test_stars_service: реальная SQLite + alembic upgrade head; SessionLocal
патчится там, где сервис открывает сессию сам (app.db — для ленивых
импортов, плюс main, mission_engine, stars_service). transfer_root и
record_player_event принимают session аргументом — им патчи не нужны.

В приложении ничего не меняется: события читаются только в изолированной
тестовой базе.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class PlayerEventsTests(unittest.TestCase):
    """PlayerEvent: прямая запись + 5 интеграционных точек (13.3)."""

    PLAYER_LATITUDE = 55.7558
    PLAYER_LONGITUDE = 37.6173

    @classmethod
    def setUpClass(cls) -> None:
        """Реальная SQLite + alembic head; SessionLocal патчится в
        app.db, main, mission_engine, stars_service."""
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-player-events-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "player-events.sqlite3"
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

        from app import main, mission_engine, stars_service

        cls._session_local_patches = [
            patch("app.db.SessionLocal", cls.SessionLocal),
            patch.object(main, "SessionLocal", cls.SessionLocal),
            patch.object(mission_engine, "SessionLocal", cls.SessionLocal),
            patch.object(stars_service, "SessionLocal", cls.SessionLocal),
        ]
        for session_local_patch in cls._session_local_patches:
            session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        for session_local_patch in cls._session_local_patches:
            session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы ---------------------------------------------

    def _make_player(self, session, suffix: str, status: str = "active") -> str:
        """Игрок GamePlayer (status по умолчанию active)."""
        from app.models import GamePlayer

        player_id = f"pe-player-{uuid.uuid4().hex[:10]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name=f"Player events {suffix}",
                auth_provider="test",
                external_id=f"pe-{uuid.uuid4().hex}",
                status=status,
            )
        )
        session.flush()  # FK: player_events.player_id -> game_players
        return player_id

    def _count_events(self, event_type: str, player_id: str) -> int:
        """Число PlayerEvent данного типа для игрока (после коммита)."""
        from app.models import PlayerEvent

        with self.SessionLocal() as session:
            return session.scalar(
                select(func.count(PlayerEvent.id)).where(
                    PlayerEvent.event_type == event_type,
                    PlayerEvent.player_id == player_id,
                )
            ) or 0

    def _get_event(self, event_type: str, player_id: str):
        """PlayerEvent-запись данного типа для игрока (или None)."""
        from app.models import PlayerEvent

        with self.SessionLocal() as session:
            return session.scalar(
                select(PlayerEvent).where(
                    PlayerEvent.event_type == event_type,
                    PlayerEvent.player_id == player_id,
                )
            )

    def _make_mission_fixture(self, session, suffix: str) -> dict[str, str]:
        """Season -> Chapter -> GeoZone -> ARObject -> Mission (published),
        text_answer c acceptedAnswers=['complete'] (валидация submit_mission)."""
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
                title="Player events season",
                description="Isolated PlayerEvent fixture",
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
                title="Player events chapter",
                description="Isolated PlayerEvent fixture",
                status="published",
                sort_order=1,
            )
        )
        session.flush()

        session.add(
            GeoZone(
                id=ids["zone"],
                slug=f"zone-{suffix}",
                title="Player events zone",
                description="Isolated PlayerEvent fixture",
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
                title="Player events AR object",
                description="Isolated PlayerEvent fixture",
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
                instruction_text="Player events instruction",
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
                title="Player events mission",
                description="Isolated PlayerEvent fixture",
                content={"schemaVersion": 1},
                validation_config={
                    "validator": "normalized_text_match",
                    "acceptedAnswers": ["complete"],
                },
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

    def _ensure_transfer_settings(self, session) -> None:
        """CMS-настройки перевода (эталонные значения из PG 10.5 теста)."""
        from app.models import SystemSetting

        for key, value in {
            "economy.transfer_min_amount": 1,
            "economy.transfer_max_amount": 10000,
            "economy.daily_transfer_limit": 50000,
            "economy.transfer_minimum_earned_root": 50,
            "economy.gas_fee_percent": 1,
        }.items():
            if session.get(SystemSetting, key) is None:
                session.add(
                    SystemSetting(
                        key=key,
                        value_json=value,
                        value_type="integer",
                        category="economy",
                        title=key,
                        description="Seeded by player_events test",
                        is_sensitive=True,
                        status="active",
                    )
                )

    def _seed_root_wallet(self, session, player_id: str, balance: int) -> str:
        """ROOT-кошелёк + credit с reference_type='mission_reward' — даёт
        earned (порог для transfer_root)."""
        from app.models import Wallet, WalletTransaction

        wallet_id = f"wallet-{uuid.uuid4().hex}"
        session.add(
            Wallet(
                id=wallet_id,
                player_id=player_id,
                currency="ROOT",
                available_balance=balance,
                locked_balance=0,
            )
        )
        session.flush()
        session.add(
            WalletTransaction(
                id=f"wallet-transaction-{uuid.uuid4().hex}",
                wallet_id=wallet_id,
                amount=balance,
                balance_after=balance,
                transaction_type="credit",
                reason="PE transfer seed",
                reference_type="mission_reward",
                reference_id=f"seed-{uuid.uuid4().hex}",
                metadata_json={},
            )
        )
        return wallet_id

    def _seed_gas_wallet(self, session, player_id: str, balance: int) -> str:
        """Газовый кошелёк + seed credit-проводка (для газовой комиссии)."""
        from app.models import GasTransaction, GasWallet

        gas_wallet_id = f"gas-wallet-{uuid.uuid4().hex}"
        session.add(
            GasWallet(id=gas_wallet_id, player_id=player_id, balance=Decimal(balance))
        )
        session.flush()
        if balance > 0:
            session.add(
                GasTransaction(
                    id=f"gas-transaction-{uuid.uuid4().hex}",
                    gas_wallet_id=gas_wallet_id,
                    amount=Decimal(balance),
                    balance_after=Decimal(balance),
                    transaction_type="credit",
                    reason="PE gas seed",
                    reference_type="test_seed",
                    reference_id=f"gas-seed-{uuid.uuid4().hex}",
                    metadata_json={},
                )
            )
        return gas_wallet_id

    def _seed_pending_payment(
        self,
        session,
        player_id: str,
        reference_id: str,
        gas_amount: int = 100,
        amount_stars: int = 80,
    ) -> None:
        """Pending StarsPayment, payload = reference_id (как в сервисе)."""
        from app.models import StarsPayment

        session.add(
            StarsPayment(
                id=f"stars-payment-{uuid.uuid4().hex}",
                player_id=player_id,
                gas_amount=Decimal(gas_amount),
                amount_stars=amount_stars,
                telegram_payment_charge_id=None,
                status="pending",
                reference_id=reference_id,
                payload=reference_id,
            )
        )
        session.flush()

    # ---- Тесты -----------------------------------------------------------

    def test_record_player_event_creates(self) -> None:
        """record_player_event: запись (id/player_id/event_type/payload/
        correlation_id) создаётся и сохраняется."""
        from app.models import PlayerEvent
        from app.player_events import record_player_event

        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "record")
            event = record_player_event(
                session,
                player_id,
                "auth.login",
                payload={"authProvider": "telegram"},
                correlation_id="corr-1",
            )
            self.assertTrue(event.id.startswith("player-event-"))
            stored = session.get(PlayerEvent, event.id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored.player_id, player_id)
        self.assertEqual(stored.event_type, "auth.login")
        self.assertEqual(stored.payload_json, {"authProvider": "telegram"})
        self.assertEqual(stored.correlation_id, "corr-1")

    def test_auth_login_event_written(self) -> None:
        """authenticate_telegram (реальный код) c mock verify_init_data:
        запись auth.login создаётся в player_events."""
        from starlette.responses import Response

        from app.main import TelegramAuthPayload, authenticate_telegram
        from app.telegram_auth import VerifiedTelegramUser

        fake_telegram_user = VerifiedTelegramUser(
            telegram_id="42",
            first_name="Telegram Player",
            last_name=None,
            username="tgplayer",
            photo_url=None,
        )

        # __wrapped__: обходим slowapi-обёртку limiter.limit (вызов вне
        # FastAPI/request-контекста), но исполняем тело endpoint полностью.
        # verify_init_data — единственный внешний стык (крипто-проверка
        # подписи Telegram) — мокается; upsert игрока и PlayerEvent реальны.
        with patch(
            "app.main.verify_init_data", return_value=fake_telegram_user
        ):
            authenticate_telegram.__wrapped__(
                request=SimpleNamespace(state=None),
                payload=TelegramAuthPayload(init_data="unused-init-data"),
                response=Response(),
            )

        from app.models import GamePlayer

        with self.SessionLocal() as session:
            player_id = session.scalar(
                select(GamePlayer.id).where(
                    (GamePlayer.auth_provider == "telegram")
                    & (GamePlayer.external_id == "42")
                )
            )
        self.assertIsNotNone(
            player_id, "Игрок не создан через _upsert_telegram_player"
        )

        event = self._get_event("auth.login", player_id)
        self.assertIsNotNone(event, "PlayerEvent auth.login не записан")
        self.assertEqual(event.payload_json, {"authProvider": "telegram"})
        self.assertIsNone(event.correlation_id)  # request.state.audit_context нет
        self.assertEqual(self._count_events("auth.login", player_id), 1)

    def test_mission_accepted_event_written(self) -> None:
        """accept_mission: mission.accepted записывается один раз."""
        from app.mission_engine import accept_mission

        suffix = uuid.uuid4().hex
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "mission-accept")
            ids = self._make_mission_fixture(session, suffix)

        result = accept_mission(
            player_id=player_id,
            mission_id=ids["mission"],
            latitude=self.PLAYER_LATITUDE,
            longitude=self.PLAYER_LONGITUDE,
            accuracy=10.0,
        )
        self.assertTrue(result["accepted"])

        self.assertEqual(self._count_events("mission.accepted", player_id), 1)
        event = self._get_event("mission.accepted", player_id)
        self.assertIsNotNone(event)
        self.assertEqual(event.payload_json, {"missionId": ids["mission"]})
        self.assertIsNone(event.correlation_id)

    def test_mission_completed_event_written(self) -> None:
        """accept + submit(text_answer) успешно: mission.completed один раз."""
        from app.mission_engine import accept_mission, submit_mission

        suffix = uuid.uuid4().hex
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "mission-submit")
            ids = self._make_mission_fixture(session, suffix)

        accepted = accept_mission(
            player_id=player_id,
            mission_id=ids["mission"],
            latitude=self.PLAYER_LATITUDE,
            longitude=self.PLAYER_LONGITUDE,
            accuracy=10.0,
        )
        self.assertTrue(accepted["accepted"])

        completed = submit_mission(
            player_id=player_id,
            mission_id=ids["mission"],
            answer="complete",
        )
        self.assertTrue(completed["accepted"])

        self.assertEqual(self._count_events("mission.completed", player_id), 1)
        event = self._get_event("mission.completed", player_id)
        self.assertIsNotNone(event)
        self.assertEqual(event.payload_json["missionId"], ids["mission"])
        self.assertIn("rewardRoot", event.payload_json)
        self.assertIsNone(event.correlation_id)

    def test_transfer_completed_event_written(self) -> None:
        """transfer_root: transfer.completed один раз (payload с transferId)."""
        from app.transfer_service import transfer_root

        with self.SessionLocal.begin() as session:
            self._ensure_transfer_settings(session)
            from_player = self._make_player(session, "transfer-from")
            to_player = self._make_player(session, "transfer-to")
            self._seed_root_wallet(session, from_player, 1000)  # earned=1000
            self._seed_root_wallet(session, to_player, 500)
            self._seed_gas_wallet(session, from_player, 1000)  # gas fee = 100*1%
            result = transfer_root(
                session,
                from_player_id=from_player,
                to_player_id=to_player,
                amount=100,
                request_id=f"pe-transfer-{uuid.uuid4().hex}",
            )
        # Коммит состоялся на выходе из SessionLocal.begin.
        self.assertEqual(result["status"], "completed")
        transfer_id = result["transferId"]

        self.assertEqual(
            self._count_events("transfer.completed", from_player), 1
        )
        event = self._get_event("transfer.completed", from_player)
        self.assertIsNotNone(event)
        self.assertEqual(event.payload_json["toPlayerId"], to_player)
        self.assertEqual(event.payload_json["amount"], 100)
        self.assertEqual(event.payload_json["transferId"], transfer_id)
        self.assertIsNone(event.correlation_id)

    def test_gas_purchased_event_written(self) -> None:
        """handle_successful_payment: gas.purchased один раз (payload с
        gasAmount как str — точность Decimal)."""
        from app.stars_service import handle_successful_payment

        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "gas")
            self._seed_gas_wallet(session, player_id, balance=0)
            self._seed_pending_payment(
                session,
                player_id,
                reference_id="pe-ref-1",
                gas_amount=100,
                amount_stars=80,
            )

        handle_successful_payment(
            {
                "message": {
                    "successful_payment": {
                        "invoice_payload": "pe-ref-1",
                        "telegram_payment_charge_id": "pe-charge-1",
                    }
                }
            }
        )

        self.assertEqual(self._count_events("gas.purchased", player_id), 1)
        event = self._get_event("gas.purchased", player_id)
        self.assertIsNotNone(event)
        self.assertEqual(event.payload_json["gasAmount"], "100.0000")
        self.assertEqual(event.payload_json["amountStars"], 80)
        self.assertEqual(event.payload_json["referenceId"], "pe-ref-1")
        self.assertEqual(event.payload_json["chargeId"], "pe-charge-1")
        self.assertIsNone(event.correlation_id)
