"""Разбор РЕАЛЬНОГО сообщения от Tonkeeper (эталон с прода).

Три версии парсера падали на нём, потому что тесты собирали BOC тем же кодом,
что и парсер, и ошибка взаимно компенсировалась. Здесь вход — настоящее
сообщение, которое вернул кошелёк при попытке оплаты батча на проде.

Структура этого сообщения:
  корень : 919 бит, 1 ref — внешнее сообщение (ext_in_msg_info)
  тело   : 642 бит, 1 ref, op 0x7369676e, wallet_id, valid_until, seqno
  подпись: последние 512 бит ТЕЛА (не корня), signed part = 130 бит

Главная ловушка: подпись надо искать в теле, а не в корне. В корне 919 бит —
если срезать с него 512, границы уезжают и подпись «не сходится».
"""
from __future__ import annotations

import unittest

from app.ton_connect_parser import (
    WALLET_V5_SIGNED_OP,
    _detect_wallet_version,
    _split_signature_v5,
    _unwrap_external_envelope,
    parse_jetton_transfers,
    same_address,
    verify_boc_signature,
)
from tests.fixtures_ton import (
    TONKEEPER_AMOUNT_NANO,
    TONKEEPER_BOC_B64,
    TONKEEPER_PUBLIC_KEY_HEX,
    TONKEEPER_QUERY_ID,
    TONKEEPER_SEQNO,
    TONKEEPER_VALID_UNTIL,
    TONKEEPER_WALLET_ID,
)


class RealTonkeeperBocTests(unittest.TestCase):
    """Разбор настоящего сообщения кошелька."""

    def setUp(self) -> None:
        from pytoniq_core import Cell
        import base64

        self.cell = Cell.one_from_boc(base64.b64decode(TONKEEPER_BOC_B64))
        self.public_key = bytes.fromhex(TONKEEPER_PUBLIC_KEY_HEX)

    def test_root_is_external_message(self) -> None:
        """Корень — внешнее сообщение 919 бит, а не тело."""
        self.assertEqual(self.cell.bits.__len__(), 919)
        self.assertEqual(len(self.cell.refs), 1)

    def test_unwraps_to_v5_body(self) -> None:
        """Обёртка снимается, тело — 642 бита с op 0x7369676e."""
        body = _unwrap_external_envelope(self.cell)

        self.assertEqual(body.bits.__len__(), 642)
        self.assertEqual(len(body.refs), 1)
        self.assertEqual(body.begin_parse().load_uint(32), WALLET_V5_SIGNED_OP)
        self.assertEqual(_detect_wallet_version(body.begin_parse()), "v5")

    def test_signature_verifies_on_body(self) -> None:
        """Подпись = последние 512 бит ТЕЛА; signed part = 130 бит."""
        body = _unwrap_external_envelope(self.cell)

        signature, signed_part = _split_signature_v5(body)

        self.assertEqual(len(signature), 64)
        self.assertEqual(signed_part.bits.__len__(), 130)
        self.assertEqual(len(signed_part.refs), 1)

        from nacl.signing import VerifyKey

        VerifyKey(self.public_key).verify(signed_part.hash, signature)

    def test_public_verify_passes(self) -> None:
        """Публичная функция принимает настоящее сообщение."""
        self.assertEqual(
            verify_boc_signature(TONKEEPER_BOC_B64, self.public_key), "ok"
        )

    def test_wrong_key_rejected(self) -> None:
        """Чужой ключ отклоняется — защита не ослаблена."""
        from app.ton_connect_parser import BocParseError

        other = bytes.fromhex("00" * 32)
        with self.assertRaises(BocParseError):
            verify_boc_signature(TONKEEPER_BOC_B64, other)

    def test_header_fields(self) -> None:
        """Поля тела читаются с правильных позиций."""
        body = _unwrap_external_envelope(self.cell)
        parser = body.begin_parse()

        self.assertEqual(parser.load_uint(32), WALLET_V5_SIGNED_OP)
        self.assertEqual(parser.load_uint(32), TONKEEPER_WALLET_ID)
        self.assertEqual(parser.load_uint(32), TONKEEPER_VALID_UNTIL)
        self.assertEqual(parser.load_uint(32), TONKEEPER_SEQNO)

    def test_transfer_parsed(self) -> None:
        """Перевод из сообщения разбирается: query_id и сумма из заявки."""
        transfers = parse_jetton_transfers(TONKEEPER_BOC_B64)

        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], TONKEEPER_QUERY_ID)
        self.assertEqual(transfers[0]["amountNano"], TONKEEPER_AMOUNT_NANO)

    def test_sender_is_payout_wallet(self) -> None:
        """Отправитель — кошелёк выплат."""
        from app.ton_connect_parser import extract_sender_address

        sender = extract_sender_address(TONKEEPER_BOC_B64)
        self.assertTrue(
            same_address(sender, "0QAqDpRYGNJLa4AqlgoLdTZK9FwCdS0xX0cwSur8LuTRz2I4")
        )

    def test_short_body_not_treated_as_envelope(self) -> None:
        """Короткая ячейка не должна приниматься за обёртку.

        Тело начинается с 0b10 так же, как ext_in_msg_info. Если снимать
        обёртку без проверки op, короткие тела ломаются.
        """
        from pytoniq_core import begin_cell

        short = begin_cell().store_uint(0b10, 2).store_uint(12345, 30).end_cell()
        self.assertIs(_unwrap_external_envelope(short), short)


if __name__ == "__main__":
    unittest.main()
