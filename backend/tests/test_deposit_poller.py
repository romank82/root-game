"""Тесты deposit_poller (Sprint 1.6): цикл поллинга (моки, без сети).

Инфраструктура — паттерн test_deposit_service: свежая disposable SQLite +
alembic upgrade head на каждый тест. Сеть TON не вызывается: _TonCenterProvider
патчится, parse_jetton_transfer/process_incoming_transfer мокаются.

Покрытие:
  1. test_poll_once_processes_new_tx — 2 tx, 2 parsed -> 2 зачёта, курсор сдвинут;
  2. test_poll_once_skips_non_jetton — parse None для одной -> process не вызван;
  3. test_poll_once_disabled — ton.deposit_enabled=False -> 0, get_transactions
     не вызывался;
  4. test_poll_once_no_deposit_wallet — ton.deposit_wallet="" -> 0;
  5. test_poll_once_updates_cursor — курсор = lt/hash последней tx.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import deposit_poller
from app.models import SystemSetting, TonPollCursor

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class _FakeProvider:
    """Заглушка _TonCenterProvider: get_transactions/parse — управляемые моки."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.transactions: list = []
        self.parsed: dict = {}
        self.get_transactions = AsyncMock(side_effect=self._get_transactions)
        self.parse_jetton_transfer = AsyncMock(side_effect=self._parse)
        self.aclose = AsyncMock()

    async def _get_transactions(self, *args, **kwargs):
        return self.transactions

    async def _parse(self, tx, session=None):
        return self.parsed.get(tx.get("hash"))


class DepositPollerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-poller-tests-"
        )
        self.database_path = (
            Path(self._temporary_directory.name) / "poller.sqlite3"
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

    # ---- Хелперы -------------------------------------------------------------

    def _seed_setting(self, session, key: str, value_json, value_type: str) -> None:
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
                    description="Seeded by deposit_poller test",
                    is_sensitive=False,
                    status="active",
                )
            )
        session.flush()

    def _enable_and_set_wallet(self, session, wallet: str = "0:" + "c" * 64) -> None:
        self._seed_setting(
            session, deposit_poller.DEPOSIT_ENABLED_KEY, True, "boolean"
        )
        self._seed_setting(session, "ton.deposit_wallet", wallet, "string")

    def _make_tx(self, h: str, lt) -> dict:
        # TonCenter отдаёт lt строкой (в тестах — как в реальном ответе).
        return {"hash": h, "lt": lt}

    def _run_poll(self, provider: "_FakeProvider") -> int:
        """poll_once с подменённым провайдером и валидным endpoint."""
        fake_settings = SimpleNamespace(
            ton_api_endpoint="https://testnet.toncenter.com/api/v2"
        )
        with patch.object(deposit_poller, "settings", fake_settings), patch.object(
            deposit_poller, "_TonCenterProvider", lambda endpoint: provider
        ):
            with self.SessionLocal() as session:
                return asyncio.run(deposit_poller.poll_once(session))

    def _cursor(self) -> TonPollCursor:
        with self.SessionLocal() as session:
            return session.get(TonPollCursor, deposit_poller.CURSOR_ID)

    # ---- Тесты ---------------------------------------------------------------

    def test_poll_once_processes_new_tx(self) -> None:
        """2 tx, оба parsed -> 2 зачёта, process вызван для каждого."""
        with self.SessionLocal.begin() as session:
            self._enable_and_set_wallet(session)

        provider = _FakeProvider("endpoint")
        provider.transactions = [self._make_tx("h2", "200"), self._make_tx("h1", "100")]
        provider.parsed = {"h1": {"tx_hash": "h1"}, "h2": {"tx_hash": "h2"}}

        with patch.object(deposit_poller, "process_incoming_transfer") as process:
            processed = self._run_poll(provider)

        self.assertEqual(processed, 2)
        self.assertEqual(process.call_count, 2)

    def test_poll_once_skips_non_jetton(self) -> None:
        """parse None для одной tx -> process вызван только для второй."""
        with self.SessionLocal.begin() as session:
            self._enable_and_set_wallet(session)

        provider = _FakeProvider("endpoint")
        provider.transactions = [self._make_tx("h2", "200"), self._make_tx("h1", "100")]
        provider.parsed = {"h2": {"tx_hash": "h2"}}  # h1 -> None

        with patch.object(deposit_poller, "process_incoming_transfer") as process:
            processed = self._run_poll(provider)

        self.assertEqual(processed, 1)
        self.assertEqual(process.call_count, 1)
        # Курсор всё равно сдвинут до последней tx (h2).
        cursor = self._cursor()
        self.assertEqual(cursor.last_lt, 200)
        self.assertIsInstance(cursor.last_lt, int)
        self.assertEqual(cursor.last_hash, "h2")

    def test_poll_once_disabled(self) -> None:
        """ton.deposit_enabled=False -> 0 и get_transactions не вызывался."""
        with self.SessionLocal.begin() as session:
            self._seed_setting(
                session, deposit_poller.DEPOSIT_ENABLED_KEY, False, "boolean"
            )

        provider = _FakeProvider("endpoint")
        provider.transactions = [self._make_tx("h1", "100")]

        processed = self._run_poll(provider)

        self.assertEqual(processed, 0)
        provider.get_transactions.assert_not_awaited()

    def test_poll_once_no_deposit_wallet(self) -> None:
        """ton.deposit_wallet='' -> 0 (get_deposit_wallet_address -> 503)."""
        with self.SessionLocal.begin() as session:
            self._seed_setting(
                session, deposit_poller.DEPOSIT_ENABLED_KEY, True, "boolean"
            )
            self._seed_setting(session, "ton.deposit_wallet", "", "string")

        provider = _FakeProvider("endpoint")
        processed = self._run_poll(provider)

        self.assertEqual(processed, 0)
        provider.get_transactions.assert_not_awaited()

    def test_poll_once_updates_cursor(self) -> None:
        """Курсор = lt/hash последней (самой новой) tx."""
        with self.SessionLocal.begin() as session:
            self._enable_and_set_wallet(session)

        provider = _FakeProvider("endpoint")
        provider.transactions = [
            self._make_tx("h3", "300"),
            self._make_tx("h2", "200"),
            self._make_tx("h1", "100"),
        ]
        provider.parsed = {
            "h1": {"tx_hash": "h1"},
            "h2": {"tx_hash": "h2"},
            "h3": {"tx_hash": "h3"},
        }

        with patch.object(deposit_poller, "process_incoming_transfer"):
            self._run_poll(provider)

        cursor = self._cursor()
        # lt в БД — BigInteger (int), хотя TonCenter отдаёт строку.
        self.assertEqual(cursor.last_lt, 300)
        self.assertIsInstance(cursor.last_lt, int)
        self.assertEqual(cursor.last_hash, "h3")

