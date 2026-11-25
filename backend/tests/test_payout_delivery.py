"""Проверка доставки ROOT: bounce не должен считаться выплатой.

Реальный случай (первая выплата на testnet): кошелёк отправил transfer на
jetton-кошелёк игрока, которого ещё НЕ СУЩЕСТВУЕТ. TON отбил сообщение
(bounce, op 0xffffffff), деньги остались у владельца. Транзакция при этом
успешна, а заявка была помечена confirmed.

Правильное доказательство — входящий internal_transfer (0x178d4519) на
jetton-кошелёк получателя с нашим query_id и суммой: его публикует jetton-
кошелёк отправителя, и он существует только при реальном зачислении.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from pytoniq_core import begin_cell

from app import ton_payout_lookup as lookup

QUERY_ID = 178326773585132116
AMOUNT = 15500000000
RECIPIENT_JETTON = "EQDDpvK-wo5TZqTY0-1hFjUaUt0K8DkZ5Qw-dsD75yeIF1tN"


def internal_transfer_body(query_id: int, amount: int) -> str:
    """Тело internal_transfer в base64 — как в raw_body у tonapi."""
    cell = (
        begin_cell()
        .store_uint(0x178D4519, 32)  # op internal_transfer
        .store_uint(query_id, 64)
        .store_coins(amount)
        .store_uint(0, 1)  # from: addr_none (NLP разбор не нужен)
        .end_cell()
    )
    return __import__("base64").b64encode(cell.to_boc()).decode()


def transfer_body(query_id: int, amount: int, dest: str) -> str:
    """Тело transfer (0xf8a7ea5) — исходящее сообщение кошелька выплат."""
    from pytoniq_core import Address

    cell = (
        begin_cell()
        .store_uint(0xF8A7EA5, 32)
        .store_uint(query_id, 64)
        .store_coins(amount)
        .store_address(Address(dest))
        .store_address(None)  # response_destination
        .store_bit(0)  # custom_payload: empty
        .store_coins(1)  # forward_ton_amount
        .store_bit(0)  # forward_payload: empty cell
        .end_cell()
    )
    return __import__("base64").b64encode(cell.to_boc()).decode()


class ParseInternalTransferTests(unittest.TestCase):
    def test_parses_query_id_and_amount(self) -> None:
        body = internal_transfer_body(QUERY_ID, AMOUNT)
        parsed = lookup._parse_internal_transfer({"raw_body": body})
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["queryId"], str(QUERY_ID))
        self.assertEqual(parsed["amountNano"], AMOUNT)

    def test_other_op_ignored(self) -> None:
        """transfer от отправителя — не доказательство доставки."""
        body = transfer_body(QUERY_ID, AMOUNT, RECIPIENT_JETTON)
        self.assertIsNone(lookup._parse_internal_transfer({"raw_body": body}))

    def test_broken_body_does_not_raise(self) -> None:
        self.assertIsNone(lookup._parse_internal_transfer({"raw_body": "AAAA"}))
        self.assertIsNone(lookup._parse_internal_transfer({}))


class LookupDeliveredTests(unittest.IsolatedAsyncioTestCase):
    """Проверка _lookup_async на подставных ответах индексера."""

    def _patch_http(self, pages: list[dict]):
        """Подменить httpx.AsyncClient.get, отдавая страницы по порядку."""

        class FakeResponse:
            def __init__(self, payload: dict) -> None:
                self._payload = payload

            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return self._payload

        class FakeClient:
            def __init__(self, *args, **kwargs) -> None:
                self.calls = 0

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc) -> None:
                return None

            async def get(self, url, params=None):
                index = min(self.calls, len(pages) - 1)
                self.calls += 1
                return FakeResponse(pages[index])

        return patch.object(lookup.httpx, "AsyncClient", FakeClient)

    def test_incoming_transfer_means_delivered(self) -> None:
        """Зачисление на jetton-кошелёк получателя = доставлено."""
        page = {
            "transactions": [
                {
                    "success": True,
                    "hash": "abc123",
                    "lt": 100,
                    "in_msg": {
                        "op_code": "0x178d4519",
                        "bounced": False,
                        "raw_body": internal_transfer_body(QUERY_ID, AMOUNT),
                    },
                }
            ]
        }
        with self._patch_http([page]):
            result = __import__("asyncio").run(
                lookup._lookup_async(str(QUERY_ID), AMOUNT, RECIPIENT_JETTON)
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result["delivered"])
        self.assertEqual(result["txHash"], "abc123")

    def test_bounced_transaction_not_delivered(self) -> None:
        """Отбитое сообщение (success=False) доставкой не считается."""
        page = {
            "transactions": [
                {
                    "success": False,
                    "hash": "bounced",
                    "lt": 100,
                    "in_msg": {
                        "op_code": "0x0f8a7ea5",
                        "bounced": True,
                        "raw_body": "",
                    },
                }
            ]
        }
        with self._patch_http([page]):
            result = __import__("asyncio").run(
                lookup._lookup_async(str(QUERY_ID), AMOUNT, RECIPIENT_JETTON)
            )

        self.assertIsNone(result)

    def test_wrong_amount_not_delivered(self) -> None:
        page = {
            "transactions": [
                {
                    "success": True,
                    "hash": "abc",
                    "lt": 100,
                    "in_msg": {
                        "op_code": "0x178d4519",
                        "bounced": False,
                        "raw_body": internal_transfer_body(QUERY_ID, AMOUNT + 1),
                    },
                }
            ]
        }
        with self._patch_http([page]):
            result = __import__("asyncio").run(
                lookup._lookup_async(str(QUERY_ID), AMOUNT, RECIPIENT_JETTON)
            )

        self.assertIsNone(result)

    def test_sent_but_not_delivered_flagged(self) -> None:
        """Фолбэк без адреса получателя: факт отправки, delivered=False."""
        page = {
            "transactions": [
                {
                    "success": True,
                    "hash": "sent-only",
                    "lt": 100,
                    "out_msgs": [
                        {
                            "bounced": False,
                            "raw_body": transfer_body(
                                QUERY_ID, AMOUNT, RECIPIENT_JETTON
                            ),
                        }
                    ],
                }
            ]
        }
        with self._patch_http([page]):
            with patch.object(lookup, "_read_payout_wallet", return_value=RECIPIENT_JETTON):
                result = __import__("asyncio").run(
                    lookup._lookup_async(str(QUERY_ID), AMOUNT, None)
                )

        self.assertIsNotNone(result)
        assert result is not None
        # Главное: не выдаём «отправлено» за «доставлено».
        self.assertFalse(result["delivered"])


if __name__ == "__main__":
    unittest.main()
