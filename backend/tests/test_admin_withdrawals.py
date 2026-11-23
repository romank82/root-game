"""Тесты админ-эндпоинтов вывода ROOT → TON (11.6).

Инфраструктура — паттерн test_withdrawal_service.py: на каждый тест свежая
disposable SQLite + alembic upgrade head; SessionLocal патчится в ТРИ канала
(admin_withdrawals.SessionLocal, withdrawal_service.SessionLocal —
прямые импорты; app.db.SessionLocal — ленивые импорты).

Сеть TON не вызывается: send_jetton_transfer_sync — мок.

Покрытие:
  1. GET list: 2 заявки (pending/confirmed) -> total=2; фильтр status=pending
     -> total=1 (read-only, без мутаций).
  2. POST /batch: 1 pending -> confirmed + ton_tx_hash + batch_id +
     аудит withdrawal.batch.
  3. POST /{id}/reject: 1 pending -> rejected + reason + refund холда
     (баланс 900 -> 1000) + аудит withdrawal.rejected.
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

from app import admin_withdrawals, withdrawal_service
from app.models import (
    AdminUser,
    GamePlayer,
    SystemSetting,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Валидный тестнет-адрес TON (как в test_withdrawal_service.py).
VALID_TON_ADDRESS = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"


class AdminWithdrawalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.admin_withdrawals = admin_withdrawals
        cls.withdrawal_service = withdrawal_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite + alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-withdrawals-tests-"
        )
        self.database_path = (
            Path(self._temporary_directory.name) / "admin_withdrawals.sqlite3"
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
            patch.object(self.admin_withdrawals, "SessionLocal", self.SessionLocal),
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
        player_id = f"admin-withdrawal-player-{uuid.uuid4().hex[:12]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name="Admin withdrawal test",
                auth_provider="demo",
                external_id=f"test-admin-withdrawal-{uuid.uuid4().hex}",
                status="active",
            )
        )
        session.flush()
        return player_id

    def _make_admin(self, session):
        """AdminUser (super_admin) — возвращается объектом из БД."""
        admin_id = f"admin-withdrawal-{uuid.uuid4().hex[:12]}"
        session.add(
            AdminUser(
                id=admin_id,
                username=f"admin-withdrawals-{uuid.uuid4().hex[:8]}",
                password_hash="not-a-real-hash",
                role="super_admin",
                is_super_admin=True,
                is_active=True,
            )
        )
        session.flush()
        return session.get(AdminUser, admin_id)

    def _seed_setting(
        self, session, key: str, value_json, value_type: str
    ) -> None:
        """Активная SystemSetting (CMS-first), идемпотентно.

        Миграция dde2038a44d9 уже создаёт ton.*-строки из каталога, поэтому
        при существующей записи обновляем ТОЛЬКО value_json (+status), а
        метаданные оставляем каталоговыми — иначе admin_system_settings
        отдаёт 409 «Метаданные настройки не соответствуют каталогу».
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
                    description="Seeded by admin_withdrawals test",
                    is_sensitive=False,
                    status="active",
                )
            )
        session.flush()

    def _seed_withdrawal_settings(self, session) -> None:
        """Три CMS-ключа вывода (как в test_withdrawal_service)."""
        self._seed_setting(
            session,
            self.withdrawal_service.WITHDRAWAL_ENABLED_KEY,
            True,
            "boolean",
        )
        self._seed_setting(
            session,
            self.withdrawal_service.WITHDRAWAL_MIN_AMOUNT_KEY,
            10,
            "integer",
        )
        self._seed_setting(
            session,
            self.withdrawal_service.WITHDRAWAL_DAILY_LIMIT_KEY,
            5000,
            "integer",
        )

    def _seed_wallet(self, session, player_id: str, balance: int) -> str:
        """ROOT-кошелёк игрока с заданным балансом."""
        wallet_id = f"admin-wallet-{uuid.uuid4().hex[:12]}"
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

    def _seed_withdrawal(
        self, session, player_id: str, *, status: str, amount_root: int = 100
    ) -> str:
        """Заявка напрямую (для GET list; холд не эмулируется)."""
        withdrawal_id = f"withdrawal-{uuid.uuid4().hex[:12]}"
        session.add(
            WithdrawalRequest(
                id=withdrawal_id,
                player_id=player_id,
                amount_root=amount_root,
                to_address=VALID_TON_ADDRESS,
                status=status,
            )
        )
        session.flush()
        return withdrawal_id

    def _find_audits(self, action: str):
        """AdminAuditLog записи действия (по action; поля до/после — в JSON)."""
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return session.scalars(
                select(AdminAuditLog).where(AdminAuditLog.action == action)
            ).all()



    # ---- Тесты --------------------------------------------------------------

    def test_list_withdrawals(self) -> None:
        """GET list: 2 заявки -> total=2; фильтр status=pending -> 1."""
        with self.SessionLocal.begin() as session:
            admin = self._make_admin(session)
            player_one = self._make_player(session)
            player_two = self._make_player(session)
            pending_id = self._seed_withdrawal(session, player_one, status="pending")
            confirmed_id = self._seed_withdrawal(
                session, player_two, status="confirmed"
            )

        result = self.admin_withdrawals.list_admin_withdrawals(_admin=admin)
        self.assertEqual(result["total"], 2)
        self.assertEqual(result["limit"], 50)
        self.assertEqual(result["offset"], 0)
        self.assertEqual(
            {row["id"] for row in result["withdrawals"]},
            {pending_id, confirmed_id},
        )

        # Сериализатор покрывает все поля контракта.
        first = result["withdrawals"][0]
        self.assertIn("playerId", first)
        self.assertIn("amountRoot", first)
        self.assertIn("toAddress", first)
        self.assertIn("tonTxHash", first)
        self.assertIn("batchId", first)
        self.assertIn("adminId", first)
        self.assertIn("reason", first)
        self.assertIn("createdAt", first)
        self.assertIn("updatedAt", first)
        # Причина отказа выплаты — часть контракта (пусто, если попыток не было).
        self.assertIn("payoutError", first)
        self.assertIn("payoutAttemptStatus", first)
        self.assertIn("payoutAttemptedAt", first)
        self.assertIsNone(first["payoutError"])

        pending_only = self.admin_withdrawals.list_admin_withdrawals(
            status="pending", _admin=admin
        )
        self.assertEqual(pending_only["total"], 1)
        self.assertEqual(
            [row["id"] for row in pending_only["withdrawals"]], [pending_id]
        )

        # Неверный status -> 422 (отклонено до запроса к БД).
        with self.assertRaises(Exception) as ctx:
            self.admin_withdrawals.list_admin_withdrawals(
                status="unknown", _admin=admin
            )
        self.assertEqual(ctx.exception.__class__.__name__, "HTTPException")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_batch(self) -> None:
        """POST /batch: pending -> confirmed + ton_tx_hash + аудит."""
        with self.SessionLocal.begin() as session:
            admin = self._make_admin(session)
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session)
            self._seed_wallet(session, player_id, 1000)

        withdrawal_id = self.withdrawal_service.create_withdrawal_request(
            player_id, 100, VALID_TON_ADDRESS
        )["withdrawalId"]

        with patch.object(
            self.withdrawal_service,
            "send_jetton_transfer_sync",
            return_value="mock-tx-hash",
        ) as mock_transfer:
            result = self.admin_withdrawals.run_admin_withdrawal_batch(
                request=None, admin=admin, limit=50
            )

        self.assertEqual(result["confirmed"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertTrue(result["batchId"].startswith("batch-"))
        mock_transfer.assert_called_once()
        # amount_root 100 -> 100 * 10^8 nanoROOT.
        self.assertEqual(mock_transfer.call_args.args[0], VALID_TON_ADDRESS)
        self.assertEqual(mock_transfer.call_args.args[1], 100 * 10**8)

        with self.SessionLocal() as session:
            request = session.get(WithdrawalRequest, withdrawal_id)
            self.assertEqual(request.status, "confirmed")
            self.assertEqual(request.ton_tx_hash, "mock-tx-hash")
            self.assertEqual(request.batch_id, result["batchId"])
            self.assertEqual(request.admin_id, admin.id)

        audits = self._find_audits("withdrawal.batch")
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.entity_type, "withdrawal_batch")
        self.assertEqual(audit.entity_id, result["batchId"])
        self.assertEqual(audit.permission_code, "players.manage")
        self.assertEqual(audit.before_json, {})
        self.assertEqual(
            audit.after_json,
            {
                "batchId": result["batchId"],
                "confirmed": 1,
                "failed": 0,
            },
        )



    def test_reject(self) -> None:
        """POST /{id}/reject: pending -> rejected + refund + аудит."""
        with self.SessionLocal.begin() as session:
            admin = self._make_admin(session)
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session)
            self._seed_wallet(session, player_id, 1000)

        withdrawal_id = self.withdrawal_service.create_withdrawal_request(
            player_id, 100, VALID_TON_ADDRESS
        )["withdrawalId"]

        result = self.admin_withdrawals.reject_admin_withdrawal(
            withdrawal_id=withdrawal_id,
            payload=self.admin_withdrawals.WithdrawalRejectPayload(
                reason="Адрес не подтверждён."
            ),
            request=None,
            admin=admin,
        )
        self.assertEqual(result["withdrawalId"], withdrawal_id)
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["reason"], "Адрес не подтверждён.")

        with self.SessionLocal() as session:
            request = session.get(WithdrawalRequest, withdrawal_id)
            self.assertEqual(request.status, "rejected")
            self.assertEqual(request.reason, "Адрес не подтверждён.")
            self.assertEqual(request.admin_id, admin.id)
            # Холд списан при create (1000 -> 900), после reject возвращён.
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            self.assertEqual(wallet.available_balance, 1000)
            refund = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.reference_type
                    == self.withdrawal_service.WITHDRAWAL_REFUND_REFERENCE_TYPE,
                    WalletTransaction.reference_id == withdrawal_id,
                )
            )
            self.assertIsNotNone(refund)
            self.assertEqual(refund.transaction_type, "credit")
            self.assertEqual(refund.amount, 100)

        audits = self._find_audits("withdrawal.rejected")
        self.assertEqual(len(audits), 1)
        audit = audits[0]
        self.assertEqual(audit.entity_type, "withdrawal")
        self.assertEqual(audit.entity_id, withdrawal_id)
        self.assertEqual(audit.permission_code, "players.manage")
        self.assertEqual(audit.before_json, {"status": "pending"})
        self.assertEqual(
            audit.after_json,
            {"status": "rejected", "reason": "Адрес не подтверждён."},
        )

    def test_failed_payout_error_is_visible_in_list(self) -> None:
        """Провал выплаты: причина из PayoutAttempt.error видна в списке.

        Без этого админка показывает только status='failed' и пустой
        ton_tx_hash — конфиг, сеть и баланс неотличимы, причину искать в логах.
        """
        with self.SessionLocal.begin() as session:
            admin = self._make_admin(session)
            player_id = self._make_player(session)
            self._seed_withdrawal_settings(session)
            self._seed_wallet(session, player_id, 1000)

        withdrawal_id = self.withdrawal_service.create_withdrawal_request(
            player_id, 100, VALID_TON_ADDRESS
        )["withdrawalId"]

        # Сеть недоступна — send_jetton_transfer_sync бросает.
        with patch.object(
            self.withdrawal_service,
            "send_jetton_transfer_sync",
            side_effect=RuntimeError("TON_API_ENDPOINT не настроен."),
        ):
            batch = self.withdrawal_service.process_withdrawal_batch(admin.id)

        self.assertEqual(batch["confirmed"], 0)
        self.assertEqual(batch["failed"], 1)

        result = self.admin_withdrawals.list_admin_withdrawals(
            status="failed", _admin=admin
        )
        self.assertEqual(result["total"], 1)
        row = result["withdrawals"][0]
        self.assertEqual(row["id"], withdrawal_id)
        self.assertEqual(row["status"], "failed")
        self.assertIsNone(row["tonTxHash"])
        # Главное: причина видна и не пустая.
        self.assertEqual(
            row["payoutError"], "TON_API_ENDPOINT не настроен."
        )
        self.assertEqual(row["payoutAttemptStatus"], "failed")
        self.assertIsNotNone(row["payoutAttemptedAt"])

        # Холд возвращён игроку — провал не съедает ROOT.
        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            self.assertEqual(wallet.available_balance, 1000)

