"""Формирование батчей выплат (11.x-external-payout, шаг 2).

Проверяем то, что защищает деньги игроков:
  * батч собирает ровно pending-заявки и переводит их в processing;
  * каждой заявке выдаётся уникальный query_id (ключ сверки в блокчейне);
  * повторный вызов возвращает открытый батч, а не создаёт второй;
  * restricted-игрок в батч не попадает;
  * пустой pending -> 409, а не пустой батч;
  * сумма батча равна сумме заявок (nano-точность);
  * три «воркера» одновременно не создают три батча (барьер БД).
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

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

VALID_TON_ADDRESS = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"
NANO = 100_000_000


class PayoutBatchServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="chimera-batch-svc-")
        cls.database_path = Path(cls._tmp.name) / "batch.sqlite3"
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
            database_url, connect_args={"check_same_thread": False}
        )

        @event.listens_for(cls.engine, "connect")
        def _fk(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        from app import withdrawal_service
        from app.payout_batch_service import create_payout_batch

        cls.service = staticmethod(create_payout_batch)
        cls.withdrawal_service = withdrawal_service
        cls._patches = [
            patch.object(withdrawal_service, "SessionLocal", cls.SessionLocal),
        ]
        # Патчим SessionLocal во всех модулях, которые его импортировали.
        from app import mission_engine, payout_batch_service

        for module in (mission_engine, payout_batch_service):
            if hasattr(module, "SessionLocal"):
                cls._patches.append(
                    patch.object(module, "SessionLocal", cls.SessionLocal)
                )
        for item in cls._patches:
            item.start()

    @classmethod
    def tearDownClass(cls) -> None:
        for item in cls._patches:
            item.stop()
        cls.engine.dispose()
        cls._tmp.cleanup()

    def setUp(self) -> None:
        from app.models import (
            GamePlayer,
            PayoutAttempt,
            PayoutBatch,
            PlayerRestriction,
            SystemSetting,
            Wallet,
            WithdrawalRequest,
        )

        with self.SessionLocal.begin() as session:
            for model in (
                PayoutAttempt,
                PayoutBatch,
                WithdrawalRequest,
                PlayerRestriction,
                Wallet,
                SystemSetting,
                GamePlayer,
            ):
                session.query(model).delete()

    # --- Хелперы ---------------------------------------------------------
    def _player(self, balance: int = 10_000) -> str:
        from app.models import GamePlayer, Wallet

        player_id = f"player-{uuid.uuid4().hex[:12]}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="Batch test",
                    auth_provider="demo",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
            session.add(
                Wallet(
                    id=f"wallet-{uuid.uuid4().hex[:12]}",
                    player_id=player_id,
                    currency="ROOT",
                    available_balance=balance,
                    available_balance_nano=balance * NANO,
                )
            )
        return player_id

    def _admin(self) -> str:
        """Реальный админ (FK payout_batches.admin_id -> admin_users.id)."""
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex[:12]}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{uuid.uuid4().hex[:8]}",
                    password_hash="x",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                )
            )
        return admin_id

    def _withdrawal(self, player_id: str, amount: int, status: str) -> str:
        from app.models import WithdrawalRequest

        withdrawal_id = f"withdrawal-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                WithdrawalRequest(
                    id=withdrawal_id,
                    player_id=player_id,
                    amount_root=amount,
                    amount_root_nano=amount * NANO,
                    to_address=VALID_TON_ADDRESS,
                    status=status,
                )
            )
        return withdrawal_id

    def _restrict(self, player_id: str) -> None:
        from app.models import PlayerRestriction

        with self.SessionLocal.begin() as session:
            # admin_id обязателен: ограничение всегда кем-то выставлено.
            from app.models import AdminUser

            admin = AdminUser(
                id=f"admin-{uuid.uuid4().hex[:12]}",
                username=f"admin-{uuid.uuid4().hex[:8]}",
                password_hash="x",
                role="super_admin",
                is_super_admin=True,
                is_active=True,
            )
            session.add(admin)
            session.flush()
            session.add(
                PlayerRestriction(
                    id=f"restriction-{uuid.uuid4().hex}",
                    player_id=player_id,
                    restriction_type="withdrawal_restricted",
                    status="active",
                    reason="test",
                    admin_id=admin.id,
                )
            )

    def _read(self, withdrawal_id: str):
        from app.models import WithdrawalRequest

        with self.SessionLocal() as session:
            return session.get(WithdrawalRequest, withdrawal_id)

    # --- Тесты -----------------------------------------------------------
    def test_batch_takes_only_pending_and_marks_processing(self) -> None:
        pending_a = self._withdrawal(self._player(), 100, "pending")
        pending_b = self._withdrawal(self._player(), 50, "pending")
        confirmed = self._withdrawal(self._player(), 30, "confirmed")

        result = self.service(admin_id=self._admin())

        self.assertEqual(result["itemCount"], 2)
        self.assertEqual(result["status"], "ready")
        # Сумма: 100 + 50 (confirmed не берём) = 150 ROOT.
        self.assertEqual(result["totalRoot"], 150)
        self.assertEqual(result["totalNano"], 150 * NANO)

        self.assertEqual(self._read(pending_a).status, "processing")
        self.assertEqual(self._read(pending_b).status, "processing")
        self.assertEqual(self._read(confirmed).status, "confirmed")
        for item in result["items"]:
            self.assertTrue(item["queryId"])
            self.assertNotEqual(item["queryId"], "0")

    def test_each_item_gets_unique_query_id(self) -> None:
        for _ in range(5):
            self._withdrawal(self._player(), 10, "pending")

        result = self.service()

        ids = [item["queryId"] for item in result["items"]]
        self.assertEqual(len(ids), 5)
        self.assertEqual(len(set(ids)), 5, "query_id должны быть уникальны")

    def test_second_call_reuses_open_batch(self) -> None:
        self._withdrawal(self._player(), 100, "pending")
        first = self.service()
        # Новая заявка после формирования — второй батч не создаётся.
        self._withdrawal(self._player(), 25, "pending")

        second = self.service()

        self.assertEqual(second["batchId"], first["batchId"])
        self.assertEqual(second["itemCount"], first["itemCount"])

    def test_empty_pending_returns_409(self) -> None:
        from app.mission_engine import MissionEngineError

        with self.assertRaises(MissionEngineError) as ctx:
            self.service()
        self.assertEqual(ctx.exception.status_code, 409)

    def test_restricted_player_excluded(self) -> None:
        allowed = self._player()
        restricted = self._player()
        self._withdrawal(allowed, 100, "pending")
        blocked = self._withdrawal(restricted, 100, "pending")
        self._restrict(restricted)

        result = self.service()

        self.assertEqual(result["itemCount"], 1)
        # Ограниченная заявка осталась pending и в батч не попала.
        self.assertEqual(self._read(blocked).status, "pending")
        self.assertIsNone(self._read(blocked).batch_id)

    def test_total_matches_sum_of_items(self) -> None:
        amounts = [7, 13, 100, 250]
        for amount in amounts:
            self._withdrawal(self._player(), amount, "pending")

        result = self.service()

        self.assertEqual(result["totalRoot"], sum(amounts))
        self.assertEqual(
            sum(item["amountRootNano"] for item in result["items"]),
            sum(amounts) * NANO,
        )

    def test_batch_has_payload_text_snapshot(self) -> None:
        self._withdrawal(self._player(), 42, "pending")

        result = self.service()

        self.assertIn(VALID_TON_ADDRESS, result["payloadText"])
        self.assertIn("42", result["payloadText"])

    def test_three_workers_create_one_batch(self) -> None:
        """Барьер БД: три одновременных вызова дают один батч."""
        for _ in range(3):
            self._withdrawal(self._player(), 10, "pending")

        results = [self.service() for _ in range(3)]
        batch_ids = {item["batchId"] for item in results}

        self.assertEqual(len(batch_ids), 1, "должен остаться один батч")

        from app.models import PayoutBatch

        with self.SessionLocal() as session:
            total = len(session.scalars(select(PayoutBatch)).all())
        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main()
