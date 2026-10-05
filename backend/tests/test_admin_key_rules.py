from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.admin_key_rules import (
    _ensure_no_existing_rule,
    _serialize_key_rule,
    _validate_item_is_key,
)


class AdminKeyRulesTests(unittest.TestCase):
    def test_validate_item_is_key_rejects_missing_item(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)

        with self.assertRaises(HTTPException) as captured:
            _validate_item_is_key(session, item_id="item-missing")

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Указанный item_id не существует.",
        )

    def test_validate_item_is_key_rejects_non_key_category(self) -> None:
        item = SimpleNamespace(category="ARCHIVE")
        session = SimpleNamespace(get=lambda *args: item)

        with self.assertRaises(HTTPException) as captured:
            _validate_item_is_key(session, item_id="item-archive")

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("category=KEY", captured.exception.detail)

    def test_validate_item_is_key_accepts_key_category(self) -> None:
        item = SimpleNamespace(category="KEY")
        session = SimpleNamespace(get=lambda *args: item)

        result = _validate_item_is_key(session, item_id="item-key")

        self.assertIs(result, item)

    def test_validate_item_is_key_accepts_lowercase_category(self) -> None:
        item = SimpleNamespace(category="key")
        session = SimpleNamespace(get=lambda *args: item)

        result = _validate_item_is_key(session, item_id="item-key-lower")

        self.assertIs(result, item)

    def test_validate_item_is_key_accepts_mixed_case_category(self) -> None:
        item = SimpleNamespace(category="Key")
        session = SimpleNamespace(get=lambda *args: item)

        result = _validate_item_is_key(session, item_id="item-key-mixed")

        self.assertIs(result, item)

    def test_ensure_no_existing_rule_rejects_duplicate_rule(self) -> None:
        session = SimpleNamespace(scalar=lambda _statement: "key-rule-existing")

        with self.assertRaises(HTTPException) as captured:
            _ensure_no_existing_rule(session, item_id="item-key")

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Для этого Item правила ключей уже существуют.",
        )

    def test_ensure_no_existing_rule_accepts_without_duplicate(self) -> None:
        session = SimpleNamespace(scalar=lambda _statement: None)

        _ensure_no_existing_rule(session, item_id="item-key")

    def test_ensure_no_existing_rule_passes_exclude_rule_id_into_statement(
        self,
    ) -> None:
        session = SimpleNamespace()

        with patch.object(
            session, "scalar", return_value=None, create=True
        ) as scalar_mock:
            _ensure_no_existing_rule(
                session,
                item_id="item-key",
                exclude_rule_id="key-rule-other",
            )

        statement = scalar_mock.call_args.args[0]
        compiled_sql = str(
            statement.compile(compile_kwargs={"literal_binds": True})
        )

        self.assertIn("!=", compiled_sql)
        self.assertIn("'key-rule-other'", compiled_sql)
        self.assertIn("'item-key'", compiled_sql)

    def test_serialize_key_rule_maps_to_camel_case_with_iso_dates(self) -> None:
        rule = SimpleNamespace(
            id="key-rule-1",
            item_id="item-key-1",
            is_consumable=True,
            stack_limit=5,
            sort_order=10,
            transfer_forbidden=False,
            sale_forbidden=True,
            trade_forbidden=False,
            created_at=datetime(2026, 10, 5, 12, 30, 0),
            updated_at=datetime(2026, 10, 5, 13, 45, 0),
        )

        result = _serialize_key_rule(rule)

        self.assertEqual(
            result,
            {
                "id": "key-rule-1",
                "itemId": "item-key-1",
                "isConsumable": True,
                "stackLimit": 5,
                "sortOrder": 10,
                "transferForbidden": False,
                "saleForbidden": True,
                "tradeForbidden": False,
                "createdAt": "2026-10-05T12:30:00",
                "updatedAt": "2026-10-05T13:45:00",
            },
        )

    def test_serialize_key_rule_returns_none_for_missing_dates(self) -> None:
        rule = SimpleNamespace(
            id="key-rule-2",
            item_id="item-key-2",
            is_consumable=False,
            stack_limit=1,
            sort_order=0,
            transfer_forbidden=True,
            sale_forbidden=True,
            trade_forbidden=True,
            created_at=None,
            updated_at=None,
        )

        result = _serialize_key_rule(rule)

        self.assertIsNone(result["createdAt"])
        self.assertIsNone(result["updatedAt"])
        self.assertEqual(result["itemId"], "item-key-2")


if __name__ == "__main__":
    unittest.main()
