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
                    attempt_deadline_seconds=600,
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
        self.assertEqual(entitlement.offer_id, "offer-fallback-1")
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
        self.assertEqual(offer["offerId"], "offer-fallback-1")
        self.assertEqual(offer["quotaLimit"], 1)
        self.assertEqual(offer["consumedCount"], 0)
        self.assertEqual(offer["remainingQuota"], 1)
        self.assertEqual(offer["status"], "available")
        self.assertEqual(
            set(offer),
            {
                "missionId",
                "missionSlug",
                "missionTitle",
                "offerId",
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