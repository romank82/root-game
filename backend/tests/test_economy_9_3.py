"""Этап 9.3 — финансовые тесты: интеграция аудита,
семантика fallback-повтора, team entry-debit (разведка 29-A).

Live SQLite + alembic upgrade head (паттерн test_admin_economy.py): на каждый
тест — свежая disposable БД со схемой и seed-данными из миграций. Ledger и
inventory_events immutable (триггеры запрещают UPDATE/DELETE), поэтому каждый
тест полностью изолирован.

Покрывает три сценария, НЕ покрытых существующими тестами (разведка 29-A):
  1. test_audit_after_real_purchases — интеграция audit_balances после
     РЕАЛЬНЫХ покупок: mission reward (submit_mission через движок) + покупка
     ключа (purchase_catalog_item через shop_service). Ledger обязан сойтись:
     ok=True, mismatches=[].
  2. test_fallback_repeat_after_success_returns_idempotent_success — текущая
     семантика повтора fallback-покупки после успешного первого списания при
     просевшем балансе. Идемпотентный guard (fallback_shop.py:427-446) стоит
     ДО проверки баланса — повтор возвращает прежний успех и НЕ падает в 409
     (в отличие от первого вызова на страже недостаточного баланса).
     Если бы повтор падал в 409 — это был бы баг 9.3.2 («повтор успешной
     покупки зависит от текущего баланса»); текущий код ведёт себя корректно,
     фиксируем поведение, ничего не чиним.
  3. test_team_entry_debit_idempotent — идемпотентность entry-debit командной
     миссии: первый ready списывает ROOT+ключ ровно один раз (reference_id =
     team_session.id), повторный ready блокируется state-машиной (409) и
     второй проводки не создаёт.

Сводка по уже покрытому (НЕ дублируем):
  - уход в минус / идемпотентность: test_fallback_shop (4_4_2, 4_4_3),
    test_shop_service (test_purchase_idempotent), test_mission_engine_integration
    (703, 1314, 1209, 2472), test_admin_player_wallet (281, 315, 527);
  - audit_balances happy/mismatch: test_admin_economy.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_access import DIRECT_EXECUTION_MODE
from app.admin_economy import ECONOMY_READ_PERMISSION, audit_balances
from app.mission_engine import (
    ENTRY_DEBIT_REFERENCE_TYPE,
    ENTRY_ITEM_EVENT_TYPE,
    ENTRY_ITEM_REFERENCE_TYPE,
    MissionEngineError,
)
from app.shop_service import SHOP_ENABLED_KEY, SHOP_PRICE_ROOT_KEY, purchase_catalog_item
from app.team_missions_service import create_team_session_entrypoint, mark_ready_entrypoint
from tests.test_geo_team_contract import valid_team_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class Economy93FinanceTests(unittest.TestCase):
    """9.3: интеграционные финансовые тесты на свежей alembic-схеме."""

    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модули; SessionLocal патчится на свежую БД в setUp."""
        from app import admin_economy, db, fallback_shop, mission_engine

        cls.db_module = db
        cls.admin_economy = admin_economy
        cls.mission_engine = mission_engine
        cls.fallback_shop = fallback_shop
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест.

        Патчатся ЧЕТЫРЕ канала SessionLocal:
          - app.db.SessionLocal — team_missions_service и прочие ленивые
            импорты (транзакции открываются через from app.db import
            SessionLocal на момент вызова);
          - mission_engine.SessionLocal / fallback_shop.SessionLocal /
            admin_economy.SessionLocal — module-level импорт на старте модуля,
            поэтому атрибут модуля зафиксирован и требует отдельной подмены.
        """
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-economy-9-3-tests-"
        )
        self.database_path = Path(self._temporary_directory.name) / "economy.sqlite3"
        database_url = f"sqlite:///{self.database_path}"

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

        self.engine = create_engine(
            database_url,
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

        self._session_local_patches = [
            patch("app.db.SessionLocal", self.SessionLocal),
            patch.object(self.mission_engine, "SessionLocal", self.SessionLocal),
            patch.object(self.fallback_shop, "SessionLocal", self.SessionLocal),
            patch.object(self.admin_economy, "SessionLocal", self.SessionLocal),
        ]
        for session_local_patch in self._session_local_patches:
            session_local_patch.start()

    def tearDown(self) -> None:
        for session_local_patch in self._session_local_patches:
            session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Хелперы: admin -------------------------------------------------

    def _request(self) -> SimpleNamespace:
        return SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.9"),
            headers={},
            state=SimpleNamespace(),
        )

    def _make_admin(self, is_super_admin: bool = True):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin" if is_super_admin else "admin",
                    is_super_admin=is_super_admin,
                    is_active=True,
                    is_deleted=False,
                )
            )
        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _grant(self, admin_id: str, permission_code: str) -> None:
        from app.models import AdminUserPermission

        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode=DIRECT_EXECUTION_MODE,
                    is_active=True,
                )
            )

    # ---- Хелперы: игрок / кошелёк / ledger ------------------------------

    def _make_player(self) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="Economy 9.3 player",
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _make_wallet(self, player_id: str) -> str:
        """Кошелёк ROOT с available_balance=0 и без проводок."""
        from app.models import Wallet

        wallet_id = f"wallet-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Wallet(
                    id=wallet_id,
                    player_id=player_id,
                    currency="ROOT",
                    available_balance=0,
                    locked_balance=0,
                )
            )
        return wallet_id

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

    def _make_transaction(
        self,
        wallet_id: str,
        amount: int,
        transaction_type: str,
        balance_after: int,
        reference_type: str = "test_economy_93",
    ) -> None:
        """Проводка c уникальным reference (unique index по референсу)."""
        from app.models import WalletTransaction

        with self.SessionLocal.begin() as session:
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet_id,
                    amount=amount,
                    balance_after=balance_after,
                    transaction_type=transaction_type,
                    reason=f"Test {transaction_type}",
                    reference_type=reference_type,
                    reference_id=f"tx-{uuid.uuid4().hex}",
                    metadata_json={},
                )
            )

    def _set_available_balance(self, wallet_id: str, amount: int) -> None:
        from app.models import Wallet

        with self.SessionLocal.begin() as session:
            session.get(Wallet, wallet_id).available_balance = amount

    def _root_balance(self, player_id: str) -> int:
        from app.models import Wallet

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            return wallet.available_balance if wallet is not None else 0

    def _root_wallet_id(self, player_id: str) -> str | None:
        from app.models import Wallet

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            return wallet.id if wallet is not None else None

    # ---- Хелперы: настройки (CMS-first) ----------------------------------

    def _set_setting(self, key: str, value) -> None:
        """Upsert системной настройки (миграции сеют дефолтные строки)."""
        from app.models import SystemSetting

        with self.SessionLocal.begin() as session:
            existing = session.get(SystemSetting, key)
            if existing is None:
                session.add(
                    SystemSetting(
                        key=key,
                        value_json=value,
                        value_type="boolean" if isinstance(value, bool) else "integer",
                        category="shop",
                        title=key,
                        description="Seeded by test",
                        is_sensitive=False,
                        status="active",
                    )
                )
            else:
                existing.value_json = value
                existing.status = "active"

    def _enable_fallback_shop(self) -> None:
        """Включить fallback-магазин (миграция сеет enabled=False)."""
        rows = [
            ("shop.fallback.enabled", True, "boolean"),
            ("shop.fallback.default_offer_id", "offer-fallback-1", "string"),
            ("shop.fallback.default_quota_limit", 1, "integer"),
            ("shop.fallback.default_price_root", 100, "integer"),
            ("shop.fallback.default_available_seconds", 0, "integer"),
        ]
        from app.models import SystemSetting

        with self.SessionLocal.begin() as session:
            for key, value, value_type in rows:
                existing = session.get(SystemSetting, key)
                if existing is None:
                    session.add(
                        SystemSetting(
                            key=key,
                            value_json=value,
                            value_type=value_type,
                            category="shop",
                            title=key,
                            description="Seeded by test",
                            is_sensitive=False,
                            status="active",
                        )
                    )
                else:
                    existing.value_json = value
                    existing.status = "active"

    # ---- Хелперы: CMS-миссия и магазин ----------------------------------

    def _make_published_key(self, prefix: str = "item-key") -> str:
        """Published KEY-item в каталоге."""
        from app.models import Item

        item_id = f"{prefix}-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Item(
                    id=item_id,
                    slug=f"slug-{item_id}",
                    code=f"CODE-{uuid.uuid4().hex[:12]}",
                    title="Economy 9.3 key",
                    description="Purchasable catalog key",
                    symbol="KEY",
                    category="KEY",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            )
        return item_id

    def _attach_key_reward(self, item_id: str) -> None:
        """KeyRules для fallback-ключа (Item+награда уже в фикстуре миссии).

        Важно не дублировать MissionReward: _make_solo_mission(reward_item_id=...)
        уже создаёт item-награду; здесь только правила расхода ключа, без
        которых create_first_failure_entitlements не создаёт entitlement
        (test_fallback_shop 4_3a_6) и не было бы дублей под unique-индексом
        (player_id, mission_id, item_id).
        """
        from app.models import KeyRules

        with self.SessionLocal.begin() as session:
            session.add(
                KeyRules(
                    id=f"key-rules-{uuid.uuid4().hex}",
                    item_id=item_id,
                    is_consumable=True,
                )
            )

    def _make_solo_mission(
        self,
        *,
        reward_currency: int = 0,
        reward_item_id: str | None = None,
    ) -> str:
        """Опубликованная solo-миссия (text_answer) с опциональными наградами.

        Минимальная CMS-фикстура в стиле test_mission_engine_integration:
        Season -> Chapter -> Mission(published) + Segment/SegmentMission для
        bootstrap. Без MissionRequirement — миссия сразу available.
        """
        from app.models import (
            Chapter,
            Mission,
            MissionReward,
            Season,
            Segment,
            SegmentMission,
        )

        suffix = uuid.uuid4().hex
        with self.SessionLocal.begin() as session:
            season = Season(
                id=f"season-{suffix}",
                slug=f"season-{suffix}",
                title="Economy 9.3 season",
                description="Isolated economy fixture",
                status="published",
                sort_order=1,
            )
            session.add(season)
            session.flush()

            chapter = Chapter(
                id=f"chapter-{suffix}",
                season_id=season.id,
                slug=f"chapter-{suffix}",
                title="Economy 9.3 chapter",
                description="Isolated economy fixture",
                status="published",
                sort_order=1,
            )
            session.add(chapter)
            session.flush()

            mission = Mission(
                id=f"mission-{suffix}",
                chapter_id=chapter.id,
                slug=f"mission-{suffix}",
                mission_type="text_answer",
                title="Economy 9.3 mission",
                description="Grants economy rewards",
                content={"schemaVersion": 1, "ui": {"label": "Reward"}},
                validation_config={
                    "validator": "normalized_text_match",
                    "acceptedAnswers": ["complete"],
                },
                status="published",
                sort_order=1,
            )
            session.add(mission)
            session.flush()

            segment = Segment(
                id=f"segment-{suffix}",
                chapter_id=chapter.id,
                slug=f"segment-{suffix}",
                title="Economy 9.3 segment",
                description="Segment for bootstrap",
                status="published",
                sort_order=1,
                content={"schemaVersion": 1},
            )
            session.add(segment)
            session.flush()

            session.add(
                SegmentMission(
                    id=f"link-{suffix}",
                    segment_id=segment.id,
                    mission_id=mission.id,
                    status="active",
                    sort_order=1,
                )
            )

            if reward_currency > 0:
                session.add(
                    MissionReward(
                        id=f"reward-root-{suffix}",
                        mission_id=mission.id,
                        reward_type="currency",
                        amount=reward_currency,
                        reward_value={"currency": "ROOT"},
                        sort_order=1,
                    )
                )
            if reward_item_id is not None:
                session.add(
                    MissionReward(
                        id=f"reward-item-{suffix}",
                        mission_id=mission.id,
                        reward_type="item",
                        item_id=reward_item_id,
                        amount=1,
                        reward_value={},
                        sort_order=2,
                    )
                )

        return mission.id

    def _get_fallback_entitlement(self, player_id: str, mission_id: str):
        from app.geo_team_runtime_models import PlayerFallbackEntitlement

        with self.SessionLocal() as session:
            return session.scalar(
                select(PlayerFallbackEntitlement).where(
                    PlayerFallbackEntitlement.player_id == player_id,
                    PlayerFallbackEntitlement.mission_id == mission_id,
                )
            )

    def _count_wallet_transactions(
        self, wallet_id: str, reference_type: str
    ) -> int:
        from app.models import WalletTransaction

        with self.SessionLocal() as session:
            rows = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet_id,
                    WalletTransaction.reference_type == reference_type,
                )
            ).all()
            return len(rows)

    # ---- Хелперы: команды -----------------------------------------------

    def _make_team(self, leader_id: str, member_ids: list[str] | None = None) -> None:
        """Активная команда: лидер + активные участники (status='active')."""
        from app.models import Team, TeamMember

        team_id = f"team-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Team(
                    id=team_id,
                    name=f"Team-{team_id[-6:]}",
                    leader_id=leader_id,
                    status="active",
                    join_policy="open",
                )
            )
            session.add(
                TeamMember(
                    id=f"tm-{uuid.uuid4().hex}",
                    team_id=team_id,
                    player_id=leader_id,
                    role="leader",
                    status="active",
                )
            )
            for member_id in member_ids or []:
                session.add(
                    TeamMember(
                        id=f"tm-{uuid.uuid4().hex}",
                        team_id=team_id,
                        player_id=member_id,
                        role="member",
                        status="active",
                    )
                )

    def _make_team_mission(self, validation_config: dict | None = None) -> str:
        """Командная миссия с валидным team/geo validation_config."""
        from app.models import Chapter, Mission, Season

        suffix = uuid.uuid4().hex
        with self.SessionLocal.begin() as session:
            season = Season(
                id=f"season-{suffix}",
                slug=f"season-{suffix}",
                title="Season",
            )
            session.add(season)
            session.flush()
            chapter = Chapter(
                id=f"chapter-{suffix}",
                season_id=season.id,
                slug=f"chapter-{suffix}",
                title="Chapter",
            )
            session.add(chapter)
            session.flush()
            mission = Mission(
                id=f"mission-{suffix}",
                chapter_id=chapter.id,
                slug=f"mission-{suffix}",
                mission_type="team",
                mission_category="team",
                title="Team mission",
                status="published",
                content={},
                validation_config=(
                    valid_team_config() if validation_config is None else validation_config
                ),
            )
            session.add(mission)
        return mission.id

    def _seed_item(self, item_id: str) -> None:
        """Published Item — без него ядро движка заблокирует списание (шаг 3)."""
        from app.models import Item

        with self.SessionLocal.begin() as session:
            session.add(
                Item(
                    id=item_id,
                    slug=f"slug-{item_id}-{uuid.uuid4().hex[:8]}",
                    code=f"CODE-{uuid.uuid4().hex[:12]}",
                    title="Team key",
                    description="Team mission entry key",
                    symbol="◇",
                    category="key",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            )

    def _seed_key(self, player_id: str, item_id: str, quantity: int) -> None:
        from app.models import PlayerItem

        with self.SessionLocal.begin() as session:
            session.add(
                PlayerItem(
                    id=f"player-item-{uuid.uuid4().hex}",
                    player_id=player_id,
                    item_id=item_id,
                    quantity=quantity,
                )
            )

    # ---- Тесты ----------------------------------------------------------

    def test_audit_after_real_purchases(self) -> None:
        """9.3.1: audit_balances сходится после реальных mission reward + shop."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)

        player_id = self._make_player()
        wallet_id = self._make_wallet(player_id)  # balance 0, без проводок

        # 1. Mission reward 100 через реальный движок (submit_mission).
        mission_id = self._make_solo_mission(reward_currency=100)
        result = self.mission_engine.submit_mission(
            player_id, mission_id, answer="complete"
        )
        self.assertIs(result["accepted"], True)
        self.assertEqual(result["awarded"]["root"], 100)
        self.assertEqual(self._root_balance(player_id), 100)

        # 2. Покупка ключа в магазине за 40 через реальный shop_service.
        self._set_setting(SHOP_ENABLED_KEY, True)
        self._set_setting(SHOP_PRICE_ROOT_KEY, 40)
        shop_item_id = self._make_published_key()
        with self.SessionLocal.begin() as session:
            purchase = purchase_catalog_item(session, player_id, shop_item_id)
        self.assertIs(purchase["purchased"], True)
        self.assertEqual(purchase["priceRoot"], 40)
        self.assertEqual(purchase["rootBalance"], 60)
        self.assertEqual(self._root_balance(player_id), 60)

        # 3. Ledger сошёлся: credit 100 (mission_reward) - debit 40 (shop).
        audit = audit_balances(request=self._request(), admin=admin)
        self.assertIs(audit["ok"], True)
        self.assertEqual(audit["mismatches"], [])
        self.assertGreaterEqual(audit["total"], 1)
        self.assertEqual(wallet_id, self._root_wallet_id(player_id))

    def test_fallback_repeat_after_success_returns_idempotent_success(self) -> None:
        """9.3.2: повтор fallback-покупки после успеха — идемпотентный успех.

        Разведка 29-A: в fallback_shop committed-guard (427-446) стоит ДО
        проверки баланса (466): повтор уже успешной покупки (consumed_count>0)
        возвращает прежний результат и НЕ зависит от текущего баланса.
        Сценарий «первый вызов при недостатке -> 409» зафиксирован в
        test_fallback_shop 4_4_3 и здесь воспроизводится только как вводная.
        Если бы повтор падал в 409 при просевшем балансе — это был бы баг
        9.3.2 (расхождение с shop_service, где guard стоит до баланса);
        текущий код возвращает успех, фиксируем поведение, не чиним.
        """
        player_id = self._make_player()
        wallet_id = self._seed_root_wallet(player_id, 50)

        # Fallback-миссия: item-награда с KeyRules -> entitlement после провала.
        fallback_item_id = self._make_published_key(prefix="item-fallback")
        mission_id = self._make_solo_mission(reward_item_id=fallback_item_id)
        self._attach_key_reward(fallback_item_id)
        self._enable_fallback_shop()

        self.mission_engine.submit_mission(
            player_id, mission_id, answer="wrong-answer"
        )
        entitlement = self._get_fallback_entitlement(player_id, mission_id)
        self.assertIsNotNone(entitlement)

        # Первый вызов при балансе 50 < 100 -> 409, без проводок.
        with self.assertRaises(MissionEngineError) as first_catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                player_id, entitlement.id
            )
        self.assertEqual(first_catcher.exception.status_code, 409)
        self.assertEqual(first_catcher.exception.detail, "Недостаточно ROOT.")
        self.assertEqual(
            self._count_wallet_transactions(wallet_id, "fallback_purchase"), 0
        )
        self.assertEqual(self._root_balance(player_id), 50)

        # «Ручная» успешная покупка при балансе 200 (credit +150 -> 200,
        # затем debit 100 движком) -> баланс 100.
        self._make_transaction(wallet_id, 150, "credit", balance_after=200)
        self._set_available_balance(wallet_id, 200)
        success = self.fallback_shop.purchase_fallback_offer_entrypoint(
            player_id, entitlement.id
        )
        self.assertIs(success["purchased"], True)
        self.assertEqual(success["consumedCount"], 1)
        self.assertEqual(success["status"], "exhausted")
        self.assertEqual(success["priceRoot"], 100)
        self.assertEqual(success["rootBalance"], 100)
        self.assertEqual(
            self._count_wallet_transactions(wallet_id, "fallback_purchase"), 1
        )

        # Баланс снова просел ниже цены (ledger-проводкой, чтобы не ломать
        # сверку), но повтор уже успешной покупки должен вернуться по
        # committed-guard, а не упасть в 409.
        self._make_transaction(wallet_id, 50, "debit", balance_after=50)
        self._set_available_balance(wallet_id, 50)
        self.assertEqual(self._root_balance(player_id), 50)

        repeat = self.fallback_shop.purchase_fallback_offer_entrypoint(
            player_id, entitlement.id
        )
        # ТЕКУЩЕЕ ПОВЕДЕНИЕ: успех, баланс не трогается, проводка одна.
        self.assertIs(repeat["purchased"], True)
        self.assertEqual(repeat["consumedCount"], 1)
        self.assertEqual(repeat["rootBalance"], 50)
        self.assertEqual(
            self._count_wallet_transactions(wallet_id, "fallback_purchase"), 1
        )
        self.assertEqual(self._root_balance(player_id), 50)
        refreshed = self._get_fallback_entitlement(player_id, mission_id)
        self.assertEqual(refreshed.consumed_count, 1)

    def test_team_entry_debit_idempotent(self) -> None:
        """9.3.3: entry-debit командной миссии списывается ровно один раз.

        Первый ready (accept) атомарно списывает entryFeeRootAtomic + расходуемый
        ключ и подтверждает готовность (reference_id = team_session.id).
        Повторный ready блокируется state-машиной (409 «Вы уже отметились
        готовым»), вторая проводка не создаётся — идемпотентность без гонок.
        """
        leader = self._make_player()
        member = self._make_player()
        self._make_team(leader, [member])

        config = valid_team_config()  # entryFeeRootAtomic = 25
        required_item_id = f"item-{uuid.uuid4().hex}"
        config["economy"]["requiredItems"] = [
            {"itemId": required_item_id, "quantity": 1}
        ]
        mission_id = self._make_team_mission(validation_config=config)
        session_id = create_team_session_entrypoint(leader, mission_id)["id"]

        self._seed_item(required_item_id)
        wallet_id = self._seed_root_wallet(leader, 100)
        self._seed_key(leader, required_item_id, 2)

        # Первый ready: списание entry (root 25 + 1 ключ), статус ready.
        first = mark_ready_entrypoint(leader, session_id)
        self.assertEqual(first["myStatus"], "ready")
        self.assertEqual(self._root_balance(leader), 75)
        self.assertEqual(
            self._count_wallet_transactions(wallet_id, ENTRY_DEBIT_REFERENCE_TYPE),
            1,
        )

        # Повторный ready: state-машина блокирует, вторая проводка не создаётся.
        with self.assertRaises(MissionEngineError) as catcher:
            mark_ready_entrypoint(leader, session_id)
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(catcher.exception.detail, "Вы уже отметились готовым.")

        self.assertEqual(self._root_balance(leader), 75)
        self.assertEqual(
            self._count_wallet_transactions(wallet_id, ENTRY_DEBIT_REFERENCE_TYPE),
            1,
        )
        with self.SessionLocal() as session:
            from app.geo_team_runtime_models import InventoryEvent
            from app.models import PlayerItem

            events = session.scalars(
                select(InventoryEvent)
                .join(PlayerItem, InventoryEvent.player_item_id == PlayerItem.id)
                .where(
                    PlayerItem.player_id == leader,
                    PlayerItem.item_id == required_item_id,
                    InventoryEvent.event_type == ENTRY_ITEM_EVENT_TYPE,
                    InventoryEvent.reference_type == ENTRY_ITEM_REFERENCE_TYPE,
                )
            ).all()
        self.assertEqual(len(events), 1)


if __name__ == "__main__":
    unittest.main()