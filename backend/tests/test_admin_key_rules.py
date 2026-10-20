from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, delete, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_key_rules import (
    _ensure_no_existing_rule,
    _serialize_key_rule,
    _validate_item_is_key,
)

import os
import subprocess
import sys
import tempfile
import uuid

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


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
            price=99,
            sort_order=10,
            transfer_forbidden=False,
            sale_forbidden=True,
            trade_forbidden=False,
            created_at=datetime(2026, 10, 5, 12, 30, 0),
            updated_at=datetime(2026, 10, 5, 13, 45, 0),
        )
        item = SimpleNamespace(
            title="Ключ A-01",
            code="KEY_A01",
            symbol="🔑",
            status="published",
        )

        result = _serialize_key_rule(rule, item)

        self.assertEqual(
            result,
            {
                "id": "key-rule-1",
                "itemId": "item-key-1",
                "isConsumable": True,
                "stackLimit": 5,
                "price": 99,
                "sortOrder": 10,
                "transferForbidden": False,
                "saleForbidden": True,
                "tradeForbidden": False,
                "itemTitle": "Ключ A-01",
                "itemCode": "KEY_A01",
                "itemSymbol": "🔑",
                "itemStatus": "published",
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
            price=None,
            sort_order=0,
            transfer_forbidden=True,
            sale_forbidden=True,
            trade_forbidden=True,
            created_at=None,
            updated_at=None,
        )
        item = SimpleNamespace(
            title="Ключ B",
            code="KEY_B",
            symbol=None,
            status="draft",
        )

        result = _serialize_key_rule(rule, item)

        self.assertIsNone(result["createdAt"])
        self.assertIsNone(result["updatedAt"])
        self.assertEqual(result["itemId"], "item-key-2")
        self.assertEqual(result["itemTitle"], "Ключ B")
        self.assertEqual(result["itemCode"], "KEY_B")
        self.assertIsNone(result["itemSymbol"])
        self.assertEqual(result["itemStatus"], "draft")


class AdminKeyRulesDbTests(unittest.TestCase):
    """Admin-ui-a2: расширенная сериализация KeyRules + dropdown items.

    Live SQLite + alembic upgrade head (паттерн test_admin_teams.py):
    disposable БД, permission key_rules.read создаётся миграцией-сидом.
    Endpoint-функции вызываются напрямую с замоканным SessionLocal.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-key-rules-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "admin-key-rules.sqlite3"
        database_url = f"sqlite:///{cls.database_path}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url

        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND_ROOT / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        cls.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(cls.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        from app import admin_key_rules

        cls.admin_key_rules = admin_key_rules
        cls._session_local_patch = patch.object(
            admin_key_rules, "SessionLocal", cls.SessionLocal
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def setUp(self) -> None:
        """Изоляция тестов: таблицы items/key_rules общие для класса."""
        from app.models import Item, KeyRules

        with self.SessionLocal.begin() as session:
            session.execute(delete(KeyRules))
            session.execute(delete(Item))

    # ---- Fixtures и хелперы -------------------------------------------------

    def _make_admin(self):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                    is_deleted=False,
                )
            )

        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _make_item(
        self,
        *,
        category: str = "KEY",
        status: str = "published",
        title: str | None = None,
        symbol: str | None = None,
        code: str | None = None,
    ) -> dict:
        from app.models import Item

        item_id = f"item-{uuid.uuid4().hex}"
        item_code = code or f"CODE_{item_id[-6:].upper()}"
        item_title = title or f"Title-{item_id[-6:]}"

        with self.SessionLocal.begin() as session:
            session.add(
                Item(
                    id=item_id,
                    slug=item_id,
                    code=item_code,
                    title=item_title,
                    symbol=symbol,
                    category=category,
                    rarity="common",
                    is_unique=True,
                    content={},
                    status=status,
                )
            )

        return {
            "id": item_id,
            "code": item_code,
            "title": item_title,
            "symbol": symbol,
            "status": status,
        }

    def _make_key_rule(self, item_id: str) -> str:
        from app.models import KeyRules

        rule_id = f"key-rule-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(KeyRules(id=rule_id, item_id=item_id))
        return rule_id


# ---- Тесты --------------------------------------------------------------

    def test_list_key_rules_returns_item_metadata(self) -> None:
        item = self._make_item(category="KEY", status="published", symbol="🔑")
        self._make_key_rule(item["id"])

        result = self.admin_key_rules.list_admin_key_rules(
            _admin=self._make_admin()
        )

        self.assertEqual(len(result["keyRules"]), 1)
        rule = result["keyRules"][0]
        self.assertEqual(rule["itemId"], item["id"])
        self.assertEqual(rule["itemTitle"], item["title"])
        self.assertEqual(rule["itemCode"], item["code"])
        self.assertEqual(rule["itemSymbol"], item["symbol"])
        self.assertEqual(rule["itemStatus"], item["status"])

    def test_list_key_items_returns_only_key_category(self) -> None:
        key_item = self._make_item(category="KEY", status="published")
        self._make_item(category="ARCHIVE", status="published")

        result = self.admin_key_rules.list_admin_key_items(
            _actor=self._make_admin()
        )

        items = result["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], key_item["id"])
        self.assertEqual(items[0]["title"], key_item["title"])
        self.assertEqual(items[0]["status"], "published")

    def test_list_key_items_filters_by_status(self) -> None:
        published_item = self._make_item(category="KEY", status="published")
        self._make_item(category="KEY", status="draft")

        published = self.admin_key_rules.list_admin_key_items(
            status="published",
            _actor=self._make_admin(),
        )
        all_items = self.admin_key_rules.list_admin_key_items(
            status="all",
            _actor=self._make_admin(),
        )

        self.assertEqual(len(published["items"]), 1)
        self.assertEqual(published["items"][0]["id"], published_item["id"])
        self.assertTrue(
            all(item["status"] == "published" for item in published["items"])
        )
        self.assertEqual(len(all_items["items"]), 2)

    def test_create_key_item_creates_item_and_rule(self) -> None:
        from app.admin_key_rules import CreateKeyItemPayload
        from app.models import Item, KeyRules

        result = self.admin_key_rules.create_admin_key_item(
            payload=CreateKeyItemPayload(title="Ключ тест", code="TEST_KEY_1"),
            request=None,
            actor=self._make_admin(),
        )

        key_rule = result["keyRule"]
        self.assertTrue(key_rule["itemId"])
        self.assertEqual(key_rule["itemTitle"], "Ключ тест")
        self.assertEqual(key_rule["itemCode"], "TEST_KEY_1")

        with self.SessionLocal() as session:
            rule = session.get(KeyRules, key_rule["id"])
            self.assertIsNotNone(rule)
            item = session.get(Item, rule.item_id)
            self.assertIsNotNone(item)
            self.assertEqual(item.category, "KEY")
            self.assertEqual(item.code, "TEST_KEY_1")
            self.assertEqual(item.title, "Ключ тест")
            self.assertEqual(item.status, "published")

    def test_create_key_item_duplicate_code_returns_409(self) -> None:
        from app.admin_key_rules import CreateKeyItemPayload

        self._make_item(category="KEY", status="published", code="TEST_KEY_2")

        with self.assertRaises(HTTPException) as captured:
            self.admin_key_rules.create_admin_key_item(
                payload=CreateKeyItemPayload(
                    title="Дубликат",
                    code="TEST_KEY_2",
                ),
                request=None,
                actor=self._make_admin(),
            )

        self.assertEqual(captured.exception.status_code, 409)
        self.assertIn("code", captured.exception.detail)

    def test_create_key_item_sets_default_flags(self) -> None:
        from app.admin_key_rules import CreateKeyItemPayload

        result = self.admin_key_rules.create_admin_key_item(
            payload=CreateKeyItemPayload(
                title="Без явных флагов",
                code="TEST_KEY_3",
            ),
            request=None,
            actor=self._make_admin(),
        )

        key_rule = result["keyRule"]
        self.assertTrue(key_rule["isConsumable"])
        self.assertTrue(key_rule["transferForbidden"])
        self.assertTrue(key_rule["saleForbidden"])
        self.assertTrue(key_rule["tradeForbidden"])
        self.assertEqual(key_rule["stackLimit"], 1)


if __name__ == "__main__":
    unittest.main()
