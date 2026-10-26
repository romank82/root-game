"""Тесты withdrawal_service (этап 11.5-a): заявка на вывод ROOT в TON.

Инфраструктура — паттерн test_stars_service.py: на каждый тест свежая
disposable SQLite + alembic upgrade head; SessionLocal патчится в ДВА канала
(app.db — ленивые импорты; withdrawal_service.SessionLocal — прямой импорт).
Сеть TON не вызывается вообще (валидация адреса — локальная, pytoniq-core).

Покрытие:
  1. Успешная заявка: pending + debit-холд withdrawal_hold + баланс 900;
  2. Недостаточно ROOT -> 409, баланс не меняется, заявок/проводок нет;
  3. withdrawal_restricted -> 403, ничего не списывается;
  4. withdrawal_enabled=False -> 503 (CMS-переключатель);
  5. amount_root < ton.min_amount_root -> 422;
  6. Сумма + существующий холд-объём > ton.daily_withdrawal_limit -> 429.
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

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app import withdrawal_service
from app.mission_engine import MissionEngineError
from app.models import (
    AdminUser,
    GamePlayer,
    PlayerRestriction,
    SystemSetting,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Валидный тестнет-адрес TON (kQA…), уже в канонической форме: pytoniq
# канонизирует его в себя же (тестнет-флаг сохраняется).
VALID_TON_ADDRESS = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"


class WithdrawalServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модуль; SessionLocal патчится на свежую БД в setUp."""
        cls.withdrawal_service = withdrawal_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-withdrawal-tests-"
        )
        self.database_path = (
            Path(self._temporary_directory.name) / "withdrawal.sqlite3"
        )
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
        # withdrawal_service.SessionLocal (прямой импорт в момент import).
        self._session_local_patches = [
            patch("app.db.SessionLocal", self.SessionLocal),
            patch.object(
                self.withdrawal_service, "SessionLocal", self.SessionLocal
            ),
        ]
        for session_local_patch in self._session_local_patches:
            session_local_patch.start()

    def tearDown(self) -> None:
        for session_local_patch in self._session_local_patches:
            session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------------

    def _make_player(self, session) -> str:
        """Игрок GamePlayer со статусом active."""
        player_id = f"withdrawal-player-{uuid.uuid4().hex[:12]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name="Withdrawal test",
                auth_provider="demo",
                external_id=f"test-withdrawal-{uuid.uuid4().hex}",
                status="active",
            )
        )
        session.flush()
        return player_id

    def _seed_setting(
        self, session, key: str, value_json, value_type: str
    ) -> None:
        """Активная SystemSetting (CMS-first)."""
        session.add(
            SystemSetting(
                key=key,
                value_json=value_json,
                value_type=value_type,
                category="ton",
                title=key,
                description="Seeded by withdrawal_service test",
                is_sensitive=False,
                status="active",
            )
        )
        session.flush()

    def _seed_withdrawal_settings(
        self,
        session,
        *,
        enabled: bool = True,
        min_amount: int = 10,
        daily: int = 5000,
    ) -> None:
        """Три CMS-ключа вывода: ton.withdrawal_enabled / min / daily."""
        self._seed_setting(
            session,
            withdrawal_service.WITHDRAWAL_ENABLED_KEY,
            enabled,
            "boolean",
        )
        self._seed_setting(
            session,
            withdrawal_service.WITHDRAWAL_MIN_AMOUNT_KEY,
            min_amount,
            "integer",
        )
        self._seed_setting(
            session,
            withdrawal_service.WITHDRAWAL_DAILY_LIMIT_KEY,
            daily,
            "integer",
        )

    def _seed_wallet(self, session, player_id: str, balance: int) -> str:
        """ROOT-кошелёк игрока с заданным балансом."""
        wallet_id = f"wallet-{uuid.uuid4().hex[:12]}"
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
        return wallet_id

    def _seed_withdrawal_restricted(self, session, player_id: str) -> None:
        """Активное ограничение withdrawal_restricted (нужен admin)."""
        admin_id = f"admin-{uuid.uuid4().hex[:12]}"
        session.add(
            AdminUser(
                id=admin_id,
                username=f"withdrawal-admin-{uuid.uuid4().hex[:8]}",
                password_hash="not-a-real-hash",
                role="super_admin",
                is_super_admin=True,
                is_active=True,
            )
        )
        session.add(
            PlayerRestriction(
                id=f"pr-{uuid.uuid4().hex[:12]}",
                player_id=player_id,
                restriction_type="withdrawal_restricted",
                status="active",
                reason="Withdrawal service test fixture",
                admin_id=admin_id,
                starts_at=None,
                expires_at=None,
            )
        )
        session.flush()

    def _seed_withdrawal_hold(
        self,
        session,
        player_id: str,
        *,
        wallet_balance: int,
        hold_amount: int,
    ) -> str:
        """Прямой seed существующего холда: заявка pending + debit-проводка."""
        wallet_id = self._seed_wallet(session, player_id, wallet_balance)
        request_id = f"withdrawal-{uuid.uuid4().hex[:12]}"
        wallet = session.get(Wallet, wallet_id)
        wallet.available_balance -= hold_amount
        session.add(
            WalletTransaction(
                id=f"wt-{uuid.uuid4().hex[:12]}",
                wallet_id=wallet_id,
                amount=hold_amount,
                balance_after=wallet.available_balance,
                transaction_type="debit",
                reason=f"Withdrawal hold {request_id}",
                reference_type=withdrawal_service.WITHDRAWAL_HOLD_REFERENCE_TYPE,
                reference_id=request_id,
                metadata_json={"toAddress": VALID_TON_ADDRESS},
            )
        )
        session.add(
            WithdrawalRequest(
                id=request_id,
                player_id=player_id,
                amount_root=hold_amount,
                to_address=VALID_TON_ADDRESS,
                status="pending",
            )
        )
        session.flush()
        return request_id

    # ---- Тесты ---------------------------------------------------------------

    def test_successful_withdrawal_request(self) -> None:
        """Заявка pending + debit-холд withdrawal_hold + баланс 900."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session)
            self._seed_wallet(session, player_id, 1000)

        result = self.withdrawal_service.create_withdrawal_request(
            player_id, 100, VALID_TON_ADDRESS
        )

        self.assertEqual(result["amountRoot"], 100)
        self.assertEqual(result["toAddress"], VALID_TON_ADDRESS)
        self.assertEqual(result["status"], "pending")
        self.assertTrue(result["withdrawalId"].startswith("withdrawal-"))

        with self.SessionLocal() as session:
            request = session.get(WithdrawalRequest, result["withdrawalId"])
            self.assertIsNotNone(request)
            self.assertEqual(request.player_id, player_id)
            self.assertEqual(request.amount_root, 100)
            self.assertEqual(request.status, "pending")
            self.assertEqual(request.to_address, VALID_TON_ADDRESS)

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            self.assertEqual(wallet.available_balance, 900)

            hold = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.reference_type
                    == withdrawal_service.WITHDRAWAL_HOLD_REFERENCE_TYPE,
                    WalletTransaction.reference_id == result["withdrawalId"],
                )
            )
            self.assertIsNotNone(hold)
            self.assertEqual(hold.transaction_type, "debit")
            self.assertEqual(hold.amount, 100)
            self.assertEqual(hold.balance_after, 900)

    def test_insufficient_balance(self) -> None:
        """Баланса не хватает -> 409, ничего не изменяется."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session)
            self._seed_wallet(session, player_id, 50)

        with self.assertRaises(MissionEngineError) as context:
            self.withdrawal_service.create_withdrawal_request(
                player_id, 100, VALID_TON_ADDRESS
            )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail, "Недостаточно ROOT.")

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            self.assertEqual(wallet.available_balance, 50)
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(WithdrawalRequest)
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(WalletTransaction)
                ),
                0,
            )

    def test_withdrawal_restricted(self) -> None:
        """Активное ограничение withdrawal_restricted -> 403, списаний нет."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session)
            self._seed_wallet(session, player_id, 1000)
            self._seed_withdrawal_restricted(session, player_id)

        with self.assertRaises(MissionEngineError) as context:
            self.withdrawal_service.create_withdrawal_request(
                player_id, 100, VALID_TON_ADDRESS
            )
        self.assertEqual(context.exception.status_code, 403)
        self.assertEqual(
            context.exception.detail, "Вывод средств для вас ограничен."
        )

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            self.assertEqual(wallet.available_balance, 1000)
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(WithdrawalRequest)
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(WalletTransaction)
                ),
                0,
            )

    def test_withdrawal_disabled(self) -> None:
        """CMS-переключатель ton.withdrawal_enabled=False -> 503."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session, enabled=False)
            self._seed_wallet(session, player_id, 1000)

        with self.assertRaises(MissionEngineError) as context:
            self.withdrawal_service.create_withdrawal_request(
                player_id, 100, VALID_TON_ADDRESS
            )
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(context.exception.detail, "Вывод ROOT в TON отключён.")

    def test_below_minimum_amount(self) -> None:
        """Сумма меньше ton.min_amount_root -> 422, списаний нет."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session, min_amount=10)
            self._seed_wallet(session, player_id, 1000)

        with self.assertRaises(MissionEngineError) as context:
            self.withdrawal_service.create_withdrawal_request(
                player_id, 5, VALID_TON_ADDRESS
            )
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("минимальной", context.exception.detail)

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            self.assertEqual(wallet.available_balance, 1000)

    def test_daily_limit_exceeded(self) -> None:
        """Существующий холд 90 + новая сумма 20 > лимит 100 -> 429."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session, daily=100)
            self._seed_withdrawal_hold(
                session,
                player_id,
                wallet_balance=1000,
                hold_amount=90,
            )

        with self.assertRaises(MissionEngineError) as context:
            self.withdrawal_service.create_withdrawal_request(
                player_id, 20, VALID_TON_ADDRESS
            )
        self.assertEqual(context.exception.status_code, 429)
        self.assertIn("дневной лимит", context.exception.detail)

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            self.assertEqual(wallet.available_balance, 910)
            self.assertEqual(
                session.scalar(
                    select(func.count()).select_from(WithdrawalRequest)
                ),
                1,
            )