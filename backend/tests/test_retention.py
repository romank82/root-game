"""Retention 30 дней (Sprint DB-Audit-2).

Проверяет только логику очистки cleanup_old_records() без поднятия
планировщика APScheduler:

  1. Старый PlayerEvent (31 день) удаляется, свежий (1 день) — остаётся.
  2. Старый AppError удаляется.
  3. Старый WalletTransaction НЕ удаляется (финансы — immutable ledger).

Инфраструктура — изолированный temp-SQLite + Base.metadata.create_all;
SessionLocal модуля app.retention патчится на тестовую сессию. Внешние
FK не включаются (PRAGMA foreign_keys по умолчанию OFF), поэтому
вставляются минимальные строки без полного дерева родителей.
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import AppError, PlayerEvent, WalletTransaction
from app.retention import cleanup_old_records


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


class RetentionCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-retention-tests-"
        )
        database_path = Path(cls._temporary_directory.name) / "retention.sqlite3"
        cls.engine = create_engine(
            f"sqlite:///{database_path}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(cls.engine)

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        import app.retention as retention_module

        cls._session_local_patch = patch.object(
            retention_module, "SessionLocal", cls.SessionLocal
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _insert_player_event(self, created_at: datetime) -> str:
        event_id = _new_id("player-event")
        with self.SessionLocal.begin() as session:
            session.add(
                PlayerEvent(
                    id=event_id,
                    player_id=_new_id("player"),
                    event_type="auth.login",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
        return event_id

    def test_old_player_event_deleted_new_kept(self):
        now = self._now()
        old_id = self._insert_player_event(now - timedelta(days=31))
        new_id = self._insert_player_event(now - timedelta(days=1))

        deleted = cleanup_old_records()

        with self.SessionLocal() as session:
            remaining = set(
                session.scalars(select(PlayerEvent.id)).all()
            )

        self.assertNotIn(old_id, remaining)
        self.assertIn(new_id, remaining)
        self.assertGreaterEqual(deleted.get("player_events", 0), 1)

    def test_old_app_error_deleted(self):
        now = self._now()
        error_id = _new_id("app-error")
        with self.SessionLocal.begin() as session:
            session.add(
                AppError(
                    id=error_id,
                    correlation_id=_new_id("corr"),
                    severity="error",
                    error_type="TestError",
                    message="boom",
                    created_at=now - timedelta(days=31),
                    updated_at=now - timedelta(days=31),
                )
            )

        deleted = cleanup_old_records()

        with self.SessionLocal() as session:
            remaining = set(session.scalars(select(AppError.id)).all())

        self.assertNotIn(error_id, remaining)
        self.assertGreaterEqual(deleted.get("app_errors", 0), 1)

    def test_old_wallet_transaction_kept(self):
        # Финансовая проводка (WalletTransaction) НЕ должна удаляться даже
        # будучи старше 30 дней — это immutable ledger (AGENTS.md).
        now = self._now()
        tx_id = _new_id("wallet-transaction")
        with self.SessionLocal.begin() as session:
            session.add(
                WalletTransaction(
                    id=tx_id,
                    wallet_id=_new_id("wallet"),
                    amount=100,
                    balance_after=100,
                    transaction_type="credit",
                    reason="test",
                    created_at=now - timedelta(days=31),
                    updated_at=now - timedelta(days=31),
                )
            )

        cleanup_old_records()

        with self.SessionLocal() as session:
            remaining = set(
                session.scalars(select(WalletTransaction.id)).all()
            )

        self.assertIn(tx_id, remaining)


if __name__ == "__main__":
    unittest.main()