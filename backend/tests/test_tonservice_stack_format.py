"""Формат стека TonCenter v2 — было сломано, ловилось только на живом API.

История: _encode_stack отправлял {"type": "slice", "value": ...}, а TonCenter v2
ждёт пары ["slice", {"bytes": ...}]. Ответ 422 «Wrong type. Expected:
kArrayValue, actual: kObjectValue». Результат на проде:
  * get_wallet_address не отвечал -> адреса jetton-кошельков не вычислялись ->
    кнопка «Оплатить батч» заблокирована;
  * get_wallet_data не отвечал -> парсер депозитов не мог определить владельца.

Ни один тест этого не ловил: и deposit_service, и payout-тесты используют
моки провайдера, поэтому реальный JSON-формат не проверялся. Эти тесты — на
формате, а не на моках.
"""
from __future__ import annotations

import base64
import unittest

from pytoniq_core import Address, begin_cell

from app.ton_service import _TonCenterError, _TonCenterProvider

# Реальный адрес jetton-кошелька кошелька выплат (testnet, проверен запросом).
PAYOUT_JETTON_WALLET = "0:2a45a040d12f9a672c030ce447ff21c809b7263c5ce8a67b588fec3d2686cfce"
PAYOUT_WALLET = "0QAqDpRYGNJLa4AqlgoLdTZK9FwCdS0xX0cwSur8LuTRz2I4"


def _address_slice_b64(address: str) -> str:
    """Slice-ячейка с адресом в base64 — то, что TonCenter принимает в stack."""
    cell = begin_cell().store_address(Address(address)).end_cell()
    return base64.b64encode(cell.to_boc()).decode()


class EncodeStackTests(unittest.TestCase):
    def test_address_encoded_as_pair(self) -> None:
        """Адрес -> ["slice", {"bytes": ...}], а не {"type": ..., "value": ...}."""
        encoded = _TonCenterProvider._encode_stack([Address(PAYOUT_WALLET)])

        self.assertEqual(len(encoded), 1)
        entry = encoded[0]
        self.assertIsInstance(entry, list, f"ожидалась пара, получено {type(entry)}")
        self.assertEqual(entry[0], "slice")
        self.assertIsInstance(entry[1], dict)
        self.assertIn("bytes", entry[1])

    def test_encoded_slice_round_trips_to_address(self) -> None:
        """Закодированный slice действительно содержит нужный адрес."""
        from pytoniq_core import Cell

        encoded = _TonCenterProvider._encode_stack([Address(PAYOUT_WALLET)])
        raw = base64.b64decode(encoded[0][1]["bytes"])
        address = Cell.one_from_boc(raw).begin_parse().load_address()
        self.assertEqual(
            address.to_str(is_user_friendly=False),
            Address(PAYOUT_WALLET).to_str(is_user_friendly=False),
        )

    def test_int_encoded_as_pair(self) -> None:
        encoded = _TonCenterProvider._encode_stack([7])
        self.assertEqual(encoded, [["num", "7"]])

    def test_unsupported_entry_rejected(self) -> None:
        with self.assertRaises(_TonCenterError):
            _TonCenterProvider._encode_stack(["строка"])


class DecodeStackTests(unittest.TestCase):
    def test_decodes_new_pair_format(self) -> None:
        """Ответ TonCenter v2: [["num", "0x…"], ["cell", {"bytes": …}]]."""
        address_slice = _address_slice_b64(PAYOUT_JETTON_WALLET)
        entries = [
            ["num", "0x16345785d8a0000"],
            ["cell", {"bytes": address_slice, "object": {"data": {}}}],
            ["slice", {"bytes": address_slice}],
        ]

        decoded = _TonCenterProvider._decode_stack(entries)

        self.assertEqual(len(decoded), 3)
        self.assertEqual(decoded[0], 0x16345785D8A0000)  # баланс из get_wallet_data
        self.assertEqual(
            decoded[1].to_str(is_user_friendly=False),
            Address(PAYOUT_JETTON_WALLET).to_str(is_user_friendly=False),
        )
        self.assertEqual(
            decoded[2].to_str(is_user_friendly=False),
            Address(PAYOUT_JETTON_WALLET).to_str(is_user_friendly=False),
        )

    def test_decodes_decimal_num(self) -> None:
        self.assertEqual(
            _TonCenterProvider._decode_stack([["num", "12345"]]), [12345]
        )

    def test_still_accepts_legacy_dict_format(self) -> None:
        """Старый формат {"type": "num", "value": …} не должен ломаться."""
        decoded = _TonCenterProvider._decode_stack([{"type": "num", "value": "42"}])
        self.assertEqual(decoded, [42])

    def test_unsupported_entry_rejected(self) -> None:
        with self.assertRaises(_TonCenterError):
            _TonCenterProvider._decode_stack(["что-то"])


class IndexerEndpointTests(unittest.TestCase):
    """Транспорт поиска транзакций: TonCenter getTransactions на тестнете не
    работает (500 lite server), поэтому поиск идёт через tonapi.

    settings — frozen dataclass, поэтому подменяем объект настроек целиком.
    """

    def _endpoint(self, network: str, configured: str = "") -> str:
        from types import SimpleNamespace
        from unittest.mock import patch

        from app import ton_payout_lookup

        fake = SimpleNamespace(
            ton_network=network,
            ton_indexer_endpoint=configured,
        )
        with patch.object(ton_payout_lookup, "settings", fake):
            return ton_payout_lookup._indexer_endpoint()

    def test_testnet_default(self) -> None:
        self.assertEqual(self._endpoint("testnet"), "https://testnet.tonapi.io/v2")

    def test_mainnet_default(self) -> None:
        self.assertEqual(self._endpoint("mainnet"), "https://tonapi.io/v2")

    def test_explicit_override_wins(self) -> None:
        self.assertEqual(
            self._endpoint("testnet", "https://example.org/v2/"),
            "https://example.org/v2",
        )


class OutMsgRawBodyTests(unittest.TestCase):
    """tonapi отдаёт тело сообщения в raw_body (base64 BOC), а не в msg_data."""

    def test_parses_raw_body_like_tonapi(self) -> None:
        from pytoniq_core import Address, begin_cell

        from app.ton_payout_lookup import _parse_transfer_from_out_msg

        body = (
            begin_cell()
            .store_uint(0xF8A7EA5, 32)
            .store_uint(424242424242, 64)
            .store_coins(500_000_000)
            .store_address(Address(PAYOUT_JETTON_WALLET))
            .store_address(None)
            .store_bit(0)
            .store_coins(0)
            .store_bit(0)
            .end_cell()
        )
        parsed = _parse_transfer_from_out_msg(
            {"raw_body": base64.b64encode(body.to_boc()).decode()}
        )

        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["queryId"], "424242424242")
        self.assertEqual(parsed["amountNano"], 500_000_000)

    def test_non_transfer_raw_body_skipped(self) -> None:
        from pytoniq_core import begin_cell

        from app.ton_payout_lookup import _parse_transfer_from_out_msg

        other = (
            begin_cell().store_uint(0x7362D09C, 32).store_uint(1, 64).end_cell()
        )
        self.assertIsNone(
            _parse_transfer_from_out_msg(
                {"raw_body": base64.b64encode(other.to_boc()).decode()}
            )
        )


if __name__ == "__main__":
    unittest.main()
