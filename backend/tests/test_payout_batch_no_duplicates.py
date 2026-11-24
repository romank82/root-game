"""Регресс: заявка с несколькими попытками не должна дублироваться в батче.

Найдено на проде. Заявка прошла откат (попытка -> 'failed'), потом попала в
новый батч (попытка -> 'sending'). В таблице payout_attempts две строки на
одну заявку. Старый JOIN на withdrawal_id возвращал заявку ДВАЖДЫ, поэтому:

  * интерфейс показывал «2 заявки · 310 ROOT» вместо «1 заявка · 155 ROOT»;
  * кнопка оплаты собирала два перевода на одну заявку с РАЗНЫМИ query_id,
    то есть владелец подписал бы двойную выплату;
  * подтверждение видело лишний query_id и отклоняло BOC как чужой.

Тест фиксирует: на одну заявку — одна строка в ответе, и это АКТИВНАЯ
(самая свежая) попытка, а не провалившаяся.
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

from sqlalchemy import select

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

NANO = 100_000_000
ADDRESS = "kQATvmnu7p4mTZ1_POo3AQbScpV98vvbdgi_yHiAQo2AQx-X"


class DuplicateAttemptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="chimera-dup-attempts-")
        database_url = f"sqlite:///{Path(cls._tmp.name) / 'dup.sqlite3'}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url
        subprocess.run(
            [
                sys.executable, "-m", "alembic",
                "-c", str(BACKEND_ROOT / "alembic.ini"),
                "upgrade", "head",
            ],
            cwd=BACKEND_ROOT, env=environment, check=True,
            capture_output=True, text=True,
        )

        from sqlalchemy import create_engine, event
        from sqlalchemy.orm import sessionmaker

        cls.engine = create_engine(
            database_url, connect_args={"check_same_thread": False}
        )

        @event.listens_for(cls.engine, "connect")
        def _fk(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        cls.SessionLocal = sessionmaker(
            bind=cls.engine, autoflush=False, autocommit=False,
            expire_on_commit=False,
        )

        from app import (
            mission_engine, payout_batch_service,
            payout_confirm_service, withdrawal_service,
        )

        cls._patches = []
        for module in (
            withdrawal_service, mission_engine,
            payout_batch_service, payout_confirm_service,
        ):
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
            AdminUser, GamePlayer, PayoutAttempt, PayoutBatch,
            PlayerRestriction, SystemSetting, Wallet, WithdrawalRequest,
        )

        with self.SessionLocal.begin() as session:
            for model in (
                PayoutAttempt, PayoutBatch, WithdrawalRequest,
                PlayerRestriction, SystemSetting, AdminUser,
            ):
                session.query(model).delete()

    def _make_withdrawal(self, amount: int) -> str:
        from app.models import GamePlayer, Wallet, WithdrawalRequest

        player_id = f"player-{uuid.uuid4().hex[:12]}"
        withdrawal_id = f"withdrawal-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(GamePlayer(
                id=player_id, display_name="Dup test", auth_provider="demo",
                external_id=f"tg-{uuid.uuid4().hex}", status="active",
            ))
            session.add(Wallet(
                id=f"wallet-{uuid.uuid4().hex[:12]}", player_id=player_id,
                currency="ROOT", available_balance=1000,
                available_balance_nano=1000 * NANO,
            ))
            session.add(WithdrawalRequest(
                id=withdrawal_id, player_id=player_id,
                amount_root=amount, amount_root_nano=amount * NANO,
                to_address=ADDRESS, status="pending",
            ))
        return withdrawal_id

    def test_withdrawal_with_old_failed_attempt_not_duplicated(self) -> None:
        """Провалившаяся попытка + новая активная = ОДНА строка в ответе."""
        from app.payout_batch_service import create_payout_batch, get_payout_batch
        from app.models import PayoutAttempt, WithdrawalRequest

        withdrawal_id = self._make_withdrawal(155)
        batch = create_payout_batch()
        batch_id = batch["batchId"]

        # Имитируем историю: добавляем СТАРУЮ failed-попытку той же заявки.
        with self.SessionLocal.begin() as session:
            session.add(PayoutAttempt(
                id=f"payout-attempt-old-{uuid.uuid4().hex[:8]}",
                withdrawal_id=withdrawal_id,
                status="failed",
                query_id="1045742324698854800",
                error="Rollback: старый батч",
            ))

        # Проверяем ровно то, что видит интерфейс.
        detail = get_payout_batch(batch_id, resolve_wallets=False)

        self.assertEqual(
            len(detail["items"]),
            1,
            "заявка не должна дублироваться из-за старой failed-попытки",
        )
        item = detail["items"][0]
        self.assertEqual(item["withdrawalId"], withdrawal_id)
        self.assertEqual(item["amountRootNano"], 155 * NANO)
        # query_id — от АКТИВНОЙ попытки, а не от провалившейся.
        with self.SessionLocal() as session:
            active = session.scalar(
                select(PayoutAttempt).where(
                    PayoutAttempt.withdrawal_id == withdrawal_id,
                    PayoutAttempt.status == "sending",
                )
            )
        self.assertIsNotNone(active)
        self.assertEqual(item["queryId"], active.query_id)
        self.assertNotEqual(item["queryId"], "1045742324698854800")

    def test_sum_of_items_equals_batch_total(self) -> None:
        """Сумма заявок в ответе совпадает с total_nano батча (155, не 310)."""
        from app.payout_batch_service import create_payout_batch, get_payout_batch

        withdrawal_id = self._make_withdrawal(155)
        batch = create_payout_batch()

        with self.SessionLocal.begin() as session:
            from app.models import PayoutAttempt

            session.add(PayoutAttempt(
                id=f"payout-attempt-old-{uuid.uuid4().hex[:8]}",
                withdrawal_id=withdrawal_id,
                status="failed",
                query_id="999999999999999999",
            ))

        detail = get_payout_batch(batch["batchId"], resolve_wallets=False)
        total_from_items = sum(item["amountRootNano"] for item in detail["items"])

        self.assertEqual(total_from_items, detail["totalNano"])
        self.assertEqual(total_from_items, 155 * NANO)


if __name__ == "__main__":
    unittest.main()
