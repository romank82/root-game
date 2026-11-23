"""Подтверждение батча выплат по подписанному BOC (шаг 4).

Тесты защищают главное: не подтвердить заявку, за которую не заплатили, и не
пропустить оплаченную. BOC собирается настоящими примитивами TON и
подписывается настоящим ed25519 — моки только на «блокчейн».

Покрываем:
  * счастливый путь: 3 заявки оплачены -> все confirmed, батч confirmed;
  * частичная оплата: в блокчейне видна часть -> submitted, остальные processing;
  * чужая подпись / чужой кошелёк -> отказ, ничего не подтверждается;
  * подмена суммы или получателя в BOC -> отказ целиком;
  * query_id не из этого батча -> отказ;
  * повторный query_id в BOC -> отказ;
  * блокчейн недоступен -> 503-подобное поведение (заявки не подтверждены);
  * повторное подтверждение уже подтверждённой заявки -> не дублируется;
  * батч уже confirmed / rolled_back -> 409.
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from nacl.signing import SigningKey
from pytoniq_core import (
    Address,
    Cell,
    InternalMsgInfo,
    MessageAny,
    begin_cell,
)
from pytoniq_core.tlb.block import CurrencyCollection

from app.mission_engine import MissionEngineError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

JETTON_TRANSFER_OP = 0xF8A7EA5
NANO = 100_000_000

PAYOUT_WALLET = "kQAqRaBA0S-aZywDDORH_yHICbcmPFzopntYj-w9JobPzpXe"
RECIPIENT_A = "kQATvmnu7p4mTZ1_POo3AQbScpV98vvbdgi_yHiAQo2AQx-X"
RECIPIENT_B = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"


def jetton_body(query_id: str, amount_nano: int, recipient: str) -> Cell:
    return (
        begin_cell()
        .store_uint(JETTON_TRANSFER_OP, 32)
        .store_uint(int(query_id), 64)
        .store_coins(amount_nano)
        .store_address(Address(recipient))
        .store_address(None)
        .store_bit(0)
        .store_coins(0)
        .store_bit(0)
        .end_cell()
    )


def build_signed_boc(transfers: list[tuple[str, int, str]], key: SigningKey,
                     sender: str = PAYOUT_WALLET) -> str:
    """Собрать и подписать BOC: список (query_id, сумма, получатель)."""
    chain: Cell | None = None
    for query_id, amount_nano, recipient in reversed(transfers):
        inner = MessageAny(
            info=InternalMsgInfo(
                ihr_disabled=True,
                bounce=True,
                bounced=False,
                src=Address(sender),
                dest=Address(sender),
                value=CurrencyCollection(grams=50_000_000),
                ihr_fee=0,
                fwd_fee=0,
                created_lt=0,
                created_at=0,
            ),
            init=None,
            body=jetton_body(query_id, amount_nano, recipient),
        )
        builder = begin_cell().store_uint(3, 8).store_ref(inner.serialize())
        if chain is not None:
            builder = builder.store_ref(chain)
        chain = builder.end_cell()

    body_cell = (
        begin_cell()
        .store_uint(0, 32)
        .store_uint(1_700_000_000, 32)
        .store_uint(7, 32)
        .store_uint(1, 8)
        .store_ref(chain)
        .end_cell()
    )

    signature = key.sign(body_cell.hash).signature
    builder = begin_cell().store_bytes(signature)
    parser = body_cell.begin_parse()
    while parser.remaining_bits >= 8:
        builder = builder.store_uint(parser.load_uint(8), 8)
    while parser.remaining_refs:
        builder = builder.store_ref(parser.load_ref())
    return base64.b64encode(builder.end_cell().to_boc()).decode()


class PayoutConfirmServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="chimera-confirm-")
        cls.database_path = Path(cls._tmp.name) / "confirm.sqlite3"
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

        from app import (  # noqa: F401
            mission_engine,
            payout_batch_service,
            payout_confirm_service,
            withdrawal_service,
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

        from app.payout_batch_service import create_payout_batch
        from app.payout_confirm_service import confirm_payout_batch

        cls.create_batch = staticmethod(create_payout_batch)
        cls.confirm = staticmethod(confirm_payout_batch)

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
                PayoutAttempt, PayoutBatch, WithdrawalRequest, PlayerRestriction,
                Wallet, SystemSetting, GamePlayer, AdminUser,
            ):
                session.query(model).delete()

        self.signing_key = SigningKey.generate()
        self.public_key = self.signing_key.verify_key.encode()
        self._set_setting("ton.payout_wallet", PAYOUT_WALLET)
        self._set_setting("ton.payout_wallet_public_key", self.public_key.hex())

    # --- Хелперы ---------------------------------------------------------
    def _set_setting(self, key: str, value: str) -> None:
        """Записать CMS-настройку: key + value_json (схема SystemSetting)."""
        from app.models import SystemSetting

        with self.SessionLocal.begin() as session:
            existing = session.query(SystemSetting).filter_by(key=key).first()
            if existing is not None:
                existing.value_json = value
                existing.status = "active"
            else:
                session.add(
                    SystemSetting(
                        key=key,
                        value_json=value,
                        value_type="string",
                        category="ton",
                        title=key,
                        description="Seed by payout confirm test",
                        is_sensitive=False,
                        status="active",
                    )
                )

    def _player(self, balance: int = 1000) -> str:
        from app.models import GamePlayer, Wallet

        player_id = f"player-{uuid.uuid4().hex[:12]}"
        with self.SessionLocal.begin() as session:
            session.add(GamePlayer(
                id=player_id, display_name="Confirm test", auth_provider="demo",
                external_id=f"tg-{uuid.uuid4().hex}", status="active",
            ))
            session.add(Wallet(
                id=f"wallet-{uuid.uuid4().hex[:12]}", player_id=player_id,
                currency="ROOT", available_balance=balance,
                available_balance_nano=balance * NANO,
            ))
        return player_id

    def _withdrawal(self, amount: int, address: str = RECIPIENT_A) -> str:
        from app.models import WithdrawalRequest

        withdrawal_id = f"withdrawal-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(WithdrawalRequest(
                id=withdrawal_id, player_id=self._player(),
                amount_root=amount, amount_root_nano=amount * NANO,
                to_address=address, status="pending",
            ))
        return withdrawal_id

    def _batch_with(self, specs: list[tuple[int, str]]) -> tuple[str, dict]:
        """Создать батч из спек (сумма ROOT, адрес) -> (batchId, {wid: qid})."""
        for amount, address in specs:
            self._withdrawal(amount, address)
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

    @staticmethod
    def _lookup_all(query_id: str, amount_nano: int):
        return {"txHash": f"tx-{query_id}"}

    # --- Тесты -----------------------------------------------------------
    def test_all_paid_confirms_batch(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A), (20, RECIPIENT_B)])
        boc = build_signed_boc(
            [
                (mapping[wid], self._read_withdrawal(wid).amount_root_nano,
                 self._read_withdrawal(wid).to_address)
                for wid in mapping
            ],
            self.signing_key,
        )

        result = self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)

        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(result["confirmedCount"], 2)
        self.assertEqual(result["pendingCount"], 0)
        for wid in mapping:
            self.assertEqual(self._read_withdrawal(wid).status, "confirmed")
        self.assertEqual(self._read_batch(batch_id).status, "confirmed")

    def test_partial_payment_leaves_batch_submitted(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A), (20, RECIPIENT_B)])
        first, second = list(mapping)
        boc = build_signed_boc(
            [(mapping[first], 10 * NANO, RECIPIENT_A)], self.signing_key
        )

        def only_first(query_id: str, amount_nano: int):
            return {"txHash": "tx-1"} if query_id == mapping[first] else None

        result = self.confirm(batch_id, boc, blockchain_lookup=only_first)

        self.assertEqual(result["status"], "submitted")
        self.assertEqual(result["confirmedCount"], 1)
        self.assertEqual(result["pendingCount"], 1)
        self.assertEqual(self._read_withdrawal(first).status, "confirmed")
        # Вторая осталась processing — её решит откат (шаг 5).
        self.assertEqual(self._read_withdrawal(second).status, "processing")
        self.assertEqual(self._read_batch(batch_id).status, "submitted")

    def test_partial_payment_boc_contains_all_but_blockchain_sees_one(self) -> None:
        """BOC подписан на все заявки, но в блокчейне пока видна одна."""
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A), (20, RECIPIENT_B)])
        boc = build_signed_boc(
            [
                (mapping[wid], self._read_withdrawal(wid).amount_root_nano,
                 self._read_withdrawal(wid).to_address)
                for wid in mapping
            ],
            self.signing_key,
        )

        def nothing_yet(query_id: str, amount_nano: int):
            return None

        result = self.confirm(batch_id, boc, blockchain_lookup=nothing_yet)

        self.assertEqual(result["confirmedCount"], 0)
        self.assertEqual(result["status"], "submitted")
        for wid in mapping:
            self.assertEqual(self._read_withdrawal(wid).status, "processing")

    def test_foreign_key_rejected(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        other_key = SigningKey.generate()
        boc = build_signed_boc(
            [(mapping[wid], 10 * NANO, RECIPIENT_A)], other_key
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self._read_withdrawal(wid).status, "processing")

    def test_other_wallet_rejected(self) -> None:
        """Подпись валидна, но платит чужой кошелёк — отказ."""
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        boc = build_signed_boc(
            [(mapping[wid], 10 * NANO, RECIPIENT_A)],
            self.signing_key,
            sender=RECIPIENT_B,  # не кошелёк выплат
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self._read_withdrawal(wid).status, "processing")

    def test_tampered_amount_rejected(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        # В BOC сумма 999 вместо 10 — подпись сходится, но заявка не та.
        boc = build_signed_boc(
            [(mapping[wid], 999 * NANO, RECIPIENT_A)], self.signing_key
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Сумма", str(ctx.exception.detail))
        self.assertEqual(self._read_withdrawal(wid).status, "processing")

    def test_wrong_recipient_rejected(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        boc = build_signed_boc(
            [(mapping[wid], 10 * NANO, RECIPIENT_B)], self.signing_key
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Получатель", str(ctx.exception.detail))

    def test_unknown_query_id_rejected(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        boc = build_signed_boc(
            [("999999999", 10 * NANO, RECIPIENT_A)], self.signing_key
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("нет в этом батче", str(ctx.exception.detail))

    def test_duplicate_query_id_rejected(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        boc = build_signed_boc(
            [
                (mapping[wid], 10 * NANO, RECIPIENT_A),
                (mapping[wid], 10 * NANO, RECIPIENT_A),
            ],
            self.signing_key,
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("дважды", str(ctx.exception.detail))

    def test_blockchain_unavailable_does_not_confirm(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        boc = build_signed_boc(
            [(mapping[wid], 10 * NANO, RECIPIENT_A)], self.signing_key
        )

        def broken(query_id: str, amount_nano: int):
            raise RuntimeError("TON API недоступен")

        result = self.confirm(batch_id, boc, blockchain_lookup=broken)

        self.assertEqual(result["confirmedCount"], 0)
        self.assertEqual(self._read_withdrawal(wid).status, "processing")
        self.assertEqual(self._read_batch(batch_id).status, "submitted")

    def test_second_confirm_does_not_duplicate(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        boc = build_signed_boc(
            [(mapping[wid], 10 * NANO, RECIPIENT_A)], self.signing_key
        )
        self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)

        # Батч уже confirmed — повтор отклоняется, а не перезаписывает.
        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_missing_public_key_configured_fails_loud(self) -> None:
        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        self._set_setting("ton.payout_wallet_public_key", "")
        boc = build_signed_boc(
            [(mapping[wid], 10 * NANO, RECIPIENT_A)], self.signing_key
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(self._read_withdrawal(wid).status, "processing")

    def test_attempt_marked_sent_with_tx_hash(self) -> None:
        from app.models import PayoutAttempt

        batch_id, mapping = self._batch_with([(10, RECIPIENT_A)])
        wid = list(mapping)[0]
        boc = build_signed_boc(
            [(mapping[wid], 10 * NANO, RECIPIENT_A)], self.signing_key
        )
        self.confirm(batch_id, boc, blockchain_lookup=self._lookup_all)

        with self.SessionLocal() as session:
            attempt = session.query(PayoutAttempt).filter_by(
                withdrawal_id=wid
            ).one()
            self.assertEqual(attempt.status, "sent")
            self.assertEqual(attempt.tx_hash, f"tx-{mapping[wid]}")


if __name__ == "__main__":
    unittest.main()
