"""Тесты deposit_service (Sprint 1.5): зачисление входящего ROOT-jetton.

Инфраструктура — паттерн test_withdrawal_service.py: на каждый тест свежая
disposable SQLite + alembic upgrade head; SessionLocal патчится в два канала
(app.db — ленивый импорт; deposit_service использует переданную сессию, но
поллер в будущем — SessionLocal, поэтому патчим оба).

Сеть TON не вызывается: deposit_service.process_incoming_transfer принимает
уже распарсенный tx-dict, тесты передают его напрямую.

Покрытие:
  1. test_successful_deposit — confirmed, баланс вырос, ledger-credit;
  2. test_idempotent_duplicate_tx — тот же tx_hash -> баланс вырос один раз;
  3. test_wrong_jetton_master — rejected, баланс не меняется;
  4. test_below_minimum — rejected, баланс не меняется;
  5. test_deposit_disabled — rejected, баланс не меняется;
  6. test_no_ton_wallet — pending (player_id None), баланс не меняется;
  7. test_parallel_deposits — два разных tx_hash -> оба зачислены;
  8. test_wrong_destination — to_address != ton.deposit_wallet -> rejected;
  9. test_deposit_wallet_not_configured — пустой ton.deposit_wallet -> rejected;
 10. test_destination_friendly_matches_raw — EQA… в CMS == 0:hex в tx;
 11. test_repeat_after_wallet_change_is_idempotent — повторная обработка
     того же перевода после смены ton.deposit_wallet не падает и не
     перезачисляет (идемпотентность проверяется первой).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app import deposit_service
from app.mission_engine import MissionEngineError
from app.models import (
    GamePlayer,
    JettonDeposit,
    SystemSetting,
    TonWallet,
    Wallet,
    WalletTransaction,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

NANO_PER_ROOT = 100_000_000
ROOT_MASTER = "0:" + "a" * 64
# Адрес депозитного кошелька (CMS ton.deposit_wallet) для тестов.
DEPOSIT_WALLET_RAW = "0:" + "c" * 64
# Та же форма, что хранит CMS в реальности (user-friendly bounceable).
DEPOSIT_WALLET_FRIENDLY = "EQDMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzDA5"
OTHER_MASTER = "0:" + "b" * 64


class DepositServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.deposit_service = deposit_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-deposit-tests-"
        )
        self.database_path = (
            Path(self._temporary_directory.name) / "deposit.sqlite3"
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
        self._session_local_patches = [
            patch("app.db.SessionLocal", self.SessionLocal),
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
        """Игрок GamePlayer (active) + ROOT-кошелёк с нулевым балансом."""
        player_id = f"deposit-player-{uuid.uuid4().hex[:12]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name="Deposit test",
                auth_provider="demo",
                external_id=f"test-deposit-{uuid.uuid4().hex}",
                status="active",
            )
        )
        session.flush()
        session.add(
            Wallet(
                id=f"wallet-{uuid.uuid4().hex[:12]}",
                player_id=player_id,
                currency="ROOT",
                available_balance=0,
                locked_balance=0,
                available_balance_nano=0,
                locked_balance_nano=0,
            )
        )
        session.flush()
        return player_id

    def _bind_ton_wallet(self, session, player_id: str, address: str) -> str:
        """Активный TonWallet игрока (адрес отправителя для сопоставления)."""
        ton_wallet_id = f"ton-wallet-{uuid.uuid4().hex[:12]}"
        session.add(
            TonWallet(
                id=ton_wallet_id,
                player_id=player_id,
                address=address,
                status="active",
            )
        )
        session.flush()
        return ton_wallet_id

    def _seed_setting(self, session, key: str, value_json, value_type: str) -> None:
        """Активная SystemSetting (CMS-first), идемпотентно.

        Миграции уже создают ton.*-строки из каталога, поэтому при наличии
        обновляем ТОЛЬКО value_json (+status): метаданные остаются
        каталоговыми, иначе admin_system_settings отдаёт 409.
        """
        existing = session.get(SystemSetting, key)
        if existing is not None:
            existing.value_json = value_json
            existing.status = "active"
        else:
            session.add(
                SystemSetting(
                    key=key,
                    value_json=value_json,
                    value_type=value_type,
                    category="ton",
                    title=key,
                    description="Seeded by deposit_service test",
                    is_sensitive=False,
                    status="active",
                )
            )
        session.flush()

    def _enable_deposit(
        self, session, min_root: int = 1, deposit_wallet: str = DEPOSIT_WALLET_RAW
    ) -> None:
        self._seed_setting(session, deposit_service.DEPOSIT_ENABLED_KEY, True, "boolean")
        self._seed_setting(
            session, deposit_service.DEPOSIT_MIN_AMOUNT_KEY, min_root, "integer"
        )
        self._seed_setting(session, deposit_service.DEPOSIT_WALLET_KEY, deposit_wallet, "string")

    def _make_tx(
        self,
        from_address: str,
        amount_nano: int = NANO_PER_ROOT,
        tx_hash: str | None = None,
        jetton_master: str = ROOT_MASTER,
        to_address: str = DEPOSIT_WALLET_RAW,
    ) -> dict:
        """Распарсенный incoming-перевод (выход ton_service.parse_jetton_transfer)."""
        return {
            "tx_hash": tx_hash or f"tx-{uuid.uuid4().hex}",
            "lt": 12345,
            "query_id": 7,
            "from_address": from_address,
            "to_address": to_address,
            "jetton_master": jetton_master,
            "amount_nano": amount_nano,
            "raw_payload": {"mock": True},
        }

    def _wallet_nano(self, player_id: str) -> int:
        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            return wallet.available_balance_nano or 0

    def _process(self, tx: dict) -> str:
        """Прогнать process_incoming_transfer в отдельной транзакции."""
        with self.SessionLocal.begin() as session:
            deposit = self.deposit_service.process_incoming_transfer(session, tx)
            return deposit.id

    def _get_deposit(self, deposit_id: str) -> JettonDeposit:
        with self.SessionLocal() as session:
            return session.get(JettonDeposit, deposit_id)

    # ---- Тесты ---------------------------------------------------------------

    def test_successful_deposit(self) -> None:
        """Успех: confirmed, баланс вырос на amount, ledger-credit записан."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session, min_root=1)

        tx = self._make_tx("0:" + "1" * 64, amount_nano=5 * NANO_PER_ROOT)

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "confirmed")
        self.assertEqual(deposit.player_id, player_id)
        self.assertEqual(deposit.tx_hash, tx["tx_hash"])
        self.assertIsNotNone(deposit.confirmed_at)
        self.assertEqual(self._wallet_nano(player_id), 5 * NANO_PER_ROOT)

        with self.SessionLocal() as session:
            credit = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.reference_type == "jetton_deposit",
                    WalletTransaction.reference_id == tx["tx_hash"],
                )
            )
        self.assertIsNotNone(credit)
        self.assertEqual(credit.transaction_type, "credit")
        self.assertEqual(credit.amount_nano, 5 * NANO_PER_ROOT)

    def test_idempotent_duplicate_tx(self) -> None:
        """Тот же tx_hash дважды -> баланс вырос один раз, deposit один."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session)

        tx = self._make_tx(
            "0:" + "1" * 64, amount_nano=3 * NANO_PER_ROOT, tx_hash="dup-tx"
        )

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            first_id = self._process(tx)
            second_id = self._process(tx)

        self.assertEqual(first_id, second_id)
        self.assertEqual(self._wallet_nano(player_id), 3 * NANO_PER_ROOT)

        with self.SessionLocal() as session:
            count = len(
                session.scalars(
                    select(JettonDeposit).where(
                        JettonDeposit.tx_hash == "dup-tx"
                    )
                ).all()
            )
        self.assertEqual(count, 1)

    def test_wrong_jetton_master(self) -> None:
        """jetton_master != ROOT -> rejected, баланс не меняется."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session)

        tx = self._make_tx(
            "0:" + "1" * 64, amount_nano=5 * NANO_PER_ROOT,
            jetton_master=OTHER_MASTER,
        )

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "rejected")
        self.assertEqual(deposit.raw_payload.get("reason"), "wrong_jetton")
        self.assertEqual(self._wallet_nano(player_id), 0)

    def test_below_minimum(self) -> None:
        """amount < ton.min_deposit_root -> rejected, баланс не меняется."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session, min_root=10)

        tx = self._make_tx("0:" + "1" * 64, amount_nano=5 * NANO_PER_ROOT)

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "rejected")
        self.assertEqual(deposit.raw_payload.get("reason"), "below_minimum")
        self.assertEqual(self._wallet_nano(player_id), 0)

    def test_deposit_disabled(self) -> None:
        """ton.deposit_enabled=False -> rejected, баланс не меняется."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._seed_setting(
                session, deposit_service.DEPOSIT_ENABLED_KEY, False, "boolean"
            )

        tx = self._make_tx("0:" + "1" * 64, amount_nano=5 * NANO_PER_ROOT)

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "rejected")
        self.assertEqual(deposit.raw_payload.get("reason"), "disabled")
        self.assertEqual(self._wallet_nano(player_id), 0)

    def test_no_ton_wallet(self) -> None:
        """Адрес не привязан к игроку -> pending (player_id=None), баланс 0."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._enable_deposit(session)

        tx = self._make_tx("0:" + "9" * 64, amount_nano=5 * NANO_PER_ROOT)

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "pending")
        self.assertIsNone(deposit.player_id)
        self.assertEqual(self._wallet_nano(player_id), 0)

    def test_parallel_deposits(self) -> None:
        """Два разных tx_hash на одного игрока -> оба зачислены (сумма)."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session)

        tx_a = self._make_tx(
            "0:" + "1" * 64, amount_nano=2 * NANO_PER_ROOT, tx_hash="par-a"
        )
        tx_b = self._make_tx(
            "0:" + "1" * 64, amount_nano=3 * NANO_PER_ROOT, tx_hash="par-b"
        )

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_a = self._process(tx_a)
            deposit_b = self._process(tx_b)

        self.assertNotEqual(deposit_a, deposit_b)
        self.assertEqual(self._get_deposit(deposit_a).status, "confirmed")
        self.assertEqual(self._get_deposit(deposit_b).status, "confirmed")
        self.assertEqual(self._wallet_nano(player_id), 5 * NANO_PER_ROOT)

    def test_wrong_destination(self) -> None:
        """to_address != ton.deposit_wallet -> rejected, баланс не меняется."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session)

        tx = self._make_tx(
            "0:" + "1" * 64,
            amount_nano=5 * NANO_PER_ROOT,
            to_address="0:" + "d" * 64,
        )

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "rejected")
        self.assertEqual(deposit.raw_payload.get("reason"), "wrong_destination")
        self.assertEqual(self._wallet_nano(player_id), 0)

    def test_deposit_wallet_not_configured(self) -> None:
        """Пустой ton.deposit_wallet -> rejected, баланс не меняется."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._seed_setting(
                session, deposit_service.DEPOSIT_ENABLED_KEY, True, "boolean"
            )
            self._seed_setting(
                session, deposit_service.DEPOSIT_MIN_AMOUNT_KEY, 1, "integer"
            )
            self._seed_setting(
                session, deposit_service.DEPOSIT_WALLET_KEY, "", "string"
            )

        tx = self._make_tx("0:" + "1" * 64, amount_nano=5 * NANO_PER_ROOT)

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "rejected")
        self.assertEqual(
            deposit.raw_payload.get("reason"), "deposit_wallet_not_configured"
        )
        self.assertEqual(self._wallet_nano(player_id), 0)

    def test_destination_friendly_matches_raw(self) -> None:
        """CMS хранит EQA…, tx приносит 0:hex -> адреса считаются равными."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session, deposit_wallet=DEPOSIT_WALLET_FRIENDLY)

        tx = self._make_tx(
            "0:" + "1" * 64,
            amount_nano=5 * NANO_PER_ROOT,
            to_address=DEPOSIT_WALLET_RAW,
        )

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            deposit_id = self._process(tx)

        deposit = self._get_deposit(deposit_id)
        self.assertEqual(deposit.status, "confirmed")
        self.assertEqual(self._wallet_nano(player_id), 5 * NANO_PER_ROOT)

    def test_repeat_after_wallet_change_is_idempotent(self) -> None:
        """Повтор того же tx после смены deposit_wallet: без IntegrityError."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._bind_ton_wallet(session, player_id, "0:" + "1" * 64)
            self._enable_deposit(session)

        tx = self._make_tx(
            "0:" + "1" * 64, amount_nano=5 * NANO_PER_ROOT, tx_hash="same-tx"
        )

        with patch.object(
            self.deposit_service, "settings",
            SimpleNamespace(ton_root_jetton_master=ROOT_MASTER),
        ):
            first_id = self._process(tx)
            # Кошелёк приёма сменили: тот же перевод теперь «чужой адрес».
            with self.SessionLocal.begin() as session:
                self._seed_setting(
                    session, deposit_service.DEPOSIT_WALLET_KEY,
                    "0:" + "e" * 64, "string",
                )
            second_id = self._process(tx)

        # Ответ на повтор — уже записанная строка, а не rejected.
        self.assertEqual(first_id, second_id)
        self.assertEqual(self._wallet_nano(player_id), 5 * NANO_PER_ROOT)

    def test_normalize_address_for_compare(self) -> None:
        """Нормализация: raw/friendly/bounceable дают один ключ, мусор -> None."""
        normalize = self.deposit_service.normalize_address_for_compare
        self.assertEqual(
            normalize(DEPOSIT_WALLET_RAW), normalize(DEPOSIT_WALLET_FRIENDLY)
        )
        # Non-bounceable (UQ…) форма — тот же адрес.
        self.assertEqual(
            normalize("UQDMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzMzG38"),
            normalize(DEPOSIT_WALLET_RAW),
        )
        self.assertIsNone(normalize(None))
        self.assertIsNone(normalize(""))
        self.assertIsNone(normalize("не адрес"))

    def test_get_deposit_wallet_address(self) -> None:
        """CMS ton.deposit_wallet: пусто -> 503; заполнено -> адрес."""
        with self.SessionLocal() as session:
            with self.assertRaises(MissionEngineError) as context:
                self.deposit_service.get_deposit_wallet_address(session)
        self.assertEqual(context.exception.status_code, 503)

        with self.SessionLocal.begin() as session:
            self._seed_setting(
                session, deposit_service.DEPOSIT_WALLET_KEY,
                "0:" + "c" * 64, "string",
            )
        with self.SessionLocal() as session:
            self.assertEqual(
                self.deposit_service.get_deposit_wallet_address(session),
                "0:" + "c" * 64,
            )

