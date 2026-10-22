"""Admin economy audit — сверка баланса (9.1, часть 2).

Live SQLite + alembic upgrade head (паттерн test_admin_segments.py): для каждого
теста — свежая disposable БД со схемой из миграций. Ledger immutable: триггеры
0b9e7c6d5a41 запрещают DELETE/UPDATE wallet_transactions на уровне БД, поэтому
между тестами проводки чистить нельзя — каждый тест получает собственную БД.
Endpoint-функция audit_balances вызывается напрямую с реальными AdminUser из БД
и замоканным SessionLocal модуля admin_economy.

Покрывает:
  - happy path: кошелёк без проводок и кошелёк со сходящимся ledger
    (SUM(credit) - SUM(debit) == available_balance) -> ok=True;
  - расхождение: available_balance != ledger-суммы -> mismatch в ответе
    и запись economy.audit в immutable admin_audit_log;
  - отсутствие права economy.read -> 403 (право проверяется зависимостью
    require_permission, поэтому тест дергает сам dependency).
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

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_access import DIRECT_EXECUTION_MODE, require_permission
from app.admin_economy import ECONOMY_READ_PERMISSION, audit_balances

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AdminEconomyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модуль; SessionLocal патчится на свежую БД в setUp."""
        from app import admin_economy

        cls.admin_economy = admin_economy
        cls._session_local_patch = None

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-economy-tests-"
        )
        self.database_path = Path(self._temporary_directory.name) / "admin.sqlite3"
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
        self._session_local_patch = patch.object(
            self.admin_economy, "SessionLocal", self.SessionLocal
        )
        self._session_local_patch.start()

    def tearDown(self) -> None:
        self._session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

# ---- Fixtures и хелперы -------------------------------------------------

    def _request(self) -> SimpleNamespace:
        return SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.9"),
            headers={},
            state=SimpleNamespace(),
        )

    def _make_admin(self, is_super_admin: bool = True):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin" if is_super_admin else "admin",
                    is_super_admin=is_super_admin,
                    is_active=True,
                    is_deleted=False,
                )
            )
        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _grant(self, admin_id: str, permission_code: str) -> None:
        from app.models import AdminUserPermission

        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode=DIRECT_EXECUTION_MODE,
                    is_active=True,
                )
            )

    def _make_player(self) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="Economy audit player",
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _make_wallet(self, player_id: str | None = None) -> str:
        """Кошелёк ROOT с available_balance=0 и без проводок."""
        from app.models import Wallet

        if player_id is None:
            player_id = self._make_player()

        wallet_id = f"wallet-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Wallet(
                    id=wallet_id,
                    player_id=player_id,
                    currency="ROOT",
                    available_balance=0,
                    locked_balance=0,
                )
            )
        return wallet_id

    def _make_transaction(
        self,
        wallet_id: str,
        amount: int,
        transaction_type: str,
        balance_after: int,
    ) -> None:
        """Проводка c уникальным reference (unique index по референсу)."""
        from app.models import WalletTransaction

        with self.SessionLocal.begin() as session:
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet_id,
                    amount=amount,
                    balance_after=balance_after,
                    transaction_type=transaction_type,
                    reason=f"Test {transaction_type}",
                    reference_type="test_economy_audit",
                    reference_id=f"tx-{uuid.uuid4().hex}",
                    metadata_json={},
                )
            )

    def _set_available_balance(self, wallet_id: str, amount: int) -> None:
        from app.models import Wallet

        with self.SessionLocal.begin() as session:
            session.get(Wallet, wallet_id).available_balance = amount

# ---- Тесты --------------------------------------------------------------

    def test_audit_ok(self) -> None:
        """Кошелёк без проводок и кошелёк со сходящимся ledger -> ok=True."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)

        # Кошелёк без проводок: ledger-сумма отсутствует -> ожидаем 0.
        self._make_wallet()

        # Кошелёк со сходящимся ledger: credit 100, debit 40 -> 60.
        wallet_id = self._make_wallet()
        self._make_transaction(wallet_id, 100, "credit", 100)
        self._set_available_balance(wallet_id, 100)
        self._make_transaction(wallet_id, 40, "debit", 60)
        self._set_available_balance(wallet_id, 60)

        result = audit_balances(request=self._request(), admin=admin)

        self.assertIs(result["ok"], True)
        self.assertEqual(result["mismatches"], [])
        self.assertGreaterEqual(result["total"], 2)

    def test_audit_finds_mismatch(self) -> None:
        """Рассинхрон баланса даёт mismatch и запись economy.audit в аудит."""
        from app.models import AdminAuditLog

        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)

        wallet_id = self._make_wallet()
        self._make_transaction(wallet_id, 50, "credit", 50)
        self._set_available_balance(wallet_id, 50)

        # Рассинхрон вручную: +50 к балансу без всякой ledger-проводки.
        self._set_available_balance(wallet_id, 100)

        result = audit_balances(request=self._request(), admin=admin)

        self.assertIs(result["ok"], False)
        mismatch = next(
            (item for item in result["mismatches"] if item["walletId"] == wallet_id),
            None,
        )
        self.assertIsNotNone(mismatch)
        self.assertEqual(mismatch["expected"], 50)
        self.assertEqual(mismatch["actual"], 100)
        self.assertEqual(mismatch["difference"], 50)

        with self.SessionLocal() as session:
            audit_rows = session.scalars(
                select(AdminAuditLog).where(
                    AdminAuditLog.action == "economy.audit"
                )
            ).all()
        self.assertGreaterEqual(len(audit_rows), 1)
        audit = audit_rows[-1]
        self.assertEqual(audit.admin_user_id, admin.id)
        self.assertEqual(audit.permission_code, ECONOMY_READ_PERMISSION)
        self.assertEqual(audit.metadata_json["count"], 1)
        self.assertLessEqual(len(audit.metadata_json["sample"]), 10)

    def test_audit_requires_permission(self) -> None:
        """Без права economy.read доступ к эндпоинту закрыт (403)."""
        # Не суперадмин: get_permission_execution_mode не отдаёт direct
        # автоматически, а проверяет грант economy.read у конкретного админа.
        admin = self._make_admin(is_super_admin=False)

        # audit_balances проверяет право через Depends(require_permission(...)),
        # поэтому дергаем сам dependency — это ровно тот гейт, что защищает
        # роут в проде (прямой вызов endpoint-функции минует его).
        dependency = require_permission(ECONOMY_READ_PERMISSION)
        with self.assertRaises(HTTPException) as context:
            dependency(admin=admin)

        self.assertEqual(context.exception.status_code, 403)