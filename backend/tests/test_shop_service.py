"""Sprint 8.16: общий магазин ключей (shop_service) — unit-тесты.

Не затрагивает fallback-механику (test_fallback_shop.py): каталог ключей —
отдельный сервис, fallback-покупка остаётся неизменной. Проверяются:
- публичный список каталога (только published KEY items, owned per player);
- покупка: атомарный debit ROOT + credit в инвентарь;
- идемпотентность ledger-проводки (guard на reference_id) и семантика
  «повторный POST с тем же state = новая покупка» (quota-free магазин);
- ошибки: нехватка ROOT / неизвестный / не-KEY item.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError
from app.shop_service import (
    SHOP_ENABLED_KEY,
    SHOP_PRICE_ROOT_KEY,
    SHOP_PURCHASE_REFERENCE_TYPE,
    list_catalog_items,
    purchase_catalog_item,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class ShopCatalogTests(unittest.TestCase):
    """8.16: unit-тесты общего магазина ключей (pure service level)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-shop-catalog-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "shop-catalog.sqlite3"
        )
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

    def setUp(self) -> None:
        """Изоляция: каждый тест копирует pristine DB (после alembic upgrade head).

        Очистка общей базы невозможна: ledger и inventory_events покрыты
        триггерами immutable (DELETE запрещён), поэтому каждый тест получает
        отдельную копию и полностью изолирован от остальных.
        """
        self._test_db_path = self.database_path.with_name(
            f"shop-{uuid.uuid4().hex}.sqlite3"
        )
        shutil.copyfile(self.database_path, self._test_db_path)
        test_database_url = f"sqlite:///{self._test_db_path}"
        self.engine = create_engine(
            test_database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def tearDown(self) -> None:
        self.engine.dispose()
        self._test_db_path.unlink(missing_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------------
    def _fixture(
        self,
        *,
        with_owned: int = 0,
    ) -> dict[str, str]:
        """Игрок + 3 item: published KEY, draft KEY, published non-KEY."""
        from app.models import GamePlayer, Item

        suffix = uuid.uuid4().hex
        ids = {
            "player": f"player-{suffix}",
            "item_key_pub": f"item-key-pub-{suffix}",
            "item_key_draft": f"item-key-draft-{suffix}",
            "item_non_key": f"item-consumable-{suffix}",
        }
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=ids["player"],
                    display_name="Shop test player",
                    auth_provider="test",
                    external_id=f"test-{suffix}",
                    status="active",
                )
            )
            session.add_all(
                [
                    Item(
                        id=ids["item_key_pub"],
                        slug=f"key-pub-{suffix}",
                        code=f"KEY-PUB-{suffix[:12]}",
                        title="Published key",
                        description="Каталог-ключ (published)",
                        symbol="KEY",
                        category="KEY",
                        rarity="common",
                        is_unique=False,
                        content={"schemaVersion": 1},
                        status="published",
                    ),
                    Item(
                        id=ids["item_key_draft"],
                        slug=f"key-draft-{suffix}",
                        code=f"KEY-DRAFT-{suffix[:12]}",
                        title="Draft key",
                        description="Каталог-ключ (draft)",
                        symbol="KEY",
                        category="KEY",
                        rarity="common",
                        is_unique=False,
                        content={"schemaVersion": 1},
                        status="draft",
                    ),
                    Item(
                        id=ids["item_non_key"],
                        slug=f"consumable-{suffix}",
                        code=f"POTION-{suffix[:12]}",
                        title="Consumable",
                        description="Не KEY — в каталог не попадает",
                        symbol="P",
                        category="consumable",
                        rarity="common",
                        is_unique=False,
                        content={"schemaVersion": 1},
                        status="published",
                    ),
                ]
            )
            session.flush()
            if with_owned:
                from app.models import PlayerItem

                session.add(
                    PlayerItem(
                        id=f"player-item-owned-{suffix}",
                        player_id=ids["player"],
                        item_id=ids["item_key_pub"],
                        quantity=with_owned,
                        obtained_from_type="test_seed",
                        obtained_from_id=None,
                    )
                )
        return ids

    def _set_setting(self, key: str, value) -> None:
        """Обновить системную настройку (строки сеются миграцией)."""
        from app.models import SystemSetting

        with self.SessionLocal.begin() as session:
            setting = session.get(SystemSetting, key)
            self.assertIsNotNone(
                setting, f"Настройка {key} должна быть посеяна миграцией"
            )
            setting.value_json = value

    def _seed_root_wallet(self, player_id: str, amount: int) -> str:
        """Кошелёк с кредитной проводкой — игровой ROOT на старте (как 4.1)."""
        from app.models import Wallet, WalletTransaction

        wallet_id = f"wallet-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Wallet(
                    id=wallet_id,
                    player_id=player_id,
                    currency="ROOT",
                    available_balance=amount,
                    locked_balance=0,
                )
            )
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet_id,
                    amount=amount,
                    balance_after=amount,
                    transaction_type="credit",
                    reason="Test seed balance",
                    reference_type="test_seed",
                    reference_id=f"seed-{uuid.uuid4().hex}",
                    metadata_json={},
                )
            )
        return wallet_id

    # ---- Read-хелперы --------------------------------------------------------
    def _wallet_balance(self, player_id: str) -> int | None:
        from app.models import Wallet

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            return wallet.available_balance if wallet is not None else None

    def _owned(self, player_id: str, item_id: str) -> int:
        from app.models import PlayerItem

        with self.SessionLocal() as session:
            row = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == player_id,
                    PlayerItem.item_id == item_id,
                )
            )
            return row.quantity if row is not None else 0

    def _shop_reference_ids(self, player_id: str) -> list[str]:
        """reference_id всех shop_purchase-проводок игрока (sorted)."""
        from app.models import Wallet, WalletTransaction

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            if wallet is None:
                return []
            rows = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == SHOP_PURCHASE_REFERENCE_TYPE,
                )
            ).all()
            return sorted(tx.reference_id for tx in rows)

    def _count_shop_transactions(self, player_id: str) -> int:
        return len(self._shop_reference_ids(player_id))

    def _count_shop_events(self, player_id: str, item_id: str) -> int:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import PlayerItem

        with self.SessionLocal() as session:
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == player_id,
                    PlayerItem.item_id == item_id,
                )
            )
            if player_item is None:
                return 0
            rows = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.player_item_id == player_item.id,
                    InventoryEvent.event_type == "credited",
                    InventoryEvent.reference_type
                    == SHOP_PURCHASE_REFERENCE_TYPE,
                )
            ).all()
            return len(rows)

    def _commit_ledger_only_shop_debit(
        self,
        wallet_id: str,
        item_id: str,
        price: int,
    ) -> None:
        """Коммитит ledger-проводку покупки без инкремента стека.

        Симулирует снимок «проигравшего» параллельного POST в гонке: проводка
        с reference_id = item_id:1 уже закоммичена, а player_item.quantity в
        этой сессии ещё 0 — ровно то состояние, в котором guard должен вернуть
        текущий результат БЕЗ повторного списания ROOT.
        """
        from app.models import Wallet, WalletTransaction

        with self.SessionLocal.begin() as session:
            wallet = session.get(Wallet, wallet_id)
            self.assertIsNotNone(wallet)
            wallet.available_balance -= price
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet_id,
                    amount=price,
                    balance_after=wallet.available_balance,
                    transaction_type="debit",
                    reason=f"Shop purchase: {item_id}",
                    reference_type=SHOP_PURCHASE_REFERENCE_TYPE,
                    reference_id=f"{item_id}:1",
                    metadata_json={"itemId": item_id},
                )
            )

    # ---- 8.16.1: публичный список каталога -----------------------------------
    def test_list_catalog_items_empty_when_disabled(self):
        ids = self._fixture()
        # Магазин выключен админом: явно ставим False (head-миграции дают
        # True по умолчанию). Явное значение — тест не зависит от порядка.
        self._set_setting(SHOP_ENABLED_KEY, False)
        with self.SessionLocal.begin() as session:
            items = list_catalog_items(session, ids["player"])
        self.assertEqual(items, [])

    def test_list_catalog_items_enabled_by_default(self):
        # Миграция 46acb135d92a ставит shop.catalog.enabled = True по
        # умолчанию (согласует БД с каталогом default_value=True). Никакого
        # явного _set_setting не нужно — pristine-копия БД уже enabled.
        ids = self._fixture()

        with self.SessionLocal.begin() as session:
            items = list_catalog_items(session, ids["player"])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["itemId"], ids["item_key_pub"])

    def test_list_catalog_items_only_published_key(self):
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)

        with self.SessionLocal.begin() as session:
            items = list_catalog_items(session, ids["player"])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["itemId"], ids["item_key_pub"])
        self.assertEqual(items[0]["category"], "KEY")
        self.assertEqual(items[0]["priceRoot"], 100)
        self.assertEqual(items[0]["owned"], 0)

    def test_list_catalog_items_with_owned(self):
        ids = self._fixture(with_owned=2)
        self._set_setting(SHOP_ENABLED_KEY, True)

        with self.SessionLocal.begin() as session:
            items = list_catalog_items(session, ids["player"])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["itemId"], ids["item_key_pub"])
        self.assertEqual(items[0]["owned"], 2)

    # ---- 8.20: per-key цена (key_rules.price) --------------------------------
    def _add_key_rule(self, item_id: str, price: int | None) -> None:
        """KeyRules для ключа каталога с заданной (или пустой) ценой."""
        from app.models import KeyRules

        with self.SessionLocal.begin() as session:
            session.add(
                KeyRules(
                    id=f"key-rules-{uuid.uuid4().hex}",
                    item_id=item_id,
                    is_consumable=True,
                    stack_limit=1,
                    price=price,
                )
            )

    def test_list_catalog_items_uses_key_rules_price(self):
        # 8.20: key_rules.price=50 имеет приоритет над глобальной (100).
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._add_key_rule(ids["item_key_pub"], price=50)

        with self.SessionLocal.begin() as session:
            items = list_catalog_items(session, ids["player"])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["itemId"], ids["item_key_pub"])
        self.assertEqual(items[0]["priceRoot"], 50)

    def test_list_catalog_items_price_null_falls_back_to_global(self):
        # 8.20: price NULL -> глобальная настройка shop.catalog.default_price_root.
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._set_setting(SHOP_PRICE_ROOT_KEY, 42)
        self._add_key_rule(ids["item_key_pub"], price=None)

        with self.SessionLocal.begin() as session:
            items = list_catalog_items(session, ids["player"])

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["priceRoot"], 42)

    def test_purchase_uses_key_rules_price(self):
        # 8.20: списание ROOT по per-key цене (50), а не по глобальной (100).
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._seed_root_wallet(ids["player"], 1000)
        self._add_key_rule(ids["item_key_pub"], price=50)

        with self.SessionLocal.begin() as session:
            result = purchase_catalog_item(
                session, ids["player"], ids["item_key_pub"]
            )

        self.assertTrue(result["purchased"])
        self.assertEqual(result["priceRoot"], 50)
        self.assertEqual(result["rootBalance"], 950)
        self.assertEqual(self._wallet_balance(ids["player"]), 950)

    # ---- 8.16.2: покупка ------------------------------------------------------
    def test_purchase_creates_player_item_and_debits_root(self):
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._seed_root_wallet(ids["player"], 1000)

        with self.SessionLocal.begin() as session:
            result = purchase_catalog_item(
                session, ids["player"], ids["item_key_pub"]
            )

        self.assertTrue(result["purchased"])
        self.assertEqual(result["itemId"], ids["item_key_pub"])
        self.assertEqual(result["priceRoot"], 100)
        self.assertEqual(result["rootBalance"], 900)
        self.assertEqual(result["owned"], 1)

        self.assertEqual(self._wallet_balance(ids["player"]), 900)
        self.assertEqual(self._owned(ids["player"], ids["item_key_pub"]), 1)
        self.assertEqual(self._count_shop_transactions(ids["player"]), 1)
        self.assertEqual(
            self._count_shop_events(ids["player"], ids["item_key_pub"]), 1
        )

    def test_purchase_idempotent(self):
        # Семантика quota-free магазина: повторный POST с тем же item — это
        # НОВАЯ покупка (reference_id = item_id:(quantity+1) растёт вместе со
        # стэком). Идемпотентность (один debit на одну проводку) защищает только
        # гонку двух одинаковых параллельных POST: «проигравший» видит уже
        # закоммиченную проводку и не списывает ROOT повторно.
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._seed_root_wallet(ids["player"], 1000)

        # (a) Последовательные покупки: каждая следующая — новая.
        with self.SessionLocal.begin() as session:
            first = purchase_catalog_item(
                session, ids["player"], ids["item_key_pub"]
            )
        self.assertEqual((first["rootBalance"], first["owned"]), (900, 1))

        with self.SessionLocal.begin() as session:
            second = purchase_catalog_item(
                session, ids["player"], ids["item_key_pub"]
            )
        self.assertEqual((second["rootBalance"], second["owned"]), (800, 2))

        self.assertEqual(
            self._shop_reference_ids(ids["player"]),
            [f"{ids['item_key_pub']}:1", f"{ids['item_key_pub']}:2"],
        )
        self.assertEqual(self._wallet_balance(ids["player"]), 800)
        self.assertEqual(self._owned(ids["player"], ids["item_key_pub"]), 2)
        self.assertEqual(
            self._count_shop_events(ids["player"], ids["item_key_pub"]), 2
        )

        # (b) Race-snapshot: проводка item:1 уже закоммичена, а в этой сессии
        # quantity ещё 0 → guard находит существующую проводку и возвращает
        # текущее состояние без повторного списания ROOT.
        ids_b = self._fixture()
        wallet_b = self._seed_root_wallet(ids_b["player"], 1000)
        self._commit_ledger_only_shop_debit(wallet_b, ids_b["item_key_pub"], 100)

        with self.SessionLocal.begin() as session:
            replay = purchase_catalog_item(
                session, ids_b["player"], ids_b["item_key_pub"]
            )
        self.assertEqual((replay["rootBalance"], replay["owned"]), (900, 0))
        self.assertEqual(self._wallet_balance(ids_b["player"]), 900)
        self.assertEqual(self._owned(ids_b["player"], ids_b["item_key_pub"]), 0)
        self.assertEqual(self._count_shop_transactions(ids_b["player"]), 1)
        self.assertEqual(
            self._count_shop_events(ids_b["player"], ids_b["item_key_pub"]), 0
        )

    def test_rebuy_after_consumed_key_creates_new_reference(self):
        # Регрессия «купил → потратил ключ → купил снова»: номер покупки
        # обязан браться из числа immutable-событий выдачи ключа, а не из
        # player_item.quantity (quantity убывает при расходовании ключа на
        # входе в миссию). Вторая покупка должна получить новый reference_id,
        # списать ROOT и выдать ключ, а не вернуть «успех» без проводки.
        from app.models import PlayerItem

        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._seed_root_wallet(ids["player"], 1000)

        with self.SessionLocal.begin() as session:
            first = purchase_catalog_item(
                session, ids["player"], ids["item_key_pub"]
            )
        self.assertEqual((first["rootBalance"], first["owned"]), (900, 1))

        # Имитация расхода ключа: mission_engine._apply_entry_debit уменьшает
        # quantity (и пишет отдельное consumed-событие), не трогая события
        # выдачи магазина. Для воспроизведения бага достаточно снизить
        # только quantity.
        with self.SessionLocal.begin() as session:
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item_key_pub"],
                )
            )
            self.assertIsNotNone(player_item)
            player_item.quantity -= 1
            session.flush()
        self.assertEqual(self._owned(ids["player"], ids["item_key_pub"]), 0)

        with self.SessionLocal.begin() as session:
            second = purchase_catalog_item(
                session, ids["player"], ids["item_key_pub"]
            )
        self.assertEqual((second["rootBalance"], second["owned"]), (800, 1))

        # Две отдельные ROOT-проводки и два события выдачи; reference_id
        # уникальны и продолжают последовательность item:1 -> item:2.
        self.assertEqual(self._wallet_balance(ids["player"]), 800)
        self.assertEqual(self._owned(ids["player"], ids["item_key_pub"]), 1)
        self.assertEqual(self._count_shop_transactions(ids["player"]), 2)
        self.assertEqual(
            self._count_shop_events(ids["player"], ids["item_key_pub"]), 2
        )
        self.assertEqual(
            self._shop_reference_ids(ids["player"]),
            [f"{ids['item_key_pub']}:1", f"{ids['item_key_pub']}:2"],
        )

    def test_purchase_insufficient_balance_409(self):
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._seed_root_wallet(ids["player"], 50)

        with self.assertRaises(MissionEngineError) as catcher:
            with self.SessionLocal.begin() as session:
                purchase_catalog_item(
                    session, ids["player"], ids["item_key_pub"]
                )
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(catcher.exception.detail, "Недостаточно ROOT.")

        # Частичных записей нет: транзакция откатилась целиком.
        self.assertEqual(self._wallet_balance(ids["player"]), 50)
        self.assertEqual(self._owned(ids["player"], ids["item_key_pub"]), 0)
        self.assertEqual(self._count_shop_transactions(ids["player"]), 0)

    def test_purchase_unknown_item_404(self):
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._seed_root_wallet(ids["player"], 1000)

        with self.assertRaises(MissionEngineError) as catcher:
            with self.SessionLocal.begin() as session:
                purchase_catalog_item(
                    session, ids["player"], f"item-missing-{uuid.uuid4().hex}"
                )
        self.assertEqual(catcher.exception.status_code, 404)
        self.assertEqual(catcher.exception.detail, "Товар не найден.")
        self.assertEqual(self._wallet_balance(ids["player"]), 1000)
        self.assertEqual(self._count_shop_transactions(ids["player"]), 0)

    def test_purchase_non_key_404(self):
        ids = self._fixture()
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._seed_root_wallet(ids["player"], 1000)

        with self.assertRaises(MissionEngineError) as catcher:
            with self.SessionLocal.begin() as session:
                purchase_catalog_item(
                    session, ids["player"], ids["item_non_key"]
                )
        self.assertEqual(catcher.exception.status_code, 404)
        self.assertEqual(catcher.exception.detail, "Товар не найден.")
        self.assertEqual(self._wallet_balance(ids["player"]), 1000)
        self.assertEqual(self._count_shop_transactions(ids["player"]), 0)