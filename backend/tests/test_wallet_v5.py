"""V5R1-кошелёк (Tonkeeper): разбор, подпись, отправитель.

Сообщения собираются `tests/ton_builder.py` — по структуре РЕАЛЬНОГО BOC с
прода, а не по догадкам. Прежняя версия этого файла строила действия отдельной
ячейкой в ref и не вставляла Either-бит в тело; такой «эталон» не совпадал с
тем, что присылает кошелёк, и тесты проходили при сломанном разборе.

Ключевые факты структуры (см. ton_builder и tests/fixtures_ton.py):
  * внешнее сообщение: src пуст, dest — кошелёк-владелец (он и платит);
  * тело: 130 бит полей + 512 бит подписи;
  * подпись — последние 512 бит ТЕЛА, а не корня;
  * список действий: op+mode в битах узла, [prev, message] в refs.
"""
from __future__ import annotations

import unittest

from app.ton_connect_parser import (
    BocParseError,
    extract_sender_address,
    parse_jetton_transfers,
    same_address,
    verify_boc_signature,
)
from tests.ton_builder import (
    SENDER,
    build_bare,
    build_external,
    new_keypair,
    transfer_message,
)

QUERY_A = 1111111111111111111
QUERY_B = 2222222222222222222
AMOUNT_A = 25 * 10**8
AMOUNT_B = 10 * 10**8


class WalletV5Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.public_key, self.private_key = new_keypair()

    def test_parses_two_transfers_in_order(self) -> None:
        boc = build_external(
            [
                transfer_message(QUERY_A, AMOUNT_A),
                transfer_message(QUERY_B, AMOUNT_B),
            ],
            self.private_key,
        )

        transfers = parse_jetton_transfers(boc)

        self.assertEqual(
            [(t["queryId"], t["amountNano"]) for t in transfers],
            [(str(QUERY_A), AMOUNT_A), (str(QUERY_B), AMOUNT_B)],
        )

    def test_signature_verifies(self) -> None:
        boc = build_external([transfer_message(QUERY_A, AMOUNT_A)], self.private_key)
        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")

    def test_foreign_key_rejected(self) -> None:
        boc = build_external([transfer_message(QUERY_A, AMOUNT_A)], self.private_key)
        other_public, _ = new_keypair()

        with self.assertRaises(BocParseError) as ctx:
            verify_boc_signature(boc, other_public)
        self.assertIn("не совпадает", str(ctx.exception))

    def test_sender_extracted(self) -> None:
        boc = build_external([transfer_message(QUERY_A, AMOUNT_A)], self.private_key)
        self.assertTrue(same_address(extract_sender_address(boc), SENDER))

    def test_envelope_with_src(self) -> None:
        """Обёртка с указанным src: адрес добавляет 267 бит."""
        boc = build_external(
            [transfer_message(QUERY_A, AMOUNT_A)], self.private_key, with_src=True
        )

        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")
        self.assertEqual(len(parse_jetton_transfers(boc)), 1)

    def test_bare_body_still_parsed(self) -> None:
        """Голое тело без обёртки — обратная совместимость."""
        boc = build_bare([transfer_message(QUERY_A, AMOUNT_A)], self.private_key)

        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")
        transfers = parse_jetton_transfers(boc)
        self.assertEqual(transfers[0]["queryId"], str(QUERY_A))

    def test_non_jetton_message_skipped(self) -> None:
        """Служебное сообщение кошелька не считается переводом."""
        boc = build_external(
            [
                transfer_message(0, 0, body_op=0x12345678),
                transfer_message(QUERY_A, AMOUNT_A),
            ],
            self.private_key,
        )

        transfers = parse_jetton_transfers(boc)

        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], str(QUERY_A))

    def test_empty_message_list(self) -> None:
        """Нет действий -> подпись может сойтись, но переводов не найдётся.

        Пустой список действий — валидное (хоть и бессмысленное) сообщение,
        поэтому проверка подписи проходит. Ошибка возникает при попытке
        получить переводы: их нет.
        """
        boc = build_external([], self.private_key)

        with self.assertRaises(BocParseError) as ctx:
            parse_jetton_transfers(boc)
        self.assertIn("нет ни одного", str(ctx.exception).lower())


class WalletV4Tests(unittest.TestCase):
    """V4 должен продолжать работать, пока такие кошельки в ходу."""

    def setUp(self) -> None:
        self.public_key, self.private_key = new_keypair()

    def _build_v4(self) -> str:
        import base64

        from nacl.signing import SigningKey
        from pytoniq_core import begin_cell

        from tests.ton_builder import VALID_UNTIL

        message = transfer_message(QUERY_A, AMOUNT_A)
        item = (
            begin_cell().store_uint(3, 8).store_ref(message.serialize()).end_cell()
        )
        body = (
            begin_cell()
            .store_uint(0, 32)
            .store_uint(VALID_UNTIL, 32)
            .store_uint(7, 32)
            .store_uint(1, 8)  # op = send messages
            .store_ref(item)
            .end_cell()
        )
        signature = SigningKey(self.private_key[:32]).sign(body.hash).signature
        external = (
            begin_cell()
            .store_bytes(signature)
            .store_uint(0, 32)
            .store_uint(VALID_UNTIL, 32)
            .store_uint(7, 32)
            .store_uint(1, 8)
            .store_ref(item)
            .end_cell()
        )
        return base64.b64encode(external.to_boc()).decode()

    def test_v4_parsed_and_verified(self) -> None:
        boc = self._build_v4()

        transfers = parse_jetton_transfers(boc)
        self.assertEqual(len(transfers), 1)
        self.assertEqual(transfers[0]["queryId"], str(QUERY_A))
        self.assertEqual(verify_boc_signature(boc, self.public_key), "ok")


if __name__ == "__main__":
    unittest.main()
