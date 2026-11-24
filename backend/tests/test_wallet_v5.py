"""Разбор V5R1-кошелька (текущий Tonkeeper) — шаг 6.

История бага: парсер писался под V4, а кошелёк заказчика оказался V5R1.
Форматы несовместимы:

  V4: [signature:512] в НАЧАЛЕ, затем поля, сообщения — цепочкой ref'ов.
  V5: op:32 = 0x7369676e ("sign") первым, поля, обёртка packed,
      [signature:512] в КОНЦЕ бит, действия — деревом.

Парсер V4 прочитает op-код V5 как wallet_id и «не найдёт» подпись. На проде
это означало бы, что подтверждение выплат не работает вообще: ни одна
выплата не подтвердится, хотя деньги уйти могут.

Тесты ниже фиксируют оба формата, чтобы регресс был виден сразу.
Структуры собираются по спеке TON:
  out_list$_ {n:#} prev:^(OutList n) action:OutAction = OutList (n + 1);
  action_send_msg#0ec3c86d mode:(## 8) out_msg:^(MessageRelaxed Any);
"""
from __future__ import annotations

import base64
import unittest

from nacl.signing import SigningKey
from pytoniq_core import (
    Address,
    Cell,
    InternalMsgInfo,
    MessageAny,
    begin_cell,
)
from pytoniq_core.crypto.keys import mnemonic_new, mnemonic_to_wallet_key
from pytoniq_core.tlb.block import CurrencyCollection

from app.ton_connect_parser import (
    ACTION_SEND_MSG_OP,
    JETTON_TRANSFER_OP,
    WALLET_V5_SIGNED_OP,
    BocParseError,
    extract_sender_address,
    parse_jetton_transfers,
    same_address,
    verify_boc_signature,
)

JETTON = "kQATvmnu7p4mTZ1_POo3AQbScpV98vvbdgi_yHiAQo2AQx-X"
SENDER = "kQAqDpRYGNJLa4AqlgoLdTZK9FwCdS0xX0cwSur8LuTRzz_9"
QUERY_A = 1111111111111111111
QUERY_B = 2222222222222222222
AMOUNT_A = 25 * 10**8
AMOUNT_B = 10 * 10**8
VALID_UNTIL = 1795432000


def _transfer_body(query_id: int, amount: int, recipient: str) -> Cell:
    return (
        begin_cell()
        .store_uint(JETTON_TRANSFER_OP, 32)
        .store_uint(query_id, 64)
        .store_coins(amount)
        .store_address(Address(recipient))
        .store_address(None)
        .store_bit(0)
        .store_coins(0)
        .store_bit(0)
        .end_cell()
    )


def _message(query_id: int, amount: int, recipient: str = JETTON) -> MessageAny:
    return MessageAny(
        info=InternalMsgInfo(
            ihr_disabled=True,
            bounce=True,
            bounced=False,
            src=Address(SENDER),
            dest=Address(JETTON),
            value=CurrencyCollection(grams=50_000_000),
            ihr_fee=0,
            fwd_fee=0,
            created_lt=0,
            created_at=0,
        ),
        init=None,
        body=_transfer_body(query_id, amount, recipient),
    )


def _v5_actions(messages: list[MessageAny]) -> Cell:
    """Дерево действий: узел = ref предыдущий + ref action."""
    actions = Cell.empty()
    for message in messages:
        action = (
            begin_cell()
            .store_uint(ACTION_SEND_MSG_OP, 32)
            .store_uint(3, 8)
            .store_ref(message.serialize())
            .end_cell()
        )
        actions = begin_cell().store_ref(actions).store_ref(action).end_cell()
    return actions


def build_v5_boc(messages: list[MessageAny], private_key: bytes) -> str:
    """Собрать подписанное V5R1-сообщение по спеке."""
    packed = (
        begin_cell()
        .store_uint(1, 1)
        .store_ref(_v5_actions(messages))
        .store_uint(0, 1)
        .end_cell()
    )
    signing_message = (
        begin_cell()
        .store_uint(WALLET_V5_SIGNED_OP, 32)
        .store_uint(2147483645, 32)  # wallet_id
        .store_uint(VALID_UNTIL, 32)
        .store_uint(3, 32)  # seqno
        .store_ref(packed)
        .end_cell()
    )
    signature = SigningKey(private_key[:32]).sign(signing_message.hash).signature
    # Подпись — в КОНЦЕ бит, тело — в начале.
    external = (
        begin_cell()
        .store_bits(signing_message.bits)
        .store_ref(packed)
        .store_bytes(signature)
        .end_cell()
    )
    return base64.b64encode(external.to_boc()).decode()


def build_v4_boc(messages: list[MessageAny], private_key: bytes) -> str:
    """Собрать V4-сообщение: подпись в начале, сообщения цепочкой ref'ов."""
    chain: Cell | None = None
    for message in reversed(messages):
        builder = (
            begin_cell().store_uint(3, 8).store_ref(message.serialize())
        )
        if chain is not None:
            builder = builder.store_ref(chain)
        chain = builder.end_cell()

    body = (
        begin_cell()
        .store_uint(0, 32)  # wallet_id
        .store_uint(VALID_UNTIL, 32)
        .store_uint(7, 32)  # seqno
        .store_uint(1, 8)  # op = send messages
        .store_ref(chain)
        .end_cell()
    )
    signature = SigningKey(private_key[:32]).sign(body.hash).signature
    external = (
        begin_cell()
        .store_bytes(signature)
        .store_uint(0, 32)
        .store_uint(VALID_UNTIL, 32)
        .store_uint(7, 32)
        .store_uint(1, 8)
        .store_ref(chain)
        .end_cell()
    )
    return base64.b64encode(external.to_boc()).decode()


class WalletV5Tests(unittest.TestCase):
    """V5R1 — формат текущего Tonkeeper."""

    def setUp(self) -> None:
        self.words = mnemonic_new(24)
        self.public_key, self.private_key = mnemonic_to_wallet_key(self.words)

    def test_parses_two_transfers_in_order(self) -> None:
        boc = build_v5_boc(
            [_message(QUERY_A, AMOUNT_A), _message(QUERY_B, AMOUNT_B)],
            self.private_key,
        )

        transfers = parse_jetton_transfers(boc)

        self.assertEqual(
            [(t["queryId"], t["amountNano"]) for t in transfers],
            [(str(QUERY_A), AMOUNT_A), (str(QUERY_B), AMOUNT_B)],
        )

    def test_signature_verifies(self) -> None:
        boc = build_v5_boc([_message(QUERY_A, AMOUNT_A)], self.private_key)
        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")

    def test_foreign_key_rejected(self) -> None:
        boc = build_v5_boc([_message(QUERY_A, AMOUNT_A)], self.private_key)
        other_public, _ = mnemonic_to_wallet_key(mnemonic_new(24))

        with self.assertRaises(BocParseError) as ctx:
            verify_boc_signature(boc, other_public)
        self.assertIn("не совпадает", str(ctx.exception))

    def test_sender_extracted(self) -> None:
        boc = build_v5_boc([_message(QUERY_A, AMOUNT_A)], self.private_key)
        self.assertTrue(same_address(extract_sender_address(boc), SENDER))

    def test_tampered_amount_breaks_signature(self) -> None:
        """Подмена суммы при честной подписи должна отклоняться."""
        honest = build_v5_boc([_message(QUERY_A, AMOUNT_A)], self.private_key)
        tampered = build_v5_boc(
            [_message(QUERY_A, 999 * 10**8)], self.private_key
        )

        honest_root = Cell.one_from_boc(base64.b64decode(honest))
        honest_parser = honest_root.begin_parse()
        honest_parser.load_bits(honest_root.bits.__len__() - 512)
        honest_signature = honest_parser.load_bytes(64)

        tampered_root = Cell.one_from_boc(base64.b64decode(tampered))
        body_bits = tampered_root.bits.__len__() - 512
        parser = tampered_root.begin_parse()
        forged = begin_cell()
        remaining = body_bits
        while remaining >= 8:
            forged = forged.store_uint(parser.load_uint(8), 8)
            remaining -= 8
        if remaining:
            forged = forged.store_uint(parser.load_uint(remaining), remaining)
        while parser.remaining_refs:
            forged = forged.store_ref(parser.load_ref())
        forged_cell = forged.store_bytes(honest_signature).end_cell()
        forged_boc = base64.b64encode(forged_cell.to_boc()).decode()

        with self.assertRaises(BocParseError) as ctx:
            verify_boc_signature(forged_boc, self.public_key)
        self.assertIn("не совпадает", str(ctx.exception))

    def test_non_jetton_message_skipped(self) -> None:
        plain = MessageAny(
            info=InternalMsgInfo(
                ihr_disabled=True, bounce=True, bounced=False,
                src=Address(SENDER), dest=Address(JETTON),
                value=CurrencyCollection(grams=50_000_000),
                ihr_fee=0, fwd_fee=0, created_lt=0, created_at=0,
            ),
            init=None,
            body=begin_cell().store_uint(0, 32).store_string("hi").end_cell(),
        )
        boc = build_v5_boc(
            [plain, _message(QUERY_A, AMOUNT_A)], self.private_key
        )

        transfers = parse_jetton_transfers(boc)

        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], str(QUERY_A))

    def test_empty_actions_rejected(self) -> None:
        """V5 без действий — не батч, а мусор: понятная ошибка."""
        packed = begin_cell().store_uint(1, 1).store_ref(Cell.empty()).store_uint(0, 1).end_cell()
        signing_message = (
            begin_cell()
            .store_uint(WALLET_V5_SIGNED_OP, 32)
            .store_uint(2147483645, 32)
            .store_uint(VALID_UNTIL, 32)
            .store_uint(3, 32)
            .store_ref(packed)
            .end_cell()
        )
        signature = SigningKey(self.private_key[:32]).sign(
            signing_message.hash
        ).signature
        external = (
            begin_cell()
            .store_bits(signing_message.bits)
            .store_ref(packed)
            .store_bytes(signature)
            .end_cell()
        )
        boc = base64.b64encode(external.to_boc()).decode()

        with self.assertRaises(BocParseError):
            parse_jetton_transfers(boc)


class WalletV4StillWorksTests(unittest.TestCase):
    """V4 не должен сломаться, пока кошельки V4 в ходу."""

    def setUp(self) -> None:
        self.words = mnemonic_new(24)
        self.public_key, self.private_key = mnemonic_to_wallet_key(self.words)

    def test_parses_and_verifies(self) -> None:
        boc = build_v4_boc([_message(QUERY_A, AMOUNT_A)], self.private_key)

        transfers = parse_jetton_transfers(boc)
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], str(QUERY_A))
        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")

    def test_sender_extracted(self) -> None:
        boc = build_v4_boc([_message(QUERY_A, AMOUNT_A)], self.private_key)
        self.assertTrue(same_address(extract_sender_address(boc), SENDER))


def build_v5_envelope(messages, private_key: bytes) -> str:
    """BOC в том виде, как его возвращает TON Connect: внешнее сообщение.

    ext_in_msg_info$10 src:MsgAddress import_fee:Grams body:^Cell
    Тело (подписанное V5-сообщение) лежит в ref, а не в битах обёртки.
    """
    import base64 as _b64

    signed_body = Cell.one_from_boc(_b64.b64decode(build_v5_boc(messages, private_key)))
    envelope = (
        begin_cell()
        .store_uint(2, 2)      # ext_in_msg_info$10
        .store_address(None)   # src: addr_none
        .store_coins(0)        # import_fee
        .store_ref(signed_body)
        .end_cell()
    )
    return _b64.b64encode(envelope.to_boc()).decode()


def build_v5_envelope_with_src(messages, private_key: bytes) -> str:
    """Обёртка ext_in с УКАЗАННЫМ src: адрес добавляет 267 бит."""
    import base64 as _b64

    signed_body = Cell.one_from_boc(_b64.b64decode(build_v5_boc(messages, private_key)))
    envelope = (
        begin_cell()
        .store_uint(2, 2)
        .store_address(Address(SENDER))  # src указан
        .store_coins(0)
        .store_ref(signed_body)
        .end_cell()
    )
    return _b64.b64encode(envelope.to_boc()).decode()


class ExternalEnvelopeTests(unittest.TestCase):
    """TON Connect отдаёт BOC с обёрткой внешнего сообщения.

    Без снятия обёртки парсер читал служебные биты (0b10 + адрес) вместо
    op-кода 0x7369676e, считал сообщение V4, брал мусор как подпись и отвечал
    «Подпись BOC не совпадает с ключом кошелька выплат» — при ВЕРНОЙ подписи.
    Именно это видел заказчик при первой реальной оплате.
    """

    def setUp(self) -> None:
        self.words = mnemonic_new(24)
        self.public_key, self.private_key = mnemonic_to_wallet_key(self.words)

    def test_enveloped_signature_verifies(self) -> None:
        boc = build_v5_envelope([_message(QUERY_A, AMOUNT_A)], self.private_key)
        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")

    def test_enveloped_transfers_parsed(self) -> None:
        boc = build_v5_envelope(
            [_message(QUERY_A, AMOUNT_A), _message(QUERY_B, AMOUNT_B)],
            self.private_key,
        )

        transfers = parse_jetton_transfers(boc)

        self.assertEqual(
            [(t["queryId"], t["amountNano"]) for t in transfers],
            [(str(QUERY_A), AMOUNT_A), (str(QUERY_B), AMOUNT_B)],
        )

    def test_enveloped_sender_extracted(self) -> None:
        boc = build_v5_envelope([_message(QUERY_A, AMOUNT_A)], self.private_key)
        self.assertTrue(same_address(extract_sender_address(boc), SENDER))

    def test_envelope_with_sender_address(self) -> None:
        """Обёртка с указанным src (273 бита) — реальный ext_in из сети.

        Первая версия снятия обёртки проверяла «мало бит в ячейке» (порог 40),
        и такой случай не срабатывал: адрес добавляет 267 бит. Признак
        исправлен на op-код 0x7369676e в ref.
        """
        boc = build_v5_envelope_with_src(
            [_message(QUERY_A, AMOUNT_A)], self.private_key
        )

        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")
        transfers = parse_jetton_transfers(boc)
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], str(QUERY_A))

    def test_enveloped_foreign_key_rejected(self) -> None:
        """Обёртка не должна ослаблять проверку подписи."""
        boc = build_v5_envelope([_message(QUERY_A, AMOUNT_A)], self.private_key)
        other_public, _ = mnemonic_to_wallet_key(mnemonic_new(24))

        with self.assertRaises(BocParseError):
            verify_boc_signature(boc, other_public)


if __name__ == "__main__":
    unittest.main()
