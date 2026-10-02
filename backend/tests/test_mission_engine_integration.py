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


if __name__ == "__main__":
    unittest.main()
