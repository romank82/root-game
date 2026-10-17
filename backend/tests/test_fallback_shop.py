from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.system_settings_catalog import SystemSettingDefinition, validate_value


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class FallbackShopEntitlementTests(unittest.TestCase):
    """4.3a: личный fallback-entitlement после первого провала (V1 semantics)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-fallback-shop-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "fallback-shop.sqlite3"
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

        from app import mission_engine

        cls.mission_engine = mission_engine
        cls._session_local_patch = patch.object(
            mission_engine,
            "SessionLocal",
            cls.SessionLocal,
        )
        cls._session_local_patch.start()

        # 4.3b: get_fallback_offers тоже открывает собственную сессию.
        from app import fallback_shop

        cls.fallback_shop = fallback_shop
        cls._fallback_session_local_patch = patch.object(
            fallback_shop,
            "SessionLocal",
            cls.SessionLocal,
        )
        cls._fallback_session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._fallback_session_local_patch.stop()
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------
    def _fixture(
        self,
        *,
        include_item_reward: bool = True,
        include_key_rules: bool = True,
        second_mission: bool = False,
        second_player: bool = False,
        second_key_reward: bool = False,
    ) -> dict[str, str]:
        from app.models import (
            Chapter,
            GamePlayer,
            Item,
            KeyRules,
            Mission,
            MissionReward,
            Season,
            Segment,
            SegmentMission,
            StoryNode,
        )

        suffix = uuid.uuid4().hex
        ids = {
            "player": f"player-{suffix}",
            "player_second": f"player-second-{suffix}",
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "segment": f"segment-{suffix}",
            "story": f"story-{suffix}",
            "item": f"item-{suffix}",
            "item_second": f"item-second-{suffix}",
            "item_extra": f"item-extra-{suffix}",
            "target": f"target-{suffix}",
            "target_second": f"target-second-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="Fallback test season",
                    description="Isolated fallback-shop fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()

            session.add_all(
                [
                    Chapter(
                        id=ids["chapter"],
                        season_id=ids["season"],
                        slug=f"chapter-{suffix}",
                        title="Fallback test chapter",
                        description="Isolated fallback-shop fixture",
                        status="published",
                        sort_order=1,
                    ),
                    GamePlayer(
                        id=ids["player"],
                        display_name="Fallback player",
                        auth_provider="test",
                        external_id=f"test-{suffix}",
                        status="active",
                    ),
                ]
            )
            if second_player:
                session.add(
                    GamePlayer(
                        id=ids["player_second"],
                        display_name="Second fallback player",
                        auth_provider="test",
                        external_id=f"test-second-{suffix}",
                        status="active",
                    )
                )
            session.flush()

            items = [
                Item(
                    id=ids["item"],
                    slug=f"item-{suffix}",
                    code=f"ITEM-{suffix[:12]}",
                    title="Fixture key",
                    description="Fallback purchasable key",
                    symbol="KEY",
                    category="key",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            ]
            if second_mission:
                items.append(
                    Item(
                        id=ids["item_second"],
                        slug=f"item-second-{suffix}",
                        code=f"ITEM2-{suffix[:12]}",
                        title="Second fixture key",
                        description="Second fallback purchasable key",
                        symbol="KEY",
                        category="key",
                        rarity="common",
                        is_unique=False,
                        content={"schemaVersion": 1},
                        status="published",
                    )
                )
            if second_key_reward:
                # Второй ключ-награда ТОЙ ЖЕ миссии (Sprint 8.16).
                items.append(
                    Item(
                        id=ids["item_extra"],
                        slug=f"item-extra-{suffix}",
                        code=f"ITEMX-{suffix[:12]}",
                        title="Extra fixture key",
                        description="Second key reward of the same mission",
                        symbol="KEY",
                        category="key",
                        rarity="common",
                        is_unique=False,
                        content={"schemaVersion": 1},
                        status="published",
                    )
                )

            session.add_all(
                [
                    StoryNode(
                        id=ids["story"],
                        chapter_id=ids["chapter"],
                        slug=f"story-{suffix}",
                        title="Fallback story",
                        body="Server-confirmed story content",
                        presentation_type="document",
                        content={"schemaVersion": 1},
                        status="published",
                        sort_order=1,
                    ),
                    Segment(
                        id=ids["segment"],
                        chapter_id=ids["chapter"],
                        slug=f"segment-{suffix}",
                        title="Published segment",
                        description="Visible segment",
                        status="published",
                        sort_order=10,
                        content={"schemaVersion": 1},
                    ),
                ]
            )
            session.add_all(items)
            session.flush()
            if include_key_rules:
                session.add(
                    KeyRules(
                        id=f"key-rules-{suffix}",
                        item_id=ids["item"],
                        is_consumable=True,
                        stack_limit=1,
                    )
                )
                if second_mission:
                    session.add(
                        KeyRules(
                            id=f"key-rules-second-{suffix}",
                            item_id=ids["item_second"],
                            is_consumable=True,
                            stack_limit=1,
                        )
                    )
                if second_key_reward:
                    session.add(
                        KeyRules(
                            id=f"key-rules-extra-{suffix}",
                            item_id=ids["item_extra"],
                            is_consumable=True,
                            stack_limit=1,
                        )
                    )
            session.flush()

            mission_rows = [
                Mission(
                    id=ids["target"],
                    chapter_id=ids["chapter"],
                    story_node_id=ids["story"],
                    slug=f"target-{suffix}",
                    mission_type="text_answer",
                    title="Fallback target mission",
                    description="First failed attempt should create entitlement",
                    content={"schemaVersion": 1, "ui": {"label": "Target"}},
                    validation_config={
                        "validator": "normalized_text_match",
                        "acceptedAnswers": ["complete"],
                    },
                    status="published",
                    sort_order=10,
                )
            ]
            if second_mission:
                mission_rows.append(
                    Mission(
                        id=ids["target_second"],
                        chapter_id=ids["chapter"],
                        slug=f"target-second-{suffix}",
                        mission_type="text_answer",
                        title="Second fallback mission",
                        description="Another mission for multi-mission checks",
                        content={"schemaVersion": 1, "ui": {"label": "Target 2"}},
                        validation_config={
                            "validator": "normalized_text_match",
                            "acceptedAnswers": ["complete2"],
                        },
                        status="published",
                        sort_order=20,
                    )
                )
            session.add_all(mission_rows)
            session.flush()
            reward_rows: list[MissionReward] = []
            if include_item_reward:
                reward_rows.append(
                    MissionReward(
                        id=f"item-reward-{suffix}",
                        mission_id=ids["target"],
                        reward_type="item",
                        item_id=ids["item"],
                        amount=1,
                        reward_value={},
                        sort_order=1,
                    )
                )
                if second_mission:
                    reward_rows.append(
                        MissionReward(
                            id=f"item-reward-second-{suffix}",
                            mission_id=ids["target_second"],
                            reward_type="item",
                            item_id=ids["item_second"],
                            amount=1,
                            reward_value={},
                            sort_order=1,
                        )
                    )
                if second_key_reward:
                    reward_rows.append(
                        MissionReward(
                            id=f"item-reward-extra-{suffix}",
                            mission_id=ids["target"],
                            reward_type="item",
                            item_id=ids["item_extra"],
                            amount=1,
                            reward_value={},
                            sort_order=2,
                        )
                    )
            session.add_all(reward_rows)
            session.flush()

            session.add_all(
                [
                    SegmentMission(
                        id=f"link-target-{suffix}",
                        segment_id=ids["segment"],
                        mission_id=ids["target"],
                        status="active",
                        sort_order=10,
                    )
                ]
            )
            if second_mission:
                session.add(
                    SegmentMission(
                        id=f"link-target-second-{suffix}",
                        segment_id=ids["segment"],
                        mission_id=ids["target_second"],
                        status="active",
                        sort_order=20,
                    )
                )

            # Миграция уже сидит 4 строки дефолтов shop.fallback.* — upsert,
            # а не повторный INSERT (PK key конфликтовал бы).
            self._upsert_fallback_settings(session)
            session.flush()

        return ids

    @staticmethod
    def _upsert_fallback_settings(session) -> None:
        from app.models import SystemSetting

        rows = [
            SystemSetting(
                key="shop.fallback.enabled",
                value_json=True,
                value_type="boolean",
                category="shop",
                title="Fallback-магазин после первого провала",
                description="Включает персональный магазин после первого провала миссии.",
                is_sensitive=False,
                status="active",
            ),
            SystemSetting(
                key="shop.fallback.default_offer_id",
                value_json="offer-fallback-1",
                value_type="string",
                category="shop",
                title="Идентификатор fallback-предложения по умолчанию",
                description="Ссылка на CMS product, продаваемый после провала.",
                is_sensitive=False,
                status="active",
            ),
            SystemSetting(
                key="shop.fallback.default_quota_limit",
                value_json=1,
                value_type="integer",
                category="shop",
                title="Лимит покупок fallback-ключа по умолчанию",
                description="Сколько раз игрок может купить ключ по этому предложению.",
                is_sensitive=False,
                status="active",
            ),
        ]
        for row in rows:
            existing = session.get(SystemSetting, row.key)
            if existing is None:
                session.add(row)
            else:
                existing.value_json = row.value_json
                existing.value_type = row.value_type
                existing.status = "active"
    def _seed_policy(
        self,
        mission_id: str,
        *,
        entry_root_atomic: int = 0,
        required_items: list[tuple[str, int]] | None = None,
    ) -> None:
        from app.geo_team_runtime_models import MissionRuntimePolicy

        with self.SessionLocal.begin() as session:
            session.add(
                MissionRuntimePolicy(
                    id=f"policy-{uuid.uuid4().hex}",
                    mission_id=mission_id,
                    version=1,
                    status="published",
                    entry_root_atomic=entry_root_atomic,
                    max_attempts=3,
                    repeatability_policy="one_time",
                    required_items_json={
                        "schemaVersion": 1,
                        "items": [
                            {"itemId": item_id, "quantity": quantity}
                            for item_id, quantity in (required_items or [])
                        ],
                    },
                    challenge_policy_json={},
                    reward_policy_json={},
                    fallback_policy_json=None,
                    feature_flags_json={},
                )
            )

    def _count_entitlements(self, player_id: str) -> int:
        from app.geo_team_runtime_models import PlayerFallbackEntitlement

        with self.SessionLocal() as session:
            rows = session.scalars(
                select(PlayerFallbackEntitlement).where(
                    PlayerFallbackEntitlement.player_id == player_id,
                )
            ).all()
            return len(rows)

    def _get_entitlement(self, player_id: str, mission_id: str):
        from app.geo_team_runtime_models import PlayerFallbackEntitlement

        with self.SessionLocal() as session:
            return session.scalar(
                select(PlayerFallbackEntitlement).where(
                    PlayerFallbackEntitlement.player_id == player_id,
                    PlayerFallbackEntitlement.mission_id == mission_id,
                )
            )

    def _list_entitlements(self, player_id: str, mission_id: str):
        """Все entitlement'ы игрока на миссию (Sprint 8.16: их может быть >1)."""
        from app.geo_team_runtime_models import PlayerFallbackEntitlement

        with self.SessionLocal() as session:
            return session.scalars(
                select(PlayerFallbackEntitlement)
                .where(
                    PlayerFallbackEntitlement.player_id == player_id,
                    PlayerFallbackEntitlement.mission_id == mission_id,
                )
                .order_by(PlayerFallbackEntitlement.item_id)
            ).all()

    def _seed_root_wallet(self, player_id: str, amount: int) -> str:
        """Кошелёк с кредитной проводкой — игровой ROOT на старте (как в 4.1)."""
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

    # ---- 4.3a.1–4.3a.9 -----------------------------------------------
    def test_4_3a_1_first_failed_attempt_creates_entitlement(self):
        ids = self._fixture()
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        entitlement = self._get_entitlement(ids["player"], ids["target"])
        self.assertIsNotNone(entitlement)
        self.assertEqual(entitlement.status, "available")
        self.assertEqual(entitlement.offer_id, ids["item"])
        self.assertEqual(entitlement.item_id, ids["item"])
        self.assertEqual(entitlement.quota_limit, 1)
        self.assertEqual(entitlement.consumed_count, 0)

    def test_4_3a_2_repeated_failures_keep_single_entitlement(self):
        ids = self._fixture()
        first = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-1"
        )
        self.assertFalse(first["accepted"])
        second = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-2"
        )
        self.assertFalse(second["accepted"])
        self.assertEqual(self._count_entitlements(ids["player"]), 1)

    def test_4_3a_3_success_does_not_create_entitlement(self):
        ids = self._fixture()
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="complete"
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(self._count_entitlements(ids["player"]), 0)

    def test_4_3a_4_disabled_flag_no_entitlement(self):
        ids = self._fixture()
        with self.SessionLocal.begin() as session:
            from app.models import SystemSetting

            setting = session.get(SystemSetting, "shop.fallback.enabled")
            self.assertIsNotNone(setting)
            setting.value_json = False
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(self._count_entitlements(ids["player"]), 0)

    def test_4_3a_5_mission_without_item_reward_no_entitlement(self):
        ids = self._fixture(include_item_reward=False)
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(self._count_entitlements(ids["player"]), 0)
    def test_4_3a_6_item_without_key_rules_no_entitlement(self):
        ids = self._fixture(include_key_rules=False)
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(self._count_entitlements(ids["player"]), 0)

    def test_4_3a_7_entitlement_isolated_per_mission(self):
        ids = self._fixture(second_mission=True)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.mission_engine.submit_mission(
            ids["player"], ids["target_second"], answer="wrong-second"
        )
        self.assertEqual(self._count_entitlements(ids["player"]), 2)
        first = self._get_entitlement(ids["player"], ids["target"])
        second = self._get_entitlement(ids["player"], ids["target_second"])
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.id, second.id)

    def test_4_3a_8_entitlement_isolated_per_player(self):
        ids = self._fixture(second_player=True)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.mission_engine.submit_mission(
            ids["player_second"], ids["target"], answer="wrong-answer"
        )
        self.assertEqual(self._count_entitlements(ids["player"]), 1)
        self.assertEqual(self._count_entitlements(ids["player_second"]), 1)
        first = self._get_entitlement(ids["player"], ids["target"])
        second = self._get_entitlement(ids["player_second"], ids["target"])
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.player_id, second.player_id)

    def test_4_3a_9_insufficient_entry_resources_no_entitlement(self):
        ids = self._fixture()
        self._seed_policy(ids["target"], entry_root_atomic=5)
        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.mission_engine.submit_mission(
                ids["player"], ids["target"], answer="wrong-answer"
            )
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(self._count_entitlements(ids["player"]), 0)

    # ---- Sprint 8.16: несколько ключей-наград одной миссии -----------------
    def test_8_16_first_failure_adds_all_key_rewards(self):
        ids = self._fixture(second_key_reward=True)
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        entitlements = self._list_entitlements(ids["player"], ids["target"])
        self.assertEqual(
            {entitlement.item_id for entitlement in entitlements},
            {ids["item"], ids["item_extra"]},
        )
        for entitlement in entitlements:
            self.assertEqual(entitlement.status, "available")
            self.assertEqual(entitlement.quota_limit, 1)
            self.assertEqual(entitlement.consumed_count, 0)
            self.assertEqual(entitlement.offer_id, entitlement.item_id)

    def test_8_16_repeated_failures_add_nothing(self):
        ids = self._fixture(second_key_reward=True)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-1"
        )
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-2"
        )
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-3"
        )
        entitlements = self._list_entitlements(ids["player"], ids["target"])
        self.assertEqual(len(entitlements), 2)

    def test_8_16_purchase_individual_key(self):
        ids = self._fixture(second_key_reward=True)
        self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(len(offers), 2)
        by_item = {offer["item"]["id"]: offer for offer in offers}
        self.assertEqual(set(by_item), {ids["item"], ids["item_extra"]})

        # Покупка красного: его квота исчерпана, синий остаётся доступен.
        first = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], by_item[ids["item"]]["entitlementId"]
        )
        self.assertTrue(first["purchased"])
        self.assertEqual(first["consumedCount"], 1)
        self.assertEqual(first["status"], "exhausted")
        self.assertEqual(first["item"]["id"], ids["item"])

        remaining = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        by_item = {offer["item"]["id"]: offer for offer in remaining}
        self.assertEqual(by_item[ids["item"]]["consumedCount"], 1)
        self.assertEqual(by_item[ids["item"]]["status"], "exhausted")
        self.assertEqual(by_item[ids["item_extra"]]["consumedCount"], 0)
        self.assertEqual(by_item[ids["item_extra"]]["status"], "available")

        # Синий покупается независимо.
        second = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], by_item[ids["item_extra"]]["entitlementId"]
        )
        self.assertTrue(second["purchased"])
        self.assertEqual(second["consumedCount"], 1)
        self.assertEqual(second["status"], "exhausted")
        self.assertEqual(second["item"]["id"], ids["item_extra"])

        with self.SessionLocal() as session:
            from app.models import PlayerItem

            red = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            blue = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item_extra"],
                )
            )
            self.assertIsNotNone(red)
            self.assertEqual(red.quantity, 1)
            self.assertIsNotNone(blue)
            self.assertEqual(blue.quantity, 1)

    def test_8_16_existing_single_key_compatible(self):
        # Legacy-миссия с одним ключом работает как раньше: 1 entitlement
        # на (player, mission), item_id = ключ-награда, покупка выдаёт ключ.
        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlements = self._list_entitlements(ids["player"], ids["target"])
        self.assertEqual(len(entitlements), 1)
        entitlement = entitlements[0]
        self.assertEqual(entitlement.item_id, ids["item"])
        self.assertEqual(entitlement.offer_id, ids["item"])
        self.assertEqual(entitlement.quota_limit, 1)

        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["item"]["id"], ids["item"])

        result = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], entitlement.id
        )
        self.assertTrue(result["purchased"])
        self.assertEqual(result["item"]["id"], ids["item"])

    # ---- 4.3b.1–4.3b.7 (GET /api/v1/engine/fallback-offers) ------------
    def test_4_3b_1_no_entitlement_returns_empty(self):
        ids = self._fixture()
        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(offers, [])

    def test_4_3b_2_first_failure_returns_one_offer(self):
        ids = self._fixture()
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer["missionId"], ids["target"])
        self.assertEqual(offer["missionSlug"], ids["target"])
        self.assertEqual(offer["missionTitle"], "Fallback target mission")
        self.assertEqual(
            offer["entitlementId"],
            self._get_entitlement(ids["player"], ids["target"]).id,
        )
        self.assertEqual(offer["offerId"], ids["item"])
        self.assertEqual(offer["priceRoot"], 100)
        self.assertEqual(offer["quotaLimit"], 1)
        self.assertEqual(offer["consumedCount"], 0)
        self.assertEqual(offer["remainingQuota"], 1)
        self.assertEqual(offer["status"], "available")
        self.assertEqual(
            set(offer),
            {
                "missionId",
                "entitlementId",
                "missionSlug",
                "missionTitle",
                "offerId",
                "priceRoot",
                "quotaLimit",
                "consumedCount",
                "remainingQuota",
                "status",
                "item",
            },
        )
        item = offer["item"]
        self.assertEqual(item["id"], ids["item"])
        self.assertEqual(item["slug"], ids["item"])
        self.assertEqual(item["code"], f"ITEM-{ids['item'][5:17]}")
        self.assertEqual(item["title"], "Fixture key")
        self.assertEqual(item["symbol"], "KEY")
        self.assertEqual(item["category"], "key")
        self.assertEqual(item["rarity"], "common")
        self.assertEqual(
            set(item),
            {"id", "slug", "code", "title", "symbol", "category", "rarity"},
        )

    def test_4_3b_3_success_returns_empty(self):
        ids = self._fixture()
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="complete"
        )
        self.assertTrue(result["accepted"])
        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(offers, [])

    def test_4_3b_4_disabled_flag_returns_empty(self):
        ids = self._fixture()
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(self._count_entitlements(ids["player"]), 1)
        with self.SessionLocal.begin() as session:
            from app.models import SystemSetting

            setting = session.get(SystemSetting, "shop.fallback.enabled")
            self.assertIsNotNone(setting)
            setting.value_json = False
        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(offers, [])

    def test_4_3b_5_two_missions_two_offers(self):
        ids = self._fixture(second_mission=True)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.mission_engine.submit_mission(
            ids["player"], ids["target_second"], answer="wrong-second"
        )
        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(len(offers), 2)
        by_mission = {offer["missionId"]: offer for offer in offers}
        self.assertEqual(set(by_mission), {ids["target"], ids["target_second"]})
        first = by_mission[ids["target"]]
        second = by_mission[ids["target_second"]]
        self.assertEqual(first["missionSlug"], ids["target"])
        self.assertEqual(second["missionSlug"], ids["target_second"])
        self.assertEqual(first["missionTitle"], "Fallback target mission")
        self.assertEqual(second["missionTitle"], "Second fallback mission")
        self.assertEqual(first["item"]["id"], ids["item"])
        self.assertEqual(second["item"]["id"], ids["item_second"])
        self.assertEqual(first["status"], "available")
        self.assertEqual(second["status"], "available")

    def test_4_3b_6_isolated_per_player(self):
        ids = self._fixture(second_player=True)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.mission_engine.submit_mission(
            ids["player_second"], ids["target"], answer="wrong-answer"
        )
        self.assertEqual(self._count_entitlements(ids["player"]), 1)
        self.assertEqual(self._count_entitlements(ids["player_second"]), 1)
        first_offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        second_offers = self.fallback_shop.get_fallback_offers(
            ids["player_second"]
        )["offers"]
        self.assertEqual(len(first_offers), 1)
        self.assertEqual(len(second_offers), 1)
        self.assertEqual(first_offers[0]["missionId"], ids["target"])
        self.assertEqual(second_offers[0]["missionId"], ids["target"])
        # В БД 2 entitlement'а, но каждый видит ровно свой — фильтр по player_id.
        self.assertEqual(
            len(first_offers) + len(second_offers),
            2,
        )

    def test_4_3b_7_unpublished_item_returns_disabled_status(self):
        ids = self._fixture()
        result = self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.assertFalse(result["accepted"])
        self.assertEqual(
            self._get_entitlement(ids["player"], ids["target"]).status,
            "available",
        )
        with self.SessionLocal.begin() as session:
            from app.models import Item

            item = session.get(Item, ids["item"])
            self.assertIsNotNone(item)
            item.status = "draft"
        offers = self.fallback_shop.get_fallback_offers(ids["player"])["offers"]
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["status"], "disabled")
        self.assertIsNone(offers[0]["item"])
        # Derived presentation: entitlement в БД не меняется.
        self.assertEqual(
            self._get_entitlement(ids["player"], ids["target"]).status,
            "available",
        )

    # ---- 4.4.1–4.4.10 (POST /api/v1/engine/fallback-offers/{offer_id}/purchases)

    def test_4_4_1_successful_purchase_debits_root_and_credits_item(self):
        ids = self._fixture()
        wallet_id = self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])
        self.assertIsNotNone(entitlement)

        result = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], entitlement.id
        )

        self.assertTrue(result["purchased"])
        self.assertEqual(result["entitlementId"], entitlement.id)
        self.assertEqual(result["consumedCount"], 1)
        self.assertEqual(result["remainingQuota"], 0)
        self.assertEqual(result["status"], "exhausted")
        self.assertEqual(result["priceRoot"], 100)
        self.assertEqual(result["rootBalance"], 900)
        self.assertEqual(result["item"]["id"], ids["item"])
        self.assertEqual(result["item"]["slug"], ids["item"])
        self.assertEqual(
            set(result["item"]),
            {"id", "slug", "code", "title", "symbol", "category", "rarity"},
        )

        with self.SessionLocal() as session:
            from app.geo_team_runtime_models import InventoryEvent

            from app.models import PlayerItem, Wallet, WalletTransaction

            wallet = session.get(Wallet, wallet_id)
            self.assertEqual(wallet.available_balance, 900)

            tx = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet_id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            )
            self.assertIsNotNone(tx)
            self.assertEqual(tx.wallet_id, wallet_id)
            self.assertEqual(tx.amount, 100)
            self.assertEqual(tx.balance_after, 900)
            self.assertEqual(tx.transaction_type, "debit")
            self.assertEqual(tx.reference_id, f"{entitlement.id}:1")

            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(player_item)
            self.assertEqual(player_item.quantity, 1)
            self.assertEqual(player_item.obtained_from_type, "fallback_purchase")
            self.assertEqual(player_item.obtained_from_id, entitlement.id)

            event = session.scalar(
                select(InventoryEvent).where(
                    InventoryEvent.player_item_id == player_item.id,
                    InventoryEvent.event_type == "credited",
                )
            )
            self.assertIsNotNone(event)
            self.assertEqual(event.quantity_delta, 1)
            self.assertEqual(event.reference_type, "fallback_purchase")
            self.assertEqual(event.reference_id, f"{entitlement.id}:1")

    def test_4_4_2_repeated_purchase_is_idempotent(self):
        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])

        first = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], entitlement.id
        )
        second = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], entitlement.id
        )

        self.assertTrue(first["purchased"])
        self.assertTrue(second["purchased"])
        self.assertEqual(second["entitlementId"], entitlement.id)
        self.assertEqual(second["consumedCount"], 1)
        self.assertEqual(second["status"], "exhausted")
        self.assertEqual(second["rootBalance"], 900)

        with self.SessionLocal() as session:
            from app.geo_team_runtime_models import InventoryEvent

            from app.models import PlayerItem, Wallet, WalletTransaction

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertEqual(wallet.available_balance, 900)

            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertEqual(player_item.quantity, 1)

            txs = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(txs), 1)

            events = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.player_item_id == player_item.id,
                    InventoryEvent.event_type == "credited",
                    InventoryEvent.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(events), 1)

    def test_4_4_3_insufficient_root_returns_409_no_changes(self):
        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])

        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                ids["player"], entitlement.id
            )
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(catcher.exception.detail, "Недостаточно ROOT.")

        with self.SessionLocal() as session:
            from app.models import PlayerItem, Wallet, WalletTransaction

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            txs = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(txs), 0)
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNone(player_item)

        refreshed = self._get_entitlement(ids["player"], ids["target"])
        self.assertEqual(refreshed.status, "available")
        self.assertEqual(refreshed.consumed_count, 0)

    def test_4_4_4_disabled_shop_returns_409(self):
        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])
        with self.SessionLocal.begin() as session:
            from app.models import SystemSetting

            setting = session.get(SystemSetting, "shop.fallback.enabled")
            self.assertIsNotNone(setting)
            setting.value_json = False

        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                ids["player"], entitlement.id
            )
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(catcher.exception.detail, "Магазин отключён.")

        with self.SessionLocal() as session:
            from app.models import Wallet, WalletTransaction

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            txs = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(txs), 0)
        refreshed = self._get_entitlement(ids["player"], ids["target"])
        self.assertEqual(refreshed.status, "available")
        self.assertEqual(refreshed.consumed_count, 0)

    def test_4_4_5_wrong_player_returns_404(self):
        ids = self._fixture(second_player=True)
        self._seed_root_wallet(ids["player"], 1000)
        self._seed_root_wallet(ids["player_second"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])
        self.assertIsNotNone(entitlement)

        # Чужой entitlement покупается только игроком-владельцем.
        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                ids["player_second"], entitlement.id
            )
        self.assertEqual(catcher.exception.status_code, 404)
        self.assertEqual(catcher.exception.detail, "Предложение не найдено.")

        # Несуществующий entitlement_id — то же 404.
        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                ids["player"], f"fallback-entitlement-{uuid.uuid4().hex}"
            )
        self.assertEqual(catcher.exception.status_code, 404)

        refreshed = self._get_entitlement(ids["player"], ids["target"])
        self.assertEqual(refreshed.status, "available")
        self.assertEqual(refreshed.consumed_count, 0)

    def test_4_4_6_unpublished_item_returns_409(self):
        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])
        self.assertEqual(entitlement.status, "available")
        with self.SessionLocal.begin() as session:
            from app.models import Item

            item = session.get(Item, ids["item"])
            self.assertIsNotNone(item)
            item.status = "draft"

        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                ids["player"], entitlement.id
            )
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(catcher.exception.detail, "Ключ недоступен.")

        with self.SessionLocal() as session:
            from app.models import Wallet, WalletTransaction

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            txs = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(txs), 0)
        refreshed = self._get_entitlement(ids["player"], ids["target"])
        self.assertEqual(refreshed.status, "available")
        self.assertEqual(refreshed.consumed_count, 0)

    def test_4_4_7_exhausted_entitlement_returns_409(self):
        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])
        # Квота уже исчерпана, но коммиченной покупки нет (ломаные данные) —
        # идемпотентный возврат не срабатывает, отдаётся честный 409.
        with self.SessionLocal.begin() as session:
            from app.geo_team_runtime_models import PlayerFallbackEntitlement

            row = session.get(PlayerFallbackEntitlement, entitlement.id)
            row.consumed_count = 1
            row.status = "available"  # проверяем именно квоту, не статус

        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                ids["player"], entitlement.id
            )
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(catcher.exception.detail, "Квота исчерпана.")

        with self.SessionLocal() as session:
            from app.models import Wallet, WalletTransaction

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            txs = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(txs), 0)

    def test_4_4_8_disabled_entitlement_returns_409(self):
        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])
        with self.SessionLocal.begin() as session:
            from app.geo_team_runtime_models import PlayerFallbackEntitlement

            row = session.get(PlayerFallbackEntitlement, entitlement.id)
            row.status = "disabled"

        with self.assertRaises(self.mission_engine.MissionEngineError) as catcher:
            self.fallback_shop.purchase_fallback_offer_entrypoint(
                ids["player"], entitlement.id
            )
        self.assertEqual(catcher.exception.status_code, 409)
        self.assertEqual(catcher.exception.detail, "Предложение недоступно.")

        with self.SessionLocal() as session:
            from app.models import Wallet, WalletTransaction

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            txs = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(txs), 0)

    def test_4_4_9_two_entitlements_with_same_item_stack_quantity(self):
        ids = self._fixture(second_mission=True)
        self._seed_root_wallet(ids["player"], 1000)
        # Вторая миссия получает ту же награду (тот же Item), что и первая.
        with self.SessionLocal.begin() as session:
            from app.models import MissionReward

            reward = session.scalar(
                select(MissionReward).where(
                    MissionReward.mission_id == ids["target_second"],
                    MissionReward.reward_type == "item",
                )
            )
            self.assertIsNotNone(reward)
            reward.item_id = ids["item"]

        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        self.mission_engine.submit_mission(
            ids["player"], ids["target_second"], answer="wrong-second"
        )
        first = self._get_entitlement(ids["player"], ids["target"])
        second = self._get_entitlement(ids["player"], ids["target_second"])
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertNotEqual(first.id, second.id)

        result_first = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], first.id
        )
        result_second = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], second.id
        )
        self.assertTrue(result_first["purchased"])
        self.assertTrue(result_second["purchased"])
        self.assertEqual(result_first["rootBalance"], 900)
        self.assertEqual(result_second["rootBalance"], 800)

        with self.SessionLocal() as session:
            from app.models import PlayerItem, Wallet, WalletTransaction

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(player_item)
            self.assertEqual(player_item.quantity, 2)

            txs = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(txs), 2)
            # reference_id привязан к entitlement — у двух разных entitlement'ов
            # ключи различаются даже при одном и том же item.
            self.assertEqual(
                {tx.reference_id for tx in txs},
                {f"{first.id}:1", f"{second.id}:1"},
            )
            self.assertEqual(wallet.available_balance, 800)

    def test_4_4_10_ledger_consistency(self):
        ids = self._fixture()
        wallet_id = self._seed_root_wallet(ids["player"], 1000)
        self.mission_engine.submit_mission(
            ids["player"], ids["target"], answer="wrong-answer"
        )
        entitlement = self._get_entitlement(ids["player"], ids["target"])

        result = self.fallback_shop.purchase_fallback_offer_entrypoint(
            ids["player"], entitlement.id
        )
        self.assertTrue(result["purchased"])

        with self.SessionLocal() as session:
            from app.geo_team_runtime_models import InventoryEvent

            from app.models import PlayerItem, Wallet, WalletTransaction

            wallet = session.get(Wallet, wallet_id)
            self.assertEqual(wallet.available_balance, 1000 - 100)

            credit = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet_id,
                    WalletTransaction.transaction_type == "credit",
                )
            )
            debit = session.scalar(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet_id,
                    WalletTransaction.transaction_type == "debit",
                )
            )
            self.assertIsNotNone(credit)
            self.assertIsNotNone(debit)
            self.assertEqual(credit.balance_after, 1000)
            self.assertEqual(debit.amount, 100)
            self.assertEqual(debit.balance_after, 900)
            # Баланс кошелька равен балансу последней проводки (ledger — truth).
            self.assertEqual(wallet.available_balance, debit.balance_after)

            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(player_item)
            events = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.player_item_id == player_item.id,
                    InventoryEvent.event_type == "credited",
                    InventoryEvent.reference_type == "fallback_purchase",
                )
            ).all()
            self.assertEqual(len(events), 1)
            # quantity инвентаря = сумма quantity_delta событий credited.
            self.assertEqual(
                player_item.quantity,
                sum(event.quantity_delta for event in events),
            )

    # ---- mini-тесты validate_value: тип string ------------------------

    def test_validate_value_accepts_string_for_shop_offer_id(self):
        definition = SystemSettingDefinition(
            key="shop.fallback.default_offer_id",
            value_type="string",
            default_value="",
            category="shop",
            title="Идентификатор fallback-предложения",
            description="Ссылка на CMS product, продаваемый после провала.",
            is_sensitive=False,
        )
        validate_value(definition, "offer-fallback-1")

    def test_validate_value_rejects_non_string_for_shop_offer_id(self):
        definition = SystemSettingDefinition(
            key="shop.fallback.default_offer_id",
            value_type="string",
            default_value="",
            category="shop",
            title="Идентификатор fallback-предложения",
            description="Ссылка на CMS product, продаваемый после провала.",
            is_sensitive=False,
        )
        with self.assertRaises(ValueError):
            validate_value(definition, 123)