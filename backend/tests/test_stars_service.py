"""Тесты stars_service (10.4-g-2): покупка газа за Telegram Stars.

Инфраструктура — паттерн test_admin_economy.py: на каждый тест свежая
disposable SQLite + alembic upgrade head; SessionLocal патчится на неё в
app.db (ленивые импорты) и app.stars_service (module-level импорт).
Реальный Telegram не вызывается — httpx.post мокается (_patch_bot_api).

Покрывает:
  1. create_invoice_link: pending StarsPayment + инвойс, цена из CMS
     (активная SystemSetting economy.gas_pack_100);
  2. неизвестный пакет (gas_amount=999): MissionEngineError(400),
     запись не создаётся;
  3. pre_checkout_query: ok=True для существующего pending-платежа,
     ok=False + error_message для неизвестного payload;
  4. successful_payment: charge_id сохраняется, газ начисляется
     (GasWallet + GasTransaction stars_purchase);
  5. повтор successful_payment — идемпотентно: баланс и число проводок
     не меняются.
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
from app.models import GasTransaction, GasWallet, GamePlayer, StarsPayment, SystemSetting
from app.stars_service import (
    create_invoice_link,
    handle_pre_checkout_query,
    handle_successful_payment,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class _MockResponse:
    """Мини-заглушка httpx.Response: только .json() для _bot_api."""

    def __init__(self, result_json: dict) -> None:
        self._result_json = result_json

    def json(self) -> dict:
        return self._result_json


class StarsServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модуль; SessionLocal патчится на свежую БД в setUp."""
        from app import stars_service

        cls.stars_service = stars_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-stars-tests-"
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

    def _make_player(self, session, suffix: str) -> str:
        """Игрок GamePlayer со статусом active."""
        player_id = f"stars-player-{uuid.uuid4().hex[:10]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name=f"Stars {suffix}",
                auth_provider="test",
                external_id=f"test-stars-{uuid.uuid4().hex}",
                status="active",
            )
        )
        session.flush()  # FK: stars_payments/gas_wallets.player_id -> game_players
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
                    description="Seeded by stars_service test",
                    is_sensitive=False,
                    status="active",
                )
            )
        session.flush()

    def _seed_pending_payment(
        self,
        session,
        player_id: str,
        reference_id: str = "ref-1",
        gas_amount: int = 100,
        amount_stars: int = 80,
    ) -> None:
        """Pending StarsPayment, payload = reference_id (как в сервисе)."""
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

    def _seed_gas_wallet(self, session, player_id: str, balance: int = 0) -> str:
        wallet_id = f"gas-wallet-{uuid.uuid4().hex}"
        session.add(
            GasWallet(id=wallet_id, player_id=player_id, balance=Decimal(balance))
        )
        session.flush()
        return wallet_id

    def _patch_bot_api(self, result_json: dict):
        """Мок httpx.post для app.stars_service (никакого Telegram)."""
        return patch(
            "app.stars_service.httpx.post",
            return_value=_MockResponse(result_json),
        )

    def test_create_invoice_link_creates_pending(self) -> None:
        """Инвойс создаётся, StarsPayment в pending, цена из CMS."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "invoice")
            self._seed_gas_pack_setting(session, 100, 80)

        with self._patch_bot_api(
            {"ok": True, "result": "https://t.me/invoice/1"}
        ) as mock_post:
            result = create_invoice_link(player_id, 100)

        self.assertEqual(result["invoiceLink"], "https://t.me/invoice/1")
        self.assertEqual(result["gasAmount"], 100)
        # Активная SystemSetting economy.gas_pack_100 = 80 (CMS-first).
        self.assertEqual(result["amountStars"], 80)
        reference_id = result["referenceId"]
        self.assertTrue(reference_id.startswith("stars-invoice-"))

        with self.SessionLocal() as session:
            payment = session.scalar(
                select(StarsPayment).where(
                    StarsPayment.reference_id == reference_id
                )
            )
        self.assertIsNotNone(payment)
        self.assertEqual(payment.status, "pending")
        self.assertEqual(payment.gas_amount, Decimal("100"))
        self.assertEqual(payment.amount_stars, 80)
        self.assertIsNone(payment.telegram_payment_charge_id)
        self.assertEqual(payment.payload, reference_id)

        # Вызов Bot API: метод createInvoiceLink, корректные payload и цены.
        url = mock_post.call_args.args[0]
        call_payload = mock_post.call_args.kwargs["json"]
        self.assertIn("createInvoiceLink", url)
        self.assertEqual(call_payload["payload"], reference_id)
        self.assertEqual(call_payload["currency"], "XTR")
        self.assertEqual(call_payload["prices"], [{"label": "100 газа", "amount": 80}])

    def test_create_invoice_link_unknown_pack_400(self) -> None:
        """Неизвестный пакет: 400, StarsPayment не создаётся."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "unknown-pack")

        with self.assertRaises(MissionEngineError) as context:
            create_invoice_link(player_id, 999)
        self.assertEqual(context.exception.status_code, 400)

        with self.SessionLocal() as session:
            payments_count = session.scalar(
                select(func.count()).select_from(StarsPayment)
            )
        self.assertEqual(payments_count, 0)

    def test_pre_checkout_query_ok_and_rejected(self) -> None:
        """pre_checkout: ok=True для pending-платежа, ok=False для чужого payload."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "pre-checkout")
            self._seed_pending_payment(
                session, player_id, reference_id="ref-1", gas_amount=100,
                amount_stars=80,
            )

        # Существующий pending-платёж -> ответ положительный.
        with self._patch_bot_api({"ok": True, "result": True}) as mock_post:
            handle_pre_checkout_query(
                {"pre_checkout_query": {"id": "q1", "invoice_payload": "ref-1"}}
            )
        url = mock_post.call_args.args[0]
        call_payload = mock_post.call_args.kwargs["json"]
        self.assertIn("answerPreCheckoutQuery", url)
        self.assertEqual(call_payload["pre_checkout_query_id"], "q1")
        self.assertTrue(call_payload["ok"])
        self.assertNotIn("error_message", call_payload)

        # Неизвестный payload -> отрицательный ответ с ошибкой.
        with self._patch_bot_api({"ok": True, "result": True}) as mock_post:
            handle_pre_checkout_query(
                {"pre_checkout_query": {"id": "q2", "invoice_payload": "no-such"}}
            )
        call_payload = mock_post.call_args.kwargs["json"]
        self.assertEqual(call_payload["pre_checkout_query_id"], "q2")
        self.assertFalse(call_payload["ok"])
        self.assertEqual(
            call_payload["error_message"], "Платёж не найден или уже обработан."
        )

    def test_successful_payment_credits_gas(self) -> None:
        """successful_payment: charge_id + начисление газа (GasWallet/GasTransaction)."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "success")
            self._seed_gas_wallet(session, player_id, balance=0)
            self._seed_pending_payment(
                session, player_id, reference_id="ref-1", gas_amount=100,
                amount_stars=80,
            )

        handle_successful_payment(
            {
                "message": {
                    "successful_payment": {
                        "invoice_payload": "ref-1",
                        "telegram_payment_charge_id": "charge-1",
                    }
                }
            }
        )

        with self.SessionLocal() as session:
            payment = session.scalar(
                select(StarsPayment).where(StarsPayment.reference_id == "ref-1")
            )
            wallet = session.scalar(
                select(GasWallet).where(GasWallet.player_id == player_id)
            )
            transaction = session.scalar(
                select(GasTransaction).where(
                    GasTransaction.reference_id == "ref-1"
                )
            )
        self.assertIsNotNone(payment)
        self.assertIsNotNone(wallet)
        self.assertIsNotNone(transaction)
        self.assertEqual(payment.status, "completed")
        self.assertEqual(payment.telegram_payment_charge_id, "charge-1")
        self.assertEqual(wallet.balance, Decimal("100"))
        self.assertEqual(transaction.transaction_type, "credit")
        self.assertEqual(transaction.amount, Decimal("100"))
        self.assertEqual(transaction.balance_after, Decimal("100"))
        self.assertEqual(transaction.reference_type, "stars_purchase")
        self.assertEqual(transaction.reference_id, "ref-1")

    def test_successful_payment_idempotent(self) -> None:
        """Повтор successful_payment не начисляет газ повторно."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session, "idempotent")
            self._seed_gas_wallet(session, player_id, balance=0)
            self._seed_pending_payment(
                session, player_id, reference_id="ref-1", gas_amount=100,
                amount_stars=80,
            )

        payment_update = {
            "message": {
                "successful_payment": {
                    "invoice_payload": "ref-1",
                    "telegram_payment_charge_id": "charge-1",
                }
            }
        }
        handle_successful_payment(payment_update)
        handle_successful_payment(payment_update)  # повторный webhook

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(GasWallet).where(GasWallet.player_id == player_id)
            )
            transactions_count = session.scalar(
                select(func.count())
                .select_from(GasTransaction)
                .where(GasTransaction.reference_id == "ref-1")
            )
        self.assertEqual(wallet.balance, Decimal("100"))
        self.assertEqual(transactions_count, 1)