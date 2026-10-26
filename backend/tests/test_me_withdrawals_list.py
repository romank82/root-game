"""Тесты GET /api/v1/me/withdrawals (11.7-a): список своих заявок.

Инфраструктура — паттерн test_admin_withdrawals.py: на каждый тест свежая
disposable SQLite + alembic upgrade head; SessionLocal патчится в каналы
withdrawal_service.SessionLocal (прямые импорты) и app.db.SessionLocal
(ленивые импорты). Сеть TON не вызывается — заявки сидятся напрямую.

Покрытие:
  1. test_list: 2 свои заявки (pending/confirmed) + 1 чужая -> total=2,
     только свои; игровые поля на месте, админские поля не отдаются.
  2. test_list_empty: у игрока нет заявок -> total=0, withdrawals=[].
  3. test_pagination: 3 заявки, limit=2 -> 2 (страница 1) + 1 (страница 2),
     total=3; порядок новее сверху (created_at desc).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app import withdrawal_service
from app.models import GamePlayer, WithdrawalRequest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Валидный тестнет-адрес TON (как в test_withdrawal_service.py).
VALID_TON_ADDRESS = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"


class MeWithdrawalsListTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.withdrawal_service = withdrawal_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite + alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-me-withdrawals-list-tests-"
        )
        self.database_path = (
            Path(self._temporary_directory.name) / "me_withdrawals_list.sqlite3"
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
            patch.object(
                self.withdrawal_service, "SessionLocal", self.SessionLocal
            ),
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
        """Игрок GamePlayer со статусом active."""
        player_id = f"me-withdrawal-player-{uuid.uuid4().hex[:12]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name="Me withdrawal list test",
                auth_provider="demo",
                external_id=f"test-me-withdrawal-{uuid.uuid4().hex}",
                status="active",
            )
        )
        session.flush()
        return player_id

    def _seed_withdrawal(
        self,
        session,
        player_id: str,
        *,
        status: str,
        amount_root: int = 100,
        created_at: datetime | None = None,
    ) -> str:
        """Заявка игрока напрямую (для списка; холд не эмулируется)."""
        withdrawal_id = f"withdrawal-{uuid.uuid4().hex[:12]}"
        session.add(
            WithdrawalRequest(
                id=withdrawal_id,
                player_id=player_id,
                amount_root=amount_root,
                to_address=VALID_TON_ADDRESS,
                status=status,
                created_at=created_at,
            )
        )
        session.flush()
        return withdrawal_id

    def _list(self, player_id: str, limit: int = 50, offset: int = 0):
        """Прямой вызов сервиса (как вызывается из GET-маршрута)."""
        return self.withdrawal_service.list_player_withdrawals(
            player_id=player_id,
            limit=limit,
            offset=offset,
        )

    # ---- Тесты --------------------------------------------------------------

    def test_list(self) -> None:
        """2 свои + 1 чужая -> total=2, только свои, игровые поля на месте."""
        with self.SessionLocal.begin() as session:
            player = self._make_player(session)
            other_player = self._make_player(session)
            pending_id = self._seed_withdrawal(session, player, status="pending")
            confirmed_id = self._seed_withdrawal(
                session, player, status="confirmed"
            )
            # Чужая заявка не должна попадать в список игрока.
            self._seed_withdrawal(session, other_player, status="pending")

        result = self._list(player)

        self.assertEqual(result["total"], 2)
        self.assertEqual(result["limit"], 50)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(
            {row["withdrawalId"] for row in result["withdrawals"]},
            {pending_id, confirmed_id},
        )

        first = result["withdrawals"][0]
        # Игровые поля контракта (11.7-a) на месте.
        for field in (
            "withdrawalId",
            "amountRoot",
            "toAddress",
            "status",
            "tonTxHash",
            "reason",
            "createdAt",
            "updatedAt",
        ):
            self.assertIn(field, first)
        # Админские/внутренние поля игроку не отдаются.
        for field in ("id", "playerId", "batchId", "adminId"):
            self.assertNotIn(field, first)

        self.assertEqual(first["toAddress"], VALID_TON_ADDRESS)
        self.assertEqual(first["amountRoot"], 100)
        self.assertEqual(first["tonTxHash"], None)
        self.assertEqual(first["reason"], None)

    def test_list_empty(self) -> None:
        """У игрока нет заявок -> total=0, withdrawals=[]."""
        with self.SessionLocal.begin() as session:
            player = self._make_player(session)

        result = self._list(player)

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["withdrawals"], [])
        self.assertEqual(result["limit"], 50)
        self.assertEqual(result["offset"], 0)

    def test_pagination(self) -> None:
        """3 заявки: limit=2 -> 2 и 1; total=3; порядок новее сверху."""
        with self.SessionLocal.begin() as session:
            player = self._make_player(session)
            for index, amount in enumerate((100, 101, 102)):
                self._seed_withdrawal(
                    session,
                    player,
                    status="pending",
                    amount_root=amount,
                    created_at=datetime(2026, 10, 1, 10, 0, index),
                )

        first_page = self._list(player, limit=2, offset=0)
        self.assertEqual(first_page["total"], 3)
        self.assertEqual(first_page["limit"], 2)
        self.assertEqual(first_page["offset"], 0)
        self.assertEqual(len(first_page["withdrawals"]), 2)

        second_page = self._list(player, limit=2, offset=2)
        self.assertEqual(len(second_page["withdrawals"]), 1)
        self.assertEqual(second_page["offset"], 2)

        # created_at desc: 10:00:02 (102) -> 10:00:01 (101) -> 10:00:00 (100).
        all_amounts = [
            row["amountRoot"]
            for row in first_page["withdrawals"] + second_page["withdrawals"]
        ]
        self.assertEqual(all_amounts, [102, 101, 100])

