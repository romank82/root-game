"""Тесты stars_service.send_gas_invoice (10.4-fix): sendInvoice в чат с ботом.

Обход бага Android (WebView openInvoice не доставляет pre_checkout_query):
инвойс отправляется в личный чат игрока с ботом через Bot API sendInvoice.

Инфраструктура — паттерн test_stars_service.py: на каждый тест свежая
disposable SQLite + alembic upgrade head; SessionLocal патчится на неё в
app.db (ленивые импорты) и app.stars_service (module-level импорт).
Реальный Telegram не вызывается — httpx.post мокается (_patch_bot_api).

Покрывает:
  1. send_gas_invoice: pending StarsPayment + sendInvoice с chat_id =
     external_id, цена из CMS (активная SystemSetting economy.gas_pack_100);
  2. игрок без external_id: MissionEngineError(400), запись не создаётся;
  3. игрок не найден: MissionEngineError(404), запись не создаётся.
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
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError
from app.models import GamePlayer, StarsPayment, SystemSetting
from app.stars_service import send_gas_invoice

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class _MockResponse:
    """Мини-заглушка httpx.Response: только .json() для _bot_api."""

    def __init__(self, result_json: dict) -> None:
        self._result_json = result_json

    def json(self) -> dict:
        return self._result_json


class SendGasInvoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модуль; SessionLocal патчится на свежую БД в setUp."""
        from app import stars_service

        cls.stars_service = stars_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-stars-send-tests-"
        )
        self.database_path = Path(self._temporary_directory.name) / "stars.sqlite3"
        database_url = f"sqlite:///{self.database_path}"

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

        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        # Патчим ДВА канала SessionLocal: app.db (ленивые импорты) и
        # аттрибут модуля stars_service (используется entrypoint-ами).
        self._session_local_patches = [
            patch("app.db.SessionLocal", self.SessionLocal),
            patch.object(self.stars_service, "SessionLocal", self.SessionLocal),
        ]
        for session_local_patch in self._session_local_patches:
            session_local_patch.start()

    def tearDown(self) -> None:
        for session_local_patch in self._session_local_patches:
            session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------------

    # Sentinel: "_make_player" генерирует случайный external_id по умолчанию,
    # а явный external_id=None значит «игрок без external_id» (для теста 400).
    _AUTO_EXTERNAL_ID = object()

    def _make_player(
        self,
        session,
        suffix: str,
        external_id=_AUTO_EXTERNAL_ID,
    ) -> str:
        """Игрок GamePlayer со статусом active и заданным external_id."""
        player_id = f"stars-send-player-{uuid.uuid4().hex[:10]}"
        if external_id is self._AUTO_EXTERNAL_ID:
            external_id = f"test-stars-send-{uuid.uuid4().hex}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name=f"Stars send {suffix}",
                auth_provider="test",
                external_id=external_id,
                status="active",
            )
        )
        session.flush()  # FK: stars_payments.player_id -> game_players
        return player_id

    def _seed_gas_pack_setting(self, session, gas_amount: int, price: int) -> None:
        """Активная SystemSetting economy.gas_pack_{N} (CMS-first), идемпотентно.

        Миграция dde2038a44d9 уже создаёт economy.gas_pack_* из каталога,
        поэтому при существующей записи обновляем ТОЛЬКО value_json
        (+status): метаданные (в частности is_sensitive=True в каталоге)
        должны остаться каталоговыми, иначе admin_system_settings отдаёт 409.
        """
        key = f"economy.gas_pack_{gas_amount}"
        existing = session.get(SystemSetting, key)
        if existing is not None:
            existing.value_json = price
            existing.status = "active"
        else:
            session.add(
                SystemSetting(
                    key=key,
                    value_json=price,
                    value_type="integer",
                    category="economy",
                    title=key,
                    description="Seeded by stars_send_invoice test",
                    is_sensitive=False,
                    status="active",
                )
            )
        session.flush()

    def _patch_bot_api(self, result_json: dict):
        """Мок httpx.post для app.stars_service (никакого Telegram)."""
        return patch(
            "app.stars_service.httpx.post",
            return_value=_MockResponse(result_json),
        )

    # ---- Тесты --------------------------------------------------------------

    def test_send_gas_invoice_creates_payment_and_calls_send_invoice(self) -> None:
        """send_gas_invoice: pending StarsPayment, chat_id=external_id=12345,
        prices=[{label: '100 газа', amount: 80}], payload=reference_id."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "send-invoice", external_id="12345")
            self._seed_gas_pack_setting(session, 100, 80)

        with self._patch_bot_api({"ok": True, "result": True}) as mock_post:
            result = send_gas_invoice(player_id, 100)

        self.assertEqual(result["gasAmount"], 100)
        # Активная SystemSetting economy.gas_pack_100 = 80 (CMS-first).
        self.assertEqual(result["amountStars"], 80)
        self.assertEqual(result["chatId"], "12345")
        reference_id = result["referenceId"]
        self.assertTrue(reference_id)

        # sendInvoice: правильный method и payload.
        url = mock_post.call_args.args[0]
        call_payload = mock_post.call_args.kwargs["json"]
        self.assertIn("/sendInvoice", url)
        self.assertEqual(call_payload["chat_id"], "12345")
        self.assertEqual(call_payload["payload"], reference_id)
        self.assertEqual(call_payload["currency"], "XTR")
        self.assertEqual(call_payload["provider_token"], "")
        self.assertEqual(
            call_payload["prices"], [{"label": "100 газа", "amount": 80}]
        )

        # StarsPayment: одна запись, pending, payload = reference_id.
        with self.SessionLocal() as session:
            payments = session.scalars(select(StarsPayment)).all()
            self.assertEqual(len(payments), 1)
            payment = payments[0]
            self.assertEqual(payment.player_id, player_id)
            self.assertEqual(payment.status, "pending")
            self.assertEqual(payment.gas_amount, Decimal(100))
            self.assertEqual(payment.amount_stars, 80)
            self.assertEqual(payment.reference_id, reference_id)
            self.assertEqual(payment.payload, reference_id)

    def test_send_gas_invoice_no_external_id_400(self) -> None:
        """Игрок без external_id: MissionEngineError(400), sendInvoice не зовётся."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "no-external-id", external_id=None)
            self._seed_gas_pack_setting(session, 100, 80)

        with self._patch_bot_api({"ok": True, "result": True}) as mock_post:
            with self.assertRaises(MissionEngineError) as context:
                send_gas_invoice(player_id, 100)
        self.assertEqual(context.exception.status_code, 400)
        mock_post.assert_not_called()

        with self.SessionLocal() as session:
            payments_count = session.scalar(
                select(func.count()).select_from(StarsPayment)
            )
        self.assertEqual(payments_count, 0)

    def test_send_gas_invoice_player_not_found_404(self) -> None:
        """Несуществующий игрок: MissionEngineError(404), sendInvoice не зовётся.

        Цена читается до проверки игрока (_gas_pack_price), поэтому сеттинг
        сидится заранее — иначе упадёт 400 «Пакет газа не настроен», а не 404.
        """
        with self.SessionLocal.begin() as session:
            self._seed_gas_pack_setting(session, 100, 80)

        with self._patch_bot_api({"ok": True, "result": True}) as mock_post:
            with self.assertRaises(MissionEngineError) as context:
                send_gas_invoice("no-such-player", 100)
        self.assertEqual(context.exception.status_code, 404)
        mock_post.assert_not_called()

        with self.SessionLocal() as session:
            payments_count = session.scalar(
                select(func.count()).select_from(StarsPayment)
            )
        self.assertEqual(payments_count, 0)

