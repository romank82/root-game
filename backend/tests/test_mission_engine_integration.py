from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class MissionEngineIntegrationTests(unittest.TestCase):
    """Run engine behavior tests against an Alembic-created disposable SQLite DB."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-engine-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "mission-engine.sqlite3"
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

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _fixture(self) -> dict[str, str]:
        from app.models import (
            Chapter,
            GamePlayer,
            Item,
            Mission,
            MissionRequirement,
            MissionReward,
            Season,
            Segment,
            SegmentMission,
            StoryNode,
        )

        suffix = uuid.uuid4().hex
        ids = {
            "player": f"player-{suffix}",
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "segment": f"segment-{suffix}",
            "hidden_segment": f"hidden-segment-{suffix}",
            "unlock": f"unlock-{suffix}",
            "target": f"target-{suffix}",
            "draft": f"draft-{suffix}",
            "story": f"story-{suffix}",
            "item": f"item-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            # Phase 1: root prerequisite.
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="Test season",
                    description="Isolated integration fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()

            # Phase 2: direct dependants of Season.
            session.add_all(
                [
                    Chapter(
                        id=ids["chapter"],
                        season_id=ids["season"],
                        slug=f"chapter-{suffix}",
                        title="Test chapter",
                        description="Isolated integration fixture",
                        status="published",
                        sort_order=1,
                    ),
                    GamePlayer(
                        id=ids["player"],
                        display_name="Integration player",
                        auth_provider="test",
                        external_id=f"test-{suffix}",
                        status="active",
                    ),
                ]
            )
            session.flush()

            # Phase 3: CMS entities depending on Chapter.
            session.add_all(
                [
                    StoryNode(
                        id=ids["story"],
                        chapter_id=ids["chapter"],
                        slug=f"story-{suffix}",
                        title="Unlocked story",
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
                    Segment(
                        id=ids["hidden_segment"],
                        chapter_id=ids["chapter"],
                        slug=f"hidden-segment-{suffix}",
                        title="Draft segment",
                        description="Hidden segment",
                        status="draft",
                        sort_order=20,
                        content={"schemaVersion": 1},
                    ),
                    Item(
                        id=ids["item"],
                        slug=f"item-{suffix}",
                        code=f"ITEM-{suffix[:12]}",
                        title="Fixture item",
                        description="Granted by the isolated test fixture",
                        symbol="◇",
                        category="key",
                        rarity="common",
                        is_unique=False,
                        content={"schemaVersion": 1},
                        status="published",
                    ),
                ]
            )
            session.flush()

            # Phase 4: entities that reference prior CMS entities.
            session.add_all(
                [
                    Mission(
                        id=ids["unlock"],
                        chapter_id=ids["chapter"],
                        slug=f"unlock-{suffix}",
                        mission_type="text_answer",
                        title="Unlock mission",
                        description="Completes the prerequisite",
                        content={"schemaVersion": 1, "ui": {"label": "Unlock"}},
                        validation_config={
                            "validator": "normalized_text_match",
                            "acceptedAnswers": ["unlock"],
                        },
                        status="published",
                        sort_order=20,
                    ),
                    Mission(
                        id=ids["target"],
                        chapter_id=ids["chapter"],
                        story_node_id=ids["story"],
                        slug=f"target-{suffix}",
                        mission_type="text_answer",
                        title="Reward mission",
                        description="Grants fixture rewards",
                        content={"schemaVersion": 1, "ui": {"label": "Reward"}},
                        validation_config={
                            "validator": "normalized_text_match",
                            "acceptedAnswers": ["complete"],
                        },
                        status="published",
                        sort_order=10,
                    ),
                    Mission(
                        id=ids["draft"],
                        chapter_id=ids["chapter"],
                        slug=f"draft-{suffix}",
                        mission_type="text_answer",
                        title="Draft mission",
                        description="Must not be public",
                        content={"schemaVersion": 1, "ui": {"label": "Draft"}},
                        validation_config={
                            "validator": "normalized_text_match",
                            "acceptedAnswers": ["not-public"],
                        },
                        status="draft",
                        sort_order=30,
                    ),
                ]
            )
            session.flush()

            # Phase 5: rewards, prerequisites, and links.
            session.add_all(
                [
                    MissionRequirement(
                        id=f"requirement-{suffix}",
                        mission_id=ids["target"],
                        requirement_type="mission_completed",
                        requirement_value={"missionId": ids["unlock"]},
                        sort_order=1,
                    ),
                    MissionReward(
                        id=f"root-reward-{suffix}",
                        mission_id=ids["target"],
                        reward_type="currency",
                        amount=15,
                        reward_value={"currency": "ROOT"},
                        sort_order=1,
                    ),
                    MissionReward(
                        id=f"item-reward-{suffix}",
                        mission_id=ids["target"],
                        reward_type="item",
                        item_id=ids["item"],
                        amount=2,
                        reward_value={},
                        sort_order=2,
                    ),
                    MissionReward(
                        id=f"story-reward-{suffix}",
                        mission_id=ids["target"],
                        reward_type="story_node",
                        story_node_id=ids["story"],
                        amount=1,
                        reward_value={},
                        sort_order=3,
                    ),
                    SegmentMission(
                        id=f"link-target-{suffix}",
                        segment_id=ids["segment"],
                        mission_id=ids["target"],
                        status="active",
                        sort_order=10,
                    ),
                    SegmentMission(
                        id=f"link-unlock-{suffix}",
                        segment_id=ids["segment"],
                        mission_id=ids["unlock"],
                        status="active",
                        sort_order=20,
                    ),
                    SegmentMission(
                        id=f"link-draft-{suffix}",
                        segment_id=ids["segment"],
                        mission_id=ids["draft"],
                        status="active",
                        sort_order=30,
                    ),
                ]
            )
            session.flush()

        return ids

    @staticmethod
    def _mission_by_id(bootstrap: dict, mission_id: str) -> dict:
        return next(
            mission
            for mission in bootstrap["missions"]
            if mission["id"] == mission_id
        )

    # ---- Хелперы шага 4.1 --------------------------------------------

    def _seed_policy(
        self,
        mission_id: str,
        *,
        entry_root_atomic: int = 0,
        required_items: list[tuple[str, int]] | None = None,
    ) -> None:
        """Создать published policy напрямую через SQLAlchemy (без admin API)."""
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

    def _seed_root_wallet(self, player_id: str, amount: int) -> None:
        """Кошелёк с кредитной проводкой — игровой ROOT на старте теста."""
        from app.models import Wallet, WalletTransaction

        with self.SessionLocal.begin() as session:
            wallet = Wallet(
                id=f"wallet-{uuid.uuid4().hex}",
                player_id=player_id,
                currency="ROOT",
                available_balance=amount,
                locked_balance=0,
            )
            session.add(wallet)
            session.flush()
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet.id,
                    amount=amount,
                    balance_after=amount,
                    transaction_type="credit",
                    reason="Test seed balance",
                    reference_type="test_seed",
                    reference_id=f"seed-{uuid.uuid4().hex}",
                    metadata_json={},
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

    def _unlock(self, ids: dict[str, str]) -> dict:
        """Пройти prerequisite-миссию, чтобы target стал available."""
        result = self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )
        self.assertTrue(result["accepted"])
        return result

    def test_bootstrap_exposes_only_public_content_and_redacts_validation(self) -> None:
        ids = self._fixture()

        bootstrap = self.mission_engine.get_bootstrap(ids["player"])

        mission_ids = {mission["id"] for mission in bootstrap["missions"]}
        self.assertIn(ids["unlock"], mission_ids)
        self.assertIn(ids["target"], mission_ids)
        self.assertNotIn(ids["draft"], mission_ids)

        segment_ids = {segment["id"] for segment in bootstrap["segments"]}
        self.assertEqual(segment_ids, {ids["segment"]})

        segment = bootstrap["segments"][0]
        self.assertEqual(
            [mission["id"] for mission in segment["linkedMissions"]],
            [ids["target"], ids["unlock"]],
        )

        for mission in bootstrap["missions"]:
            self.assertNotIn("validationConfig", mission)
            self.assertNotIn("acceptedAnswers", mission)
            self.assertNotIn("rewardValue", mission)

        self.assertEqual(
            self._mission_by_id(bootstrap, ids["unlock"])["status"],
            "available",
        )
        self.assertEqual(
            self._mission_by_id(bootstrap, ids["target"])["status"],
            "locked",
        )
        self.assertEqual(bootstrap["storyNodes"], [])

    def test_prerequisite_completion_unlocks_reward_mission(self) -> None:
        ids = self._fixture()

        before = self.mission_engine.get_bootstrap(ids["player"])
        self.assertEqual(
            self._mission_by_id(before, ids["target"])["status"],
            "locked",
        )

        with self.assertRaises(self.mission_engine.MissionEngineError) as error:
            self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
        self.assertEqual(error.exception.status_code, 403)

        unlock_result = self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )
        self.assertTrue(unlock_result["accepted"])
        self.assertEqual(unlock_result["missionStatus"], "completed")

        after = self.mission_engine.get_bootstrap(ids["player"])
        self.assertEqual(
            self._mission_by_id(after, ids["target"])["status"],
            "available",
        )

    def test_reward_submit_is_atomic_and_duplicate_safe(self) -> None:
        from app.models import PlayerItem, Wallet, WalletTransaction

        ids = self._fixture()

        self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )

        rejected = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong",
            sequence=None,
        )
        self.assertFalse(rejected["accepted"])

        with self.SessionLocal() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id))
                ),
                0,
            )
            self.assertEqual(
                session.scalar(select(func.count(PlayerItem.id))),
                0,
            )

        accepted = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(accepted["accepted"])
        self.assertFalse(accepted["alreadyCompleted"])
        self.assertEqual(accepted["awarded"]["root"], 15)
        awarded_items = accepted["awarded"]["items"]
        self.assertEqual(len(awarded_items), 1)
        self.assertEqual(
            set(awarded_items[0]),
            {"id", "code", "title", "quantity"},
        )
        self.assertEqual(awarded_items[0]["id"], ids["item"])
        self.assertEqual(awarded_items[0]["quantity"], 2)
        self.assertTrue(awarded_items[0]["code"])
        self.assertTrue(awarded_items[0]["title"])
        self.assertEqual(accepted["awarded"]["storyNodeIds"], [ids["story"]])

        duplicate = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(duplicate["accepted"])
        self.assertTrue(duplicate["alreadyCompleted"])
        self.assertEqual(
            duplicate["awarded"],
            {"root": 0, "items": [], "storyNodeIds": []},
        )

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 15)

            transaction_count = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id == ids["target"],
                )
            )
            self.assertEqual(transaction_count, 1)

            item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(item)
            self.assertEqual(item.quantity, 2)

        final_bootstrap = self.mission_engine.get_bootstrap(ids["player"])
        self.assertEqual(final_bootstrap["wallet"]["availableBalance"], 15)
        self.assertEqual(
            {story["id"] for story in final_bootstrap["storyNodes"]},
            {ids["story"]},
        )


    def test_zz_4_1_1_success_consumes_root_and_key(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import PlayerItem, Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], ids["item"], 2)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)

        accepted = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(accepted["accepted"])

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            # 50 (seed) - 5 (entry) + 15 (reward) = 60.
            self.assertEqual(wallet.available_balance, 60)

            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == "mission_entry_debit",
                    WalletTransaction.reference_id == ids["target"],
                )
            ).all()
            self.assertEqual(len(debits), 1)
            self.assertEqual(debits[0].amount, 5)
            self.assertEqual(debits[0].transaction_type, "debit")
            self.assertEqual(debits[0].balance_after, 45)  # до награды

            item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(item)
            # 2 (seed) - 1 (consumed) + 2 (reward) = 3.
            self.assertEqual(item.quantity, 3)

            events = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.reference_type == "mission_entry",
                    InventoryEvent.reference_id == ids["target"],
                )
            ).all()
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].event_type, "consumed")
            self.assertEqual(events[0].quantity_delta, -1)

    def test_zz_4_1_2_insufficient_root_is_409_and_rolls_back(self) -> None:
        from app.geo_team_runtime_models import MissionRun
        from app.models import WalletTransaction

        ids = self._fixture()
        self._seed_policy(ids["target"], entry_root_atomic=30)
        self._unlock(ids)  # создаёт кошелёк с балансом 0

        with self.assertRaises(self.mission_engine.MissionEngineError) as error:
            self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(
            error.exception.detail,
            "Недостаточно ROOT для взятия миссии.",
        )

        with self.SessionLocal() as session:
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.reference_type
                        == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                    )
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(MissionRun.id)).where(
                        MissionRun.mission_id == ids["target"]
                    )
                ),
                0,
            )

        bootstrap = self.mission_engine.get_bootstrap(ids["player"])
        # Откат: миссия не стартовала и не завершена.
        self.assertEqual(
            self._mission_by_id(bootstrap, ids["target"])["status"],
            "available",
        )
        self.assertEqual(bootstrap["wallet"]["availableBalance"], 0)


    def test_zz_4_1_3_insufficient_key_is_409_and_rolls_back(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent, MissionRun
        from app.models import Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)

        with self.assertRaises(self.mission_engine.MissionEngineError) as error:
            self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
        self.assertEqual(error.exception.status_code, 409)

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertEqual(wallet.available_balance, 50)  # ROOT не тронут

            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.reference_type
                        == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                    )
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_id == ids["target"]
                    )
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(MissionRun.id)).where(
                        MissionRun.mission_id == ids["target"]
                    )
                ),
                0,
            )

    def test_zz_4_1_4_repeated_submit_does_not_charge_twice(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import (
            Mission,
            PlayerItem,
            PlayerMission,
            Wallet,
            WalletTransaction,
        )

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], ids["item"], 2)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)

        first = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(first["accepted"])

        second = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(second["alreadyCompleted"])

        # Прямой повторный вызов consume в новой сессии — проверка охранника
        # идемпотентности в самом механизме (не только через alreadyCompleted).
        with self.SessionLocal() as session:
            mission = session.get(Mission, ids["target"])
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.mission_engine._consume_entry_resources(
                session,
                ids["player"],
                mission,
                player_mission,
            )
            session.flush()

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == "mission_entry_debit",
                    WalletTransaction.reference_id == ids["target"],
                )
            ).all()
            self.assertEqual(len(debits), 1)

            events = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.reference_type == "mission_entry",
                    InventoryEvent.reference_id == ids["target"],
                )
            ).all()
            self.assertEqual(len(events), 1)

            item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            # 2 - 1 (единственное списание) + 2 (награда) = 3.
            self.assertEqual(item.quantity, 3)
            # 50 - 5 (entry) + 15 (reward) = 60 — повторных списаний нет.
            self.assertEqual(wallet.available_balance, 60)


    def test_zz_4_1_5_non_consumable_key_checked_but_not_spent(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import KeyRules, PlayerItem, Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], ids["item"], 2)
        with self.SessionLocal.begin() as session:
            session.add(
                KeyRules(
                    id=f"key-rules-{uuid.uuid4().hex}",
                    item_id=ids["item"],
                    is_consumable=False,
                )
            )
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)

        accepted = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(accepted["accepted"])

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            # ROOT списан, ключ — нет: 50 - 5 + 15 = 60.
            self.assertEqual(wallet.available_balance, 60)
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.reference_type
                        == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                    )
                ),
                1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_id == ids["target"]
                    )
                ),
                0,
            )
            item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            # 2 (seed) + 2 (награда) = 4 — списания не было.
            self.assertEqual(item.quantity, 4)

    def test_zz_4_1_6_zero_entry_policy_consumes_nothing(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_policy(ids["target"], entry_root_atomic=0, required_items=[])
        self._unlock(ids)

        accepted = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(accepted["accepted"])

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            # Только награда за target: 15.
            self.assertEqual(wallet.available_balance, 15)
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.reference_type
                        == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                    )
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_id == ids["target"]
                    )
                ),
                0,
            )

    def test_zz_4_1_7_unpublished_required_item_is_409(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import Item, PlayerItem, Wallet, WalletTransaction

        ids = self._fixture()
        draft_item_id = f"draft-key-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                Item(
                    id=draft_item_id,
                    slug=f"draft-key-{uuid.uuid4().hex}",
                    code=f"DRAFT-{uuid.uuid4().hex[:12]}",
                    title="Draft key",
                    description="Must not gate entry",
                    symbol="◇",
                    category="key",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="draft",
                )
            )
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], draft_item_id, 1)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(draft_item_id, 1)],
        )
        self._unlock(ids)

        with self.assertRaises(self.mission_engine.MissionEngineError) as error:
            self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(error.exception.detail, "Ключ недоступен.")

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertEqual(wallet.available_balance, 50)  # откат

            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.reference_type
                        == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                    )
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_id == ids["target"]
                    )
                ),
                0,
            )
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == draft_item_id,
                )
            )
            self.assertEqual(player_item.quantity, 1)  # не списан

    def test_zz_4_2_1_failed_attempt_keeps_key_consumed(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import PlayerItem, PlayerMission, Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], ids["item"], 2)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)

        rejected = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong_answer",
            sequence=None,
        )
        self.assertFalse(rejected["accepted"])

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            # ROOT списан и не восстановлен: 50 - 5 = 45.
            self.assertEqual(wallet.available_balance, 45)

            # Debit-проводка входа осталась, не отменена и ровно одна.
            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_entry_debit",
                    WalletTransaction.reference_id == ids["target"],
                )
            ).all()
            self.assertEqual(len(debits), 1)
            self.assertEqual(debits[0].transaction_type, "debit")
            self.assertEqual(debits[0].amount, 5)
            self.assertEqual(debits[0].balance_after, 45)

            # Нет credit-проводки по reference входа.
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.wallet_id == wallet.id,
                        WalletTransaction.reference_type == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                        WalletTransaction.transaction_type == "credit",
                    )
                ),
                0,
            )

            # Ключ списан и не восстановлен: 2 - 1 = 1.
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertEqual(player_item.quantity, 1)

            # Сводка 4.2.3: нет credited/released-событий по reference входа.
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_type == "mission_entry",
                        InventoryEvent.reference_id == ids["target"],
                        InventoryEvent.event_type.in_(["credited", "released"]),
                    )
                ),
                0,
            )

            # «Провал» = некорректный ответ: статус in_progress, попытка учтена.
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertEqual(player_mission.status, "in_progress")
            self.assertEqual(player_mission.attempt_count, 1)

    def test_zz_4_2_2_second_failed_attempt_does_not_recharge(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import PlayerItem, PlayerMission, Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], ids["item"], 2)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)

        first = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong",
            sequence=None,
        )
        second = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong",
            sequence=None,
        )
        self.assertFalse(first["accepted"])
        self.assertFalse(second["accepted"])

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            # Вторая провальная попытка не списывает повторно.
            self.assertEqual(wallet.available_balance, 45)
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.wallet_id == wallet.id,
                        WalletTransaction.reference_type == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                    )
                ),
                1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_type == "mission_entry",
                        InventoryEvent.reference_id == ids["target"],
                    )
                ),
                1,
            )

            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertEqual(player_item.quantity, 1)

            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertEqual(player_mission.status, "in_progress")
            self.assertEqual(player_mission.attempt_count, 2)

    def test_zz_4_2_3_no_release_or_credit_events_for_entry_reference(self) -> None:
        from app.geo_team_runtime_models import InventoryEvent
        from app.models import Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], ids["item"], 2)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)

        rejected = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong_answer",
            sequence=None,
        )
        self.assertFalse(rejected["accepted"])

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            # Прямой срез по ledger: для входа нет «возвратных» инвентарных событий.
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_type == "mission_entry",
                        InventoryEvent.reference_id == ids["target"],
                        InventoryEvent.event_type.in_(["credited", "released"]),
                    )
                ),
                0,
            )
            # И нет credit-проводок по reference входа.
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.wallet_id == wallet.id,
                        WalletTransaction.reference_type == "mission_entry_debit",
                        WalletTransaction.reference_id == ids["target"],
                        WalletTransaction.transaction_type == "credit",
                    )
                ),
                0,
            )

    def test_zz_4_2_4_ledger_immutability_trigger_blocks_mutation(self) -> None:
        from sqlalchemy import exc as sa_exc
        from sqlalchemy import text

        from app.geo_team_runtime_models import InventoryEvent
        from app.models import Wallet, WalletTransaction

        ids = self._fixture()
        self._seed_root_wallet(ids["player"], 50)
        self._seed_key(ids["player"], ids["item"], 2)
        self._seed_policy(
            ids["target"],
            entry_root_atomic=5,
            required_items=[(ids["item"], 1)],
        )
        self._unlock(ids)
        self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong_answer",
            sequence=None,
        )

        def assert_immutable(sql: str, params: dict[str, str]) -> None:
            # SQLite RAISE(ABORT) может прийти и как OperationalError,
            # и как IntegrityError (зависит от драйвера/extended codes),
            # поэтому ловим общего родителя DBAPIError и проверяем message.
            try:
                with self.engine.begin() as connection:
                    connection.execute(text(sql), params)
            except sa_exc.DBAPIError as error:
                self.assertIn(
                    "immutable",
                    str(getattr(error, "orig", "")),
                )
            else:
                self.fail("БД допустила мутацию immutable-ledger записи")

        assert_immutable(
            "UPDATE wallet_transactions SET amount = 999 "
            "WHERE reference_type = :rt AND reference_id = :rid",
            {"rt": "mission_entry_debit", "rid": ids["target"]},
        )
        assert_immutable(
            "DELETE FROM inventory_events "
            "WHERE reference_type = :rt AND reference_id = :rid",
            {"rt": "mission_entry", "rid": ids["target"]},
        )

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_entry_debit",
                    WalletTransaction.reference_id == ids["target"],
                )
            ).all()
            # UPDATE не прошёл: проводка на месте и не изменена.
            self.assertEqual(len(debits), 1)
            self.assertEqual(debits[0].amount, 5)

            # DELETE не прошёл: consumed-событие на месте.
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_type == "mission_entry",
                        InventoryEvent.reference_id == ids["target"],
                    )
                ),
                1,
            )


class CipherMatchValidatorUnitTests(unittest.TestCase):
    """Direct unit tests for _validate_submission cipher_match validator."""

    class FakeMission:
        def __init__(self, validation_config: dict) -> None:
            self.validation_config = validation_config
            self.content = {"schemaVersion": 1}

    @staticmethod
    def _validate(
        validation_config: dict,
        sequence,
        answer: str | None = None,
    ) -> bool:
        from app.mission_engine import _validate_submission

        mission = CipherMatchValidatorUnitTests.FakeMission(validation_config)
        return _validate_submission(mission, answer, sequence)

    def test_cipher_match_accepts_correct_sequence(self) -> None:
        validation_config = {
            "validator": "cipher_match",
            "correctCombination": ["R", "O", "O", "T"],
        }

        self.assertTrue(
            self._validate(validation_config, sequence=["R", "O", "O", "T"])
        )

    def test_cipher_match_rejects_wrong_sequence(self) -> None:
        validation_config = {
            "validator": "cipher_match",
            "correctCombination": ["R", "O", "O", "T"],
        }

        self.assertFalse(
            self._validate(validation_config, sequence=["R", "O", "T", "O"])
        )

    def test_cipher_match_rejects_wrong_length(self) -> None:
        validation_config = {
            "validator": "cipher_match",
            "correctCombination": ["R", "O", "O", "T"],
        }

        self.assertFalse(self._validate(validation_config, sequence=["R", "O"]))

    def test_cipher_match_rejects_non_list(self) -> None:
        validation_config = {
            "validator": "cipher_match",
            "correctCombination": ["R", "O", "O", "T"],
        }

        self.assertFalse(self._validate(validation_config, sequence="ROOT"))


if __name__ == "__main__":
    unittest.main()
