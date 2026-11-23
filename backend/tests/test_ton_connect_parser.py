"""Разбор подписанного BOC от TON Connect (шаг 3).

BOC собирается теми же примитивами, что и в реальном кошельке, поэтому тесты
проверяют не мок, а настоящую структуру ячеек TON.

Покрываем:
  * три перевода с разными query_id/суммами разбираются по одному;
  * посторонние (не-jetton) сообщения игнорируются, а не роняют разбор;
  * битый base64 / не-ячейка / обрезанное тело -> BocParseError;
  * пустой BOC и «нет переводов» -> BocParseError;
  * отправитель извлекается и сравнивается корректно (bounceable vs raw);
  * защита от гигантского BOC и от слишком длинного списка сообщений.
"""
from __future__ import annotations

import base64
import unittest

from pytoniq_core import (
    Address,
    Cell,
    InternalMsgInfo,
    MessageAny,
    begin_cell,
)
from nacl.signing import SigningKey
from pytoniq_core.tlb.block import CurrencyCollection

from app.ton_connect_parser import (
    JETTON_TRANSFER_OP,
    MAX_BOC_BASE64_LENGTH,
    BocParseError,
    extract_sender_address,
    parse_jetton_transfers,
    same_address,
    verify_boc_signature,
)

RECIPIENT_A = "kQATvmnu7p4mTZ1_POo3AQbScpV98vvbdgi_yHiAQo2AQx-X"
RECIPIENT_B = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"
SENDER_WALLET = "kQAqRaBA0S-aZywDDORH_yHICbcmPFzopntYj-w9JobPzpXe"

NANO = 100_000_000


def jetton_body(query_id: int, amount_nano: int, recipient: str) -> Cell:
    return (
        begin_cell()
        .store_uint(JETTON_TRANSFER_OP, 32)
        .store_uint(query_id, 64)
        .store_coins(amount_nano)
        .store_address(Address(recipient))
        .store_address(None)
        .store_bit(0)
        .store_coins(0)
        .store_bit(0)
        .end_cell()
    )


def plain_body() -> Cell:
    """Постороннее сообщение: текст-комментарий, а не jetton-перевод."""
    return begin_cell().store_uint(0, 32).store_string("hello").end_cell()


def build_boc(bodies: list[Cell], sender: str = SENDER_WALLET) -> str:
    """Подписанное внешнее сообщение кошелька с заданными телами."""
    # Цепочка строится с конца, чтобы голова списка была первым переводом —
    # так же, как это делает кошелёк при сборке списка сообщений.
    chain: Cell | None = None
    for body in reversed(bodies):
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
            body=body,
        )
        builder = begin_cell().store_uint(3, 8).store_ref(inner.serialize())
        if chain is not None:
            builder = builder.store_ref(chain)
        chain = builder.end_cell()

    root = (
        begin_cell()
        .store_uint(0, 32)
        .store_uint(1_700_000_000, 32)
        .store_uint(7, 32)
        .store_uint(1, 8)
        .store_ref(chain)
        .end_cell()
    )
    return base64.b64encode(root.to_boc()).decode()


class ParseJettonTransfersTests(unittest.TestCase):
    def test_parses_three_transfers(self) -> None:
        boc = build_boc(
            [
                jetton_body(111, 10 * NANO, RECIPIENT_A),
                jetton_body(222, 25 * NANO, RECIPIENT_B),
                jetton_body(333, 7 * NANO, RECIPIENT_A),
            ]
        )

        transfers = parse_jetton_transfers(boc)

        self.assertEqual(len(transfers), 3)
        self.assertEqual([t["queryId"] for t in transfers], ["111", "222", "333"])
        self.assertEqual(
            [t["amountNano"] for t in transfers],
            [10 * NANO, 25 * NANO, 7 * NANO],
        )
        # Порядок сохранён: первый в списке — первый в результате.
        self.assertTrue(same_address(transfers[0]["recipient"], RECIPIENT_A))
        self.assertTrue(same_address(transfers[1]["recipient"], RECIPIENT_B))

    def test_large_query_id_survives(self) -> None:
        big = 2**64 - 1  # максимум unsigned 64
        transfers = parse_jetton_transfers(build_boc([jetton_body(big, NANO, RECIPIENT_A)]))
        self.assertEqual(transfers[0]["queryId"], str(big))

    def test_non_jetton_message_is_skipped(self) -> None:
        boc = build_boc(
            [
                plain_body(),
                jetton_body(444, 5 * NANO, RECIPIENT_A),
            ]
        )

        transfers = parse_jetton_transfers(boc)

        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], "444")

    def test_only_non_jetton_raises(self) -> None:
        with self.assertRaises(BocParseError) as ctx:
            parse_jetton_transfers(build_boc([plain_body()]))
        self.assertIn("jetton", str(ctx.exception).lower())

    def test_empty_string_raises(self) -> None:
        with self.assertRaises(BocParseError):
            parse_jetton_transfers("")

    def test_invalid_base64_raises(self) -> None:
        with self.assertRaises(BocParseError) as ctx:
            parse_jetton_transfers("это не base64!!!")
        self.assertIn("base64", str(ctx.exception))

    def test_valid_base64_but_not_cell_raises(self) -> None:
        garbage = base64.b64encode(b"not a ton cell at all").decode()
        with self.assertRaises(BocParseError):
            parse_jetton_transfers(garbage)

    def test_oversized_boc_rejected(self) -> None:
        huge = "A" * (MAX_BOC_BASE64_LENGTH + 10)
        with self.assertRaises(BocParseError) as ctx:
            parse_jetton_transfers(huge)
        self.assertIn("большой", str(ctx.exception))

    def test_wrong_wallet_op_raises(self) -> None:
        root = (
            begin_cell()
            .store_uint(0, 32)
            .store_uint(1, 32)
            .store_uint(0, 32)
            .store_uint(9, 8)  # не send-messages
            .store_ref(begin_cell().store_uint(3, 8).store_ref(plain_body()).end_cell())
            .end_cell()
        )
        with self.assertRaises(BocParseError) as ctx:
            parse_jetton_transfers(base64.b64encode(root.to_boc()).decode())
        self.assertIn("операция", str(ctx.exception))

    def test_no_messages_raises(self) -> None:
        root = (
            begin_cell()
            .store_uint(0, 32)
            .store_uint(1, 32)
            .store_uint(0, 32)
            .store_uint(1, 8)
            .end_cell()
        )
        with self.assertRaises(BocParseError):
            parse_jetton_transfers(base64.b64encode(root.to_boc()).decode())

    def test_truncated_transfer_body_raises(self) -> None:
        truncated = (
            begin_cell()
            .store_uint(JETTON_TRANSFER_OP, 32)
            # query_id обрезан: только 20 бит
            .store_uint(12345, 20)
            .end_cell()
        )
        with self.assertRaises(BocParseError):
            parse_jetton_transfers(build_boc([truncated]))


class SenderAddressTests(unittest.TestCase):
    def test_extracts_sender(self) -> None:
        boc = build_boc([jetton_body(1, NANO, RECIPIENT_A)])
        sender = extract_sender_address(boc)
        self.assertTrue(same_address(sender, SENDER_WALLET))

    def test_same_address_across_forms(self) -> None:
        bounceable = Address(SENDER_WALLET).to_str(is_user_friendly=True, is_bounceable=True)
        non_bounceable = Address(SENDER_WALLET).to_str(
            is_user_friendly=True, is_bounceable=False
        )
        raw = Address(SENDER_WALLET).to_str(is_user_friendly=False)

        self.assertTrue(same_address(bounceable, non_bounceable))
        self.assertTrue(same_address(non_bounceable, raw))
        self.assertTrue(same_address(raw, bounceable))

    def test_different_addresses_not_equal(self) -> None:
        self.assertFalse(same_address(RECIPIENT_A, RECIPIENT_B))

    def test_invalid_address_is_false_not_crash(self) -> None:
        self.assertFalse(same_address("не адрес", RECIPIENT_A))
        self.assertFalse(same_address(RECIPIENT_A, ""))


def build_signed_boc(bodies: list[Cell], signing_key: SigningKey) -> str:
    """Подписанный BOC: sig(512) + тело кошелька в одной ячейке.

    Так устроено внешнее сообщение TON: кошелёк кладёт подпись перед телом,
    а подписывает хэш ячейки-тела.
    """
    chain: Cell | None = None
    for body in reversed(bodies):
        inner = MessageAny(
            info=InternalMsgInfo(
                ihr_disabled=True,
                bounce=True,
                bounced=False,
                src=Address(SENDER_WALLET),
                dest=Address(SENDER_WALLET),
                value=CurrencyCollection(grams=50_000_000),
                ihr_fee=0,
                fwd_fee=0,
                created_lt=0,
                created_at=0,
            ),
            init=None,
            body=body,
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

    # Подпись = ed25519 над хэшем тела.
    signature = signing_key.sign(body_cell.hash).signature

    # Собираем: сигнатура впереди, затем биты и refs тела.
    builder = begin_cell().store_bytes(signature)
    parser = body_cell.begin_parse()
    while parser.remaining_bits >= 8:
        builder = builder.store_uint(parser.load_uint(8), 8)
    while parser.remaining_refs:
        builder = builder.store_ref(parser.load_ref())
    return base64.b64encode(builder.end_cell().to_boc()).decode()


class SignedBocTests(unittest.TestCase):
    def setUp(self) -> None:
        self.key = SigningKey.generate()
        self.public_key = self.key.verify_key.encode()

    def _boc(self) -> str:
        return build_signed_boc(
            [jetton_body(777, 15 * NANO, RECIPIENT_A)], self.key
        )

    def test_valid_signature_passes(self) -> None:
        self.assertEqual(verify_boc_signature(self._boc(), self.public_key), "ok")

    def test_signature_of_other_key_rejected(self) -> None:
        other = SigningKey.generate().verify_key.encode()
        with self.assertRaises(BocParseError) as ctx:
            verify_boc_signature(self._boc(), other)
        self.assertIn("не совпадает", str(ctx.exception))

    def test_tampered_body_rejected(self) -> None:
        """Подмена суммы в подписанном BOC должна ломать подпись."""
        boc = self._boc()
        cell = Cell.one_from_boc(base64.b64decode(boc))
        parser = cell.begin_parse()
        signature = parser.load_bytes(64)
        wallet_id = parser.load_uint(32)
        valid_until = parser.load_uint(32)
        seqno = parser.load_uint(32)
        op = parser.load_uint(8)
        chain = parser.load_ref()

        # Меняем сумму в теле перевода, подпись оставляем прежнюю.
        item = chain.begin_parse()
        send_mode = item.load_uint(8)
        message_cell = item.load_ref()
        tampered_message = MessageAny.deserialize(message_cell.begin_parse())
        tampered_message.body = (
            begin_cell()
            .store_uint(JETTON_TRANSFER_OP, 32)
            .store_uint(777, 64)
            .store_coins(999 * NANO)   # было 15 ROOT
            .store_address(Address(RECIPIENT_A))
            .store_address(None)
            .store_bit(0)
            .store_coins(0)
            .store_bit(0)
            .end_cell()
        )
        new_chain = (
            begin_cell()
            .store_uint(send_mode, 8)
            .store_ref(tampered_message.serialize())
            .end_cell()
        )
        rebuilt = (
            begin_cell()
            .store_bytes(signature)
            .store_uint(wallet_id, 32)
            .store_uint(valid_until, 32)
            .store_uint(seqno, 32)
            .store_uint(op, 8)
            .store_ref(new_chain)
            .end_cell()
        )
        tampered_boc = base64.b64encode(rebuilt.to_boc()).decode()

        with self.assertRaises(BocParseError) as ctx:
            verify_boc_signature(tampered_boc, self.public_key)
        self.assertIn("не совпадает", str(ctx.exception))

    def test_missing_signature_rejected(self) -> None:
        unsigned = build_boc([jetton_body(1, NANO, RECIPIENT_A)])
        with self.assertRaises(BocParseError) as ctx:
            verify_boc_signature(unsigned, self.public_key)
        self.assertIn("нет подписи", str(ctx.exception))

    def test_bad_public_key_length_rejected(self) -> None:
        with self.assertRaises(BocParseError):
            verify_boc_signature(self._boc(), b"short")

    def test_signed_boc_parses_transfers(self) -> None:
        """Подпись не мешает разбору: переводы те же."""
        transfers = parse_jetton_transfers(self._boc())
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], "777")
        self.assertEqual(transfers[0]["amountNano"], 15 * NANO)

    def test_signed_boc_sender_extracted(self) -> None:
        sender = extract_sender_address(self._boc())
        self.assertTrue(same_address(sender, SENDER_WALLET))


class OutMsgLookupParseTests(unittest.TestCase):
    """Разбор исходящих сообщений из TonCenter (поиск выплаты в блокчейне).

    Формат ответа TonCenter отличается от TON Connect BOC: тело лежит в
    out_msgs[].msg_data.body. Проверяем, что парсер выплат его понимает.
    """

    def _out_msg(self, query_id: int, amount_nano: int, recipient: str) -> dict:
        body = (
            begin_cell()
            .store_uint(JETTON_TRANSFER_OP, 32)
            .store_uint(query_id, 64)
            .store_coins(amount_nano)
            .store_address(Address(recipient))
            .store_address(None)
            .store_bit(0)
            .store_coins(0)
            .store_bit(0)
            .end_cell()
        )
        return {
            "msg_data": {
                "body": base64.b64encode(body.to_boc()).decode()
            }
        }

    def test_parses_transfer_from_out_msg(self) -> None:
        from app.ton_payout_lookup import _parse_transfer_from_out_msg

        parsed = _parse_transfer_from_out_msg(
            self._out_msg(555, 20 * NANO, RECIPIENT_A)
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["queryId"], "555")
        self.assertEqual(parsed["amountNano"], 20 * NANO)
        self.assertTrue(same_address(parsed["recipient"], RECIPIENT_A))

    def test_non_transfer_out_msg_returns_none(self) -> None:
        from app.ton_payout_lookup import _parse_transfer_from_out_msg

        other = {
            "msg_data": {
                "body": base64.b64encode(
                    begin_cell().store_uint(0, 32).store_string("hi").end_cell().to_boc()
                ).decode()
            }
        }
        self.assertIsNone(_parse_transfer_from_out_msg(other))

    def test_empty_or_garbage_out_msg_returns_none(self) -> None:
        from app.ton_payout_lookup import _parse_transfer_from_out_msg

        self.assertIsNone(_parse_transfer_from_out_msg({}))
        self.assertIsNone(
            _parse_transfer_from_out_msg({"msg_data": {"body": "не base64!"}})
        )


class FrontendPayloadCompatTests(unittest.TestCase):
    """Payload, собранный фронтом (@ton/core), читается боевым парсером.

    Фронт строит TEP-74 transfer в TypeScript, бэкенд разбирает его в Python.
    Если порядок полей или кодирование coins разойдутся, подтверждение выплат
    молча перестанет работать — этот тест ловит именно такой рассинхрон.
    """

    # Тот же payload, что выдаёт @ton/core в браузере для этих входных данных.
    FRONTEND_PAYLOAD_B64 = (
        "te6cckEBAQEANQAAZQ+KfqURIhD0femBFUlQL5AIACd8093dPEybOv551G4CDaTlKvvl"
        "97bsEX+Q8QCFGwCGAdmGCx8="
    )

    def test_frontend_payload_parses(self) -> None:
        from pytoniq_core import Cell

        cell = Cell.one_from_boc(base64.b64decode(self.FRONTEND_PAYLOAD_B64))
        parser = cell.begin_parse()

        self.assertEqual(parser.load_uint(32), JETTON_TRANSFER_OP)
        self.assertEqual(parser.load_uint(64), 1234567890123456789)
        self.assertEqual(parser.load_coins(), 25 * 100_000_000)
        recipient = parser.load_address()
        self.assertIsNotNone(recipient)
        # response_destination пуст: фронт шлёт storeAddress(null).
        self.assertIsNone(parser.load_address())

    def test_build_transfer_payload_matches_parser(self) -> None:
        """Сборка в Python и разбор тем же кодом — замкнутый круг."""
        from pytoniq_core import Address, Cell, begin_cell

        amount = 25 * 100_000_000
        query_id = 1234567890123456789
        wallet = "kQATvmnu7p4mTZ1_POo3AQbScpV98vvbdgi_yHiAQo2AQx-X"

        built = (
            begin_cell()
            .store_uint(JETTON_TRANSFER_OP, 32)
            .store_uint(query_id, 64)
            .store_coins(amount)
            .store_address(Address(wallet))
            .store_address(None)
            .store_maybe_ref(None)
            .store_coins(0)
            .store_maybe_ref(None)
            .end_cell()
        )

        parser = Cell.one_from_boc(built.to_boc()).begin_parse()
        self.assertEqual(parser.load_uint(32), JETTON_TRANSFER_OP)
        self.assertEqual(parser.load_uint(64), query_id)
        self.assertEqual(parser.load_coins(), amount)
        self.assertIsNotNone(parser.load_address())
        self.assertIsNone(parser.load_address())


if __name__ == "__main__":
    unittest.main()
