"""Откат батча выплат (шаг 5).

Проверяем то, что защищает деньги и не даёт системе залипнуть:

  * return_to_pending: заявки снова pending, батч снят, попытка 'failed'
    (иначе unique-индекс не дал бы создать новую попытку — заявка застряла бы);
  * fail_and_refund: заявка failed И холд вернулся игроку + проводка credit;
  * CONFIRMED заявки не откатываются никогда, даже с force;
  * частично подтверждённый батч без force -> 409, с force -> трогает только
    неоплаченные;
  * пустая причина -> 422, неверный mode -> 422;
  * повторный откат -> 409;
  * авто-откат по таймауту: свежий батч не трогается, просроченный
    возвращается в pending; таймаут берётся из CMS.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select

from app.mission_engine import MissionEngineError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

NANO = 100_000_000
ADDRESS_A = "kQATvmnu7p4mTZ1_POo3AQbScpV98vvbdgi_yHiAQo2AQx-X"
ADDRESS_B = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"


class PayoutRollbackServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="chimera-rollback-")
        cls.database_path = Path(cls._tmp.name) / "rollback.sqlite3"
        database_url = f"sqlite:///{cls.database_path}"

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
            payout_confirm_service, payout_rollback_service,
            withdrawal_service,
        )

        cls._patches = []
        for module in (
            withdrawal_service, mission_engine, payout_batch_service,
            payout_confirm_service, payout_rollback_service,
        ):
            if hasattr(module, "SessionLocal"):
                cls._patches.append(
                    patch.object(module, "SessionLocal", cls.SessionLocal)
                )
        for item in cls._patches:
            item.start()

        from app.payout_batch_service import create_payout_batch
        from app.payout_confirm_service import confirm_payout_batch
        from app.payout_rollback_service import (
            rollback_payout_batch,
            rollback_stale_processing,
        )

        cls.create_batch = staticmethod(create_payout_batch)
        cls.confirm = staticmethod(confirm_payout_batch)
        cls.rollback = staticmethod(rollback_payout_batch)
        cls.rollback_stale = staticmethod(rollback_stale_processing)

    @classmethod
    def tearDownClass(cls) -> None:
        for item in cls._patches:
            item.stop()
        cls.engine.dispose()
        cls._tmp.cleanup()

    def setUp(self) -> None:
        from app.models import (
            AdminUser, PayoutAttempt, PayoutBatch, PlayerRestriction,
            SystemSetting, WithdrawalRequest,
        )

        with self.SessionLocal.begin() as session:
            # wallets/game_players/wallet_transactions НЕ чистим: ledger
            # append-only (DELETE запрещён триггером, а удаление кошелька
            # каскадом тянет проводки). Каждый тест создаёт новых игроков с
            # уникальными id, а проверки идут по конкретным id — мусор прошлых
            # прогонов не мешает.
            for model in (
                PayoutAttempt, PayoutBatch, WithdrawalRequest,
                PlayerRestriction, SystemSetting, AdminUser,
            ):
                session.query(model).delete()

        self._set_setting("ton.payout_processing_timeout_hours", 24)

    # --- Хелперы ---------------------------------------------------------
    def _set_setting(self, key: str, value) -> None:
        from app.models import SystemSetting

        with self.SessionLocal.begin() as session:
            existing = session.query(SystemSetting).filter_by(key=key).first()
            if existing is not None:
                existing.value_json = value
                existing.status = "active"
            else:
                session.add(SystemSetting(
                    key=key, value_json=value,
                    value_type="integer" if isinstance(value, int) else "string",
                    category="ton", title=key, description="test",
                    is_sensitive=False, status="active",
                ))

    def _player(self, balance: int = 1000) -> tuple[str, str]:
        from app.models import GamePlayer, Wallet

        player_id = f"player-{uuid.uuid4().hex[:12]}"
        wallet_id = f"wallet-{uuid.uuid4().hex[:12]}"
        with self.SessionLocal.begin() as session:
            session.add(GamePlayer(
                id=player_id, display_name="Rollback test", auth_provider="demo",
                external_id=f"tg-{uuid.uuid4().hex}", status="active",
            ))
            session.add(Wallet(
                id=wallet_id, player_id=player_id, currency="ROOT",
                available_balance=balance,
                available_balance_nano=balance * NANO,
            ))
        return player_id, wallet_id

    def _withdrawal(self, amount: int, address: str = ADDRESS_A) -> tuple[str, str]:
        """Заявка + списанный холд (как после реального создания)."""
        from app.models import WithdrawalRequest

        player_id, wallet_id = self._player(balance=1000)
        withdrawal_id = f"withdrawal-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            from app.models import Wallet

            wallet = session.get(Wallet, wallet_id)
            wallet.available_balance -= amount
            wallet.available_balance_nano = wallet.available_balance * NANO
            session.add(WithdrawalRequest(
                id=withdrawal_id, player_id=player_id,
                amount_root=amount, amount_root_nano=amount * NANO,
                to_address=address, status="pending",
            ))
        return withdrawal_id, wallet_id

    def _batch(self, specs: list[int]) -> tuple[str, dict[str, str]]:
        for amount in specs:
            self._withdrawal(amount)
        result = self.create_batch()
        mapping = {
            item["withdrawalId"]: item["queryId"] for item in result["items"]
        }
        return result["batchId"], mapping

    def _read_withdrawal(self, withdrawal_id: str):
        from app.models import WithdrawalRequest

        with self.SessionLocal() as session:
            return session.get(WithdrawalRequest, withdrawal_id)

    def _read_batch(self, batch_id: str):
        from app.models import PayoutBatch

        with self.SessionLocal() as session:
            return session.get(PayoutBatch, batch_id)

    def _wallet_balance(self, player_id: str) -> int:
        from app.models import Wallet

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == player_id)
            )
            return wallet.available_balance if wallet else -1

    def _confirm_all(self, batch_id: str, mapping: dict[str, str]) -> None:
        from tests.test_payout_confirm_service import (
            PAYOUT_WALLET,
            build_signed_boc,
        )
        from nacl.signing import SigningKey

        key = SigningKey.generate()
        self._set_setting("ton.payout_wallet", PAYOUT_WALLET)
        self._set_setting("ton.payout_wallet_public_key", key.verify_key.encode().hex())
        transfers = []
        for wid, qid in mapping.items():
            withdrawal = self._read_withdrawal(wid)
            transfers.append(
                (qid, withdrawal.amount_root_nano, withdrawal.to_address)
            )
        boc = build_signed_boc(transfers, key)
        self.confirm(
            batch_id, boc,
            blockchain_lookup=lambda q, a: {"txHash": f"tx-{q}"},
        )

    def _confirm_partial(self, batch_id: str, mapping: dict[str, str],
                         wid_to_confirm: str) -> None:
        from tests.test_payout_confirm_service import (
            PAYOUT_WALLET,
            build_signed_boc,
        )
        from nacl.signing import SigningKey

        key = SigningKey.generate()
        self._set_setting("ton.payout_wallet", PAYOUT_WALLET)
        self._set_setting("ton.payout_wallet_public_key", key.verify_key.encode().hex())
        withdrawal = self._read_withdrawal(wid_to_confirm)
        boc = build_signed_boc(
            [(mapping[wid_to_confirm], withdrawal.amount_root_nano,
              withdrawal.to_address)],
            key,
        )
        qid = mapping[wid_to_confirm]
        self.confirm(
            batch_id, boc,
            blockchain_lookup=lambda q, a: {"txHash": "tx-1"} if q == qid else None,
        )

    # --- Тесты -----------------------------------------------------------
    def test_return_to_pending_releases_batch(self) -> None:
        batch_id, mapping = self._batch([10, 20])

        result = self.rollback(batch_id, "не тот кошелёк")

        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(len(result["returned"]), 2)
        self.assertEqual(result["failed"], [])
        for wid in mapping:
            withdrawal = self._read_withdrawal(wid)
            self.assertEqual(withdrawal.status, "pending")
            self.assertIsNone(withdrawal.batch_id)
        self.assertEqual(self._read_batch(batch_id).status, "rolled_back")

    def test_return_to_pending_does_not_refund_hold(self) -> None:
        """Холд не возвращается: деньги всё ещё зарезервированы под вывод."""
        batch_id, mapping = self._batch([100])
        wid = list(mapping)[0]
        player_id = self._read_withdrawal(wid).player_id
        balance_before = self._wallet_balance(player_id)

        self.rollback(batch_id, "ошибся батчем")

        self.assertEqual(self._wallet_balance(player_id), balance_before)

    def test_return_to_pending_clears_attempt_so_new_batch_works(self) -> None:
        """Главная ловушка: 'sending' держит unique-индекс."""
        batch_id, mapping = self._batch([10])
        wid = list(mapping)[0]

        self.rollback(batch_id, "надо пересобрать")

        # Заявка снова pending -> новый батч обязан её взять.
        # Остальные pending-заявки в БД могут быть от других тестов
        # (батч забирает все pending), поэтому проверяем только нашу.
        second = self.create_batch()
        second_ids = {item["withdrawalId"] for item in second["items"]}
        self.assertIn(wid, second_ids)
        self.assertNotEqual(second["batchId"], batch_id)

    def test_fail_and_refund_returns_money(self) -> None:
        from app.models import WalletTransaction

        batch_id, mapping = self._batch([100])
        wid = list(mapping)[0]
        withdrawal = self._read_withdrawal(wid)
        player_id = withdrawal.player_id
        balance_held = self._wallet_balance(player_id)

        result = self.rollback(batch_id, "платёж отклонён", mode="fail_and_refund")

        self.assertEqual(result["failed"], [wid])
        self.assertEqual(self._read_withdrawal(wid).status, "failed")
        self.assertEqual(self._wallet_balance(player_id), balance_held + 100)

        with self.SessionLocal() as session:
            transactions = list(session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.reference_id == wid
                )
            ).all())
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].transaction_type, "credit")
        self.assertEqual(transactions[0].amount, 100)

    def test_confirmed_withdrawal_never_rolled_back(self) -> None:
        batch_id, mapping = self._batch([10])
        wid = list(mapping)[0]
        self._confirm_all(batch_id, mapping)
        self.assertEqual(self._read_withdrawal(wid).status, "confirmed")

        # Батч уже confirmed -> откат запрещён на уровне батча.
        with self.assertRaises(MissionEngineError) as ctx:
            self.rollback(batch_id, "поздно", force=True)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self._read_withdrawal(wid).status, "confirmed")

    def test_partial_confirm_requires_force(self) -> None:
        batch_id, mapping = self._batch([10, 20])
        confirmed_wid = list(mapping)[0]
        self._confirm_partial(batch_id, mapping, confirmed_wid)

        with self.assertRaises(MissionEngineError) as ctx:
            self.rollback(batch_id, "откат остатка")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("force", str(ctx.exception.detail))

    def test_partial_confirm_with_force_keeps_confirmed(self) -> None:
        batch_id, mapping = self._batch([10, 20])
        confirmed_wid = list(mapping)[0]
        other_wid = list(mapping)[1]
        self._confirm_partial(batch_id, mapping, confirmed_wid)

        result = self.rollback(batch_id, "откат остатка", force=True)

        self.assertEqual(result["skippedConfirmed"], [confirmed_wid])
        self.assertEqual(self._read_withdrawal(confirmed_wid).status, "confirmed")
        self.assertEqual(self._read_withdrawal(other_wid).status, "pending")

    def test_empty_reason_rejected(self) -> None:
        batch_id, _ = self._batch([10])
        with self.assertRaises(MissionEngineError) as ctx:
            self.rollback(batch_id, "   ")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_invalid_mode_rejected(self) -> None:
        batch_id, _ = self._batch([10])
        with self.assertRaises(MissionEngineError) as ctx:
            self.rollback(batch_id, "причина", mode="delete_everything")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_double_rollback_rejected(self) -> None:
        batch_id, _ = self._batch([10])
        self.rollback(batch_id, "первый раз")
        with self.assertRaises(MissionEngineError) as ctx:
            self.rollback(batch_id, "второй раз")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_unknown_batch_rejected(self) -> None:
        with self.assertRaises(MissionEngineError) as ctx:
            self.rollback("batch-does-not-exist", "причина")
        self.assertEqual(ctx.exception.status_code, 404)

    def test_stale_rollback_skips_fresh_batch(self) -> None:
        batch_id, mapping = self._batch([10])

        result = self.rollback_stale(batch_id)

        self.assertIsNone(result)
        self.assertEqual(
            self._read_withdrawal(list(mapping)[0]).status, "processing"
        )

    def test_stale_rollback_returns_expired_batch(self) -> None:
        from app.models import PayoutBatch

        batch_id, mapping = self._batch([10])
        # Состарить батч сильнее таймаута (24 ч по умолчанию).
        with self.SessionLocal.begin() as session:
            batch = session.get(PayoutBatch, batch_id)
            from app.withdrawal_service import _utcnow
            batch.opened_at = _utcnow() - timedelta(hours=30)

        result = self.rollback_stale(batch_id)

        self.assertIsNotNone(result)
        self.assertEqual(result["status"], "rolled_back")
        for wid in mapping:
            self.assertEqual(self._read_withdrawal(wid).status, "pending")

    def test_stale_timeout_comes_from_cms(self) -> None:
        """Таймаут 1 час: батч двухчасовой давности уже просрочен."""
        from app.models import PayoutBatch
        from app.withdrawal_service import _utcnow

        self._set_setting("ton.payout_processing_timeout_hours", 1)
        batch_id, mapping = self._batch([10])
        with self.SessionLocal.begin() as session:
            batch = session.get(PayoutBatch, batch_id)
            batch.opened_at = _utcnow() - timedelta(hours=2)

        result = self.rollback_stale(batch_id)

        self.assertIsNotNone(result)
        self.assertEqual(
            self._read_withdrawal(list(mapping)[0]).status, "pending"
        )

    def test_stale_rollback_skips_confirmed_batch(self) -> None:
        batch_id, mapping = self._batch([10])
        self._confirm_all(batch_id, mapping)

        result = self.rollback_stale(batch_id)

        self.assertIsNone(result)
        self.assertEqual(
            self._read_withdrawal(list(mapping)[0]).status, "confirmed"
        )


if __name__ == "__main__":
    unittest.main()
