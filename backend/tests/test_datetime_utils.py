"""Unit + интеграционные тесты datetime-нормализации (datetime-fix).

`app/datetime_utils.ensure_utc`: naive-datetime → aware-UTC, aware не
меняется, None → None. Это не pydantic-валидация payload'ов, а
нормализация значений, прочитанных из БД.

Интеграция (реальный SQLite/alembic): SQLite возвращает naive datetime
даже для DateTime(timezone=True). Executor заявки кошелька с таким
`expires_at` не должен падать с TypeError, а корректно обнаруживать
истёкший срок (HTTP 409).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.datetime_utils import ensure_utc

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class EnsureUtcTests(unittest.TestCase):
    """Unit: нормализация naive/aware/None."""

    def test_naive_datetime_is_converted_to_aware_utc_with_same_wall_clock(self) -> None:
        naive = datetime(2026, 10, 8, 12, 0, 0)
        result = ensure_utc(naive)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.utcoffset(), timedelta(0))
        self.assertEqual(result.hour, 12)  # naive трактуется как UTC

    def test_aware_utc_datetime_is_left_untouched(self) -> None:
        aware = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)
        self.assertIs(ensure_utc(aware), aware)

    def test_aware_non_utc_datetime_is_left_untouched(self) -> None:
        aware = datetime(2026, 10, 8, 15, 0, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertIs(ensure_utc(aware), aware)

    def test_none_passes_through(self) -> None:
        self.assertIsNone(ensure_utc(None))


class ApprovalExecutorDatetimeIntegrationTests(unittest.TestCase):
    """Реальный SQLite/alembic: executor не падает на naive `expires_at`.

    Данные вставляются aware-UTC, читаются назад naive (SQLite-quirk для
    DateTime(timezone=True)) — ровно та ситуация, что роняла executor'ы
    заявок с TypeError на локальном dev.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-datetime-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "datetime-fix.sqlite3"
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
        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def test_wallet_executor_handles_naive_expires_at_without_typeerror(self) -> None:
        from app.admin_player_wallet import execute_player_wallet_adjustment
        from app.models import AdminApprovalRequest

        suffix = uuid.uuid4().hex
        approval_id = f"approval-{suffix}"

        with self.SessionLocal.begin() as session:
            session.add(
                AdminApprovalRequest(
                    id=approval_id,
                    status="approved",
                    requested_by_admin_id=f"admin-{suffix}",
                    required_permission_code="players.wallet_adjust",
                    action_type="player.wallet_credit",
                    target_entity_type="player",
                    target_entity_id=f"player-{suffix}",
                    payload_snapshot={
                        "playerId": f"player-{suffix}",
                        "direction": "credit",
                        "amount": 100,
                    },
                    reason="datetime-fix integration",
                    request_id=f"request-{suffix}",
                    expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
                )
            )

        # SQLite-quirk: прочитанный назад expires_at — naive.
        with self.SessionLocal() as session:
            approval = session.get(AdminApprovalRequest, approval_id)
            self.assertIsNotNone(approval.expires_at)
            assert approval.expires_at is not None
            self.assertIsNone(approval.expires_at.tzinfo)

        # Нормализация в UTC: срок виден, TypeError не возникает.
        import app.admin_player_wallet as wallet_module

        with patch.object(wallet_module, "SessionLocal", self.SessionLocal):
            with self.assertRaises(HTTPException) as caught:
                execute_player_wallet_adjustment(
                    approval_id=approval_id,
                    request=SimpleNamespace(client=None),
                    admin=SimpleNamespace(id=f"approver-{suffix}"),
                )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("истёк", caught.exception.detail)
