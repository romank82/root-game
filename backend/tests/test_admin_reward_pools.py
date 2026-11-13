from datetime import datetime
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from app.admin_reward_pools import (
    _replace_entries,
    _serialize_entry,
    _serialize_pool,
    _validate_entries,
)


def _entry(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "reward_type": "currency",
        "amount": 50,
        "item_id": None,
        "reward_value": {"currency": "ROOT"},
        "weight": 1,
        "sort_order": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class AdminRewardPoolsEntryValidationTests(unittest.TestCase):
    def test_validate_entries_rejects_unknown_reward_type(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(reward_type="unknown")]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("reward_type", captured.exception.detail)

    def test_validate_entries_currency_rejects_missing_amount(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(amount=None)]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("amount", captured.exception.detail)

    def test_validate_entries_currency_rejects_non_positive_amount(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(amount=0)]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("amount", captured.exception.detail)

    def test_validate_entries_currency_rejects_non_root_currency(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(reward_value={"currency": "USD"})]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("currency", captured.exception.detail)

    def test_validate_entries_currency_accepts_root_currency(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(weight=100)]

        try:
            _validate_entries(session, entries)
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"Валидация currency ROOT не должна падать: {exc.detail}")

    def test_validate_entries_item_rejects_missing_item_id(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(reward_type="item", item_id=None)]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("item_id", captured.exception.detail)

    def test_validate_entries_item_rejects_unknown_item_id(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(reward_type="item", item_id="item-missing")]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("item_id", captured.exception.detail)

    def test_validate_entries_item_accepts_existing_item_id(self) -> None:
        session = SimpleNamespace(get=lambda *args: object())
        entries = [_entry(reward_type="item", item_id="item-1")]

        try:
            _validate_entries(session, entries)
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"Валидация item не должна падать: {exc.detail}")

    def test_validate_entries_rejects_zero_weight(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(weight=0)]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("weight", captured.exception.detail)

    def test_validate_entries_rejects_negative_weight(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(weight=-1)]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("weight", captured.exception.detail)

    def test_validate_entries_rejects_weight_above_one_million(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)
        entries = [_entry(weight=1_000_001)]

        with self.assertRaises(HTTPException) as captured:
            _validate_entries(session, entries)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("weight", captured.exception.detail)


class AdminRewardPoolsReplacementTests(unittest.TestCase):
    def test_replace_entries_deletes_old_entries_and_adds_new_ones(self) -> None:
        deleted: list[str] = []
        added: list[object] = []

        def fake_delete(entry: object) -> None:
            deleted.append(entry.id)

        def fake_add(entry: object) -> None:
            added.append(entry)

        session = SimpleNamespace(
            scalars=lambda statement: SimpleNamespace(
                all=lambda: [SimpleNamespace(id="old-entry")]
            ),
            delete=fake_delete,
            add=fake_add,
            flush=lambda: None,
        )
        entries = [
            _entry(reward_type="currency", amount=100, weight=10, sort_order=0),
            _entry(reward_type="item", item_id="item-1", weight=20, sort_order=1),
        ]

        _replace_entries(session, pool_id="pool-1", entries=entries)

        self.assertEqual(deleted, ["old-entry"])
        self.assertEqual(len(added), 2)

        first = added[0]
        self.assertEqual(first.pool_id, "pool-1")
        self.assertEqual(first.reward_type, "currency")
        self.assertEqual(first.amount, 100)
        self.assertEqual(first.weight, 10)
        self.assertEqual(first.sort_order, 0)

        second = added[1]
        self.assertEqual(second.reward_type, "item")
        self.assertEqual(second.item_id, "item-1")
        self.assertEqual(second.weight, 20)
        self.assertEqual(second.sort_order, 1)


class AdminRewardPoolsSerializationTests(unittest.TestCase):
    def test_serialize_entry_maps_camel_case_with_weight_and_iso_dates(self) -> None:
        entry = SimpleNamespace(
            id="entry-1",
            reward_type="currency",
            amount=50,
            item_id=None,
            reward_value={"currency": "ROOT"},
            weight=5,
            sort_order=3,
        )

        serialized = _serialize_entry(entry)

        self.assertEqual(serialized["id"], "entry-1")
        self.assertEqual(serialized["rewardType"], "currency")
        self.assertEqual(serialized["amount"], 50)
        self.assertIsNone(serialized["itemId"])
        self.assertEqual(serialized["rewardValue"], {"currency": "ROOT"})
        self.assertEqual(serialized["weight"], 5)
        self.assertEqual(serialized["sortOrder"], 3)

    def test_serialize_pool_includes_nested_entries(self) -> None:
        session = SimpleNamespace(
            scalars=lambda statement: SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        id="entry-1",
                        reward_type="currency",
                        amount=50,
                        item_id=None,
                        reward_value={"currency": "ROOT"},
                        weight=5,
                        sort_order=3,
                    )
                ]
            )
        )
        pool = SimpleNamespace(
            id="pool-1",
            slug="daily-rewards",
            title="Daily rewards",
            description=None,
            status="published",
            sort_order=5,
            created_at=datetime(2026, 5, 1, 12, 30, 45),
            updated_at=datetime(2026, 5, 2, 9, 0, 0),
        )

        serialized = _serialize_pool(session, pool)

        self.assertEqual(serialized["id"], "pool-1")
        self.assertEqual(serialized["slug"], "daily-rewards")
        self.assertEqual(serialized["status"], "published")
        self.assertEqual(serialized["sortOrder"], 5)
        self.assertEqual(serialized["createdAt"], "2026-05-01T12:30:45")
        self.assertEqual(serialized["updatedAt"], "2026-05-02T09:00:00")
        self.assertEqual(
            serialized["entries"],
            [
                {
                    "id": "entry-1",
                    "rewardType": "currency",
                    "amount": 50,
                    "itemId": None,
                    "rewardValue": {"currency": "ROOT"},
                    "weight": 5,
                    "sortOrder": 3,
                }
            ],
        )

    def test_serialize_pool_returns_empty_entries_list(self) -> None:
        session = SimpleNamespace(
            scalars=lambda statement: SimpleNamespace(all=lambda: [])
        )
        pool = SimpleNamespace(
            id="pool-2",
            slug="empty-pool",
            title="Empty pool",
            description=None,
            status="draft",
            sort_order=0,
            created_at=None,
            updated_at=None,
        )

        serialized = _serialize_pool(session, pool)

        self.assertEqual(serialized["entries"], [])
        self.assertIsNone(serialized["createdAt"])
        self.assertIsNone(serialized["updatedAt"])


if __name__ == "__main__":
    unittest.main()