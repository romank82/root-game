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

    @staticmethod
    def _as_naive_utc(value):
        """SQLite может вернуть naive или tz-aware datetime — приводим к naive UTC."""
        from datetime import timezone

        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    # ---- Хелперы шага 4.1 --------------------------------------------

    def _seed_policy(
        self,
        mission_id: str,
        *,
        entry_root_atomic: int = 0,
        required_items: list[tuple[str, int]] | None = None,
        reward_policy_json: dict | None = None,
        repeatability_policy: str = "one_time",
        attempt_deadline_seconds: int = 600,
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
                    attempt_deadline_seconds=attempt_deadline_seconds,
                    repeatability_policy=repeatability_policy,
                    required_items_json={
                        "schemaVersion": 1,
                        "items": [
                            {"itemId": item_id, "quantity": quantity}
                            for item_id, quantity in (required_items or [])
                        ],
                    },
                    challenge_policy_json={},
                    reward_policy_json=reward_policy_json or {},
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

    def _attach_geo_zone(self, ids: dict[str, str]) -> None:
        """Настроить target-миссии геозону, чтобы accept_mission прошёл."""
        from app.models import GeoZone, Mission

        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, ids["target"])
            self.assertIsNotNone(mission)
            zone_id = f"zone-{uuid.uuid4().hex}"
            session.add(
                GeoZone(
                    id=zone_id,
                    slug=f"zone-{uuid.uuid4().hex}",
                    title="Fixture geo zone",
                    description="Accept fixture geo zone",
                    zone_type="radius",
                    status="published",
                    sort_order=1,
                    latitude=55.751244,
                    longitude=37.618423,
                    radius_meters=500,
                    search_radius_meters=1500,
                    location_constraints={},
                )
            )
            mission.geo_zone_id = zone_id

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
        from app.models import PlayerItem, PlayerMission, Wallet, WalletTransaction

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
            # Проверки изолированы по игроку фикстуры: disposable SQLite-БД
            # общая на весь класс, поэтому глобальный count(...) задевал бы
            # данные соседних тестов (порядко-зависимость).
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id))
                    .join(Wallet, WalletTransaction.wallet_id == Wallet.id)
                    .where(Wallet.player_id == ids["player"])
                ),
                0,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(PlayerItem.id)).where(
                        PlayerItem.player_id == ids["player"]
                    )
                ),
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
            # Sprint 8.14 (шаг 2): solo-награда помечается per-run
            # reference_id "<player_mission.id>_<successful_completions>".
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 1)

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 15)

            transaction_count = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id == f"{player_mission.id}_1",
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

            # Sprint 8.14 (fix): entry-дебит теперь per-run reference_id.
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 1)
            # accept не вызывался (submit напрямую) → entry_count=0 → _entry_0.
            self.assertEqual(player_mission.entry_count, 0)
            entry_reference_id = f"{player_mission.id}_entry_0"

            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == "mission_entry_debit",
                    WalletTransaction.reference_id == entry_reference_id,
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
                    InventoryEvent.reference_id == entry_reference_id,
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

        # Sprint 8.14 (fix): охранник идемпотентности теперь per-run.
        # Прямой повторный вызов consume в рамках одного захода
        # (entry_count=0, accept не вызывался) не создаёт второй debit — тот же
        # reference_id "<pm.id>_entry_0".
        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, ids["target"])
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 0)
            self.assertEqual(player_mission.entry_count, 0)
            entry_reference_id = f"{player_mission.id}_entry_0"
            self.mission_engine._consume_entry_resources(
                session,
                ids["player"],
                mission,
                player_mission,
            )
            self.mission_engine._consume_entry_resources(
                session,
                ids["player"],
                mission,
                player_mission,
            )

        # Первый реальный submit того же захода тоже не списывает повторно.
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

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == "mission_entry_debit",
                    WalletTransaction.reference_id == entry_reference_id,
                )
            ).all()
            self.assertEqual(len(debits), 1)

            events = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.reference_type == "mission_entry",
                    InventoryEvent.reference_id == entry_reference_id,
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
        from app.models import (
            KeyRules,
            PlayerItem,
            PlayerMission,
            Wallet,
            WalletTransaction,
        )

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

            # Sprint 8.14 (fix): entry-дебит per-run reference_id.
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            entry_reference_id = f"{player_mission.id}_entry_0"

            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.reference_type
                        == "mission_entry_debit",
                        WalletTransaction.reference_id == entry_reference_id,
                    )
                ),
                1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_id == entry_reference_id
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

            # Sprint 8.14 (fix): entry-дебит per-run (entry_count=0,
            # submit без accept) → "_entry_0".
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertEqual(player_mission.status, "in_progress")
            self.assertEqual(player_mission.attempt_count, 1)
            self.assertEqual(player_mission.successful_completions, 0)
            self.assertEqual(player_mission.entry_count, 0)
            entry_reference_id = f"{player_mission.id}_entry_0"

            # Debit-проводка входа осталась, не отменена и ровно одна.
            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_entry_debit",
                    WalletTransaction.reference_id == entry_reference_id,
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
                        WalletTransaction.reference_id == entry_reference_id,
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
                        InventoryEvent.reference_id == entry_reference_id,
                        InventoryEvent.event_type.in_(["credited", "released"]),
                    )
                ),
                0,
            )

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
            # Sprint 8.14 (fix): обе попытки — один заход (entry_count=0,
            # submit без accept), entry-дебит один на тот же "_entry_0".
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertEqual(player_mission.status, "in_progress")
            self.assertEqual(player_mission.attempt_count, 2)
            self.assertEqual(player_mission.successful_completions, 0)
            self.assertEqual(player_mission.entry_count, 0)
            entry_reference_id = f"{player_mission.id}_entry_0"

            # Вторая провальная попытка не списывает повторно.
            self.assertEqual(wallet.available_balance, 45)
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.wallet_id == wallet.id,
                        WalletTransaction.reference_type == "mission_entry_debit",
                        WalletTransaction.reference_id == entry_reference_id,
                    )
                ),
                1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_type == "mission_entry",
                        InventoryEvent.reference_id == entry_reference_id,
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
        from app.models import PlayerMission, Wallet, WalletTransaction

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

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            # Sprint 8.14 (fix): entry-дебит per-run (entry_count=0,
            # submit без accept) → "_entry_0".
            entry_reference_id = f"{player_mission.id}_entry_0"

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
            {"rt": "mission_entry_debit", "rid": entry_reference_id},
        )
        assert_immutable(
            "DELETE FROM inventory_events "
            "WHERE reference_type = :rt AND reference_id = :rid",
            {"rt": "mission_entry", "rid": entry_reference_id},
        )

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_entry_debit",
                    WalletTransaction.reference_id == entry_reference_id,
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
                        InventoryEvent.reference_id == entry_reference_id,
                    )
                ),
                1,
            )


    def test_entry_debit_after_success(self) -> None:
        """Sprint 8.14 (fix): после успеха entry_count=1; после сброса в
        available повторный accept (entry_count=2) списывает entry заново."""
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
        self._attach_geo_zone(ids)
        self._unlock(ids)

        # Первый заход: accept → entry_count=1 → submit списывает "_entry_1".
        accepted = self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )
        self.assertIn("spawn", accepted)
        first = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(first["accepted"])

        # Сброс в available — временный суррогат шага 5 (after_terminal):
        # attempt_count=0, successful_completions и entry_count НЕ трогаем.
        with self.SessionLocal.begin() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 1)
            self.assertEqual(player_mission.entry_count, 1)
            player_mission.status = "available"
            player_mission.attempt_count = 0
            player_mission.started_at = None
            player_mission.completed_at = None
            player_mission.progress = {}

        # Второй заход: accept → entry_count=2 → submit списывает "_entry_2".
        accepted = self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )
        self.assertIn("spawn", accepted)
        second = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(second["accepted"])
        self.assertFalse(second["alreadyCompleted"])

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 2)
            self.assertEqual(player_mission.entry_count, 2)

            first_entry_reference = f"{player_mission.id}_entry_1"
            second_entry_reference = f"{player_mission.id}_entry_2"
            entry_references = {
                first_entry_reference,
                second_entry_reference,
            }

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            # 50 - 5 - 5 (два входа) + 15 + 15 (две награды) = 70.
            self.assertEqual(wallet.available_balance, 70)

            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == "mission_entry_debit",
                    WalletTransaction.reference_id.in_(entry_references),
                )
            ).all()
            # Два debit с разными per-run reference_id.
            self.assertEqual(len(debits), 2)
            self.assertEqual(
                {debit.reference_id for debit in debits},
                entry_references,
            )
            self.assertEqual(
                {debit.amount for debit in debits},
                {5},
            )

            # Ключи списаны за оба захода: 2 - 1 - 1 + 2 + 2 = 4.
            item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(item)
            self.assertEqual(item.quantity, 4)

            # Два consumed-события с разными per-run reference_id.
            entry_events = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.reference_type == "mission_entry",
                    InventoryEvent.reference_id.in_(entry_references),
                )
            ).all()
            self.assertEqual(len(entry_events), 2)
            self.assertEqual(
                {event.reference_id for event in entry_events},
                entry_references,
            )


    def test_entry_debit_idempotent_within_run(self) -> None:
        """Sprint 8.14 (fix): retry в рамках захода не создаёт второй debit."""
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
        self._attach_geo_zone(ids)
        self._unlock(ids)

        # Accept: начало захода → entry_count=1.
        accepted = self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )
        self.assertIn("spawn", accepted)

        # Провальная попытка: entry списан, заход остаётся in_progress.
        rejected = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong",
            sequence=None,
        )
        self.assertFalse(rejected["accepted"])

        # Retry того же захода: consume вызывается с тем же reference_id
        # "_entry_1" (entry_count при submit-rety не инкрементируется).
        accepted = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(accepted["accepted"])

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 1)
            # attempt_count вырос (retry), но entry_count тот же → один debit.
            self.assertEqual(player_mission.entry_count, 1)
            self.assertEqual(player_mission.attempt_count, 2)
            entry_reference_id = f"{player_mission.id}_entry_1"

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            # 50 - 5 (единственный entry) + 15 (награда) = 60.
            self.assertEqual(wallet.available_balance, 60)

            # Ровно один debit и одно consumed-событие на reference_id захода.
            self.assertEqual(
                session.scalar(
                    select(func.count(WalletTransaction.id)).where(
                        WalletTransaction.wallet_id == wallet.id,
                        WalletTransaction.reference_type
                        == "mission_entry_debit",
                        WalletTransaction.reference_id == entry_reference_id,
                    )
                ),
                1,
            )
            self.assertEqual(
                session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.reference_type == "mission_entry",
                        InventoryEvent.reference_id == entry_reference_id,
                    )
                ),
                1,
            )

            # Ключ списан один раз: 2 - 1 + 2 = 3.
            item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(item)
            self.assertEqual(item.quantity, 3)


    def test_entry_debit_per_new_accept(self) -> None:
        """Sprint 8.14 (fix): заход ПОСЛЕ ПРОВАЛА (expire → cooldown →
        available) снова списывает entry: заход 1 → "_entry_1", заход 2 →
        "_entry_2". Идемпотентный повторный accept НЕ инкрементирует."""
        from datetime import datetime, timedelta, timezone

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
        self._attach_geo_zone(ids)
        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, ids["target"])
            self.assertIsNotNone(mission)
            mission.reentry_cooldown_seconds = 300
        self._unlock(ids)

        # Первый accept → entry_count=1. Идемпотентный повторный accept
        # (in_progress + spawn уже есть) НЕ инкрементирует entry_count.
        first_accept = self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )
        self.assertIn("spawn", first_accept)
        repeated_accept = self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )
        self.assertIn("spawn", repeated_accept)

        # Провал захода: 3 неверные попытки → 4-я блокируется (max_attempts=3)
        # → expired + available_again_at (cooldown 300).
        for _ in range(3):
            rejected = self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="wrong_answer",
                sequence=None,
            )
            self.assertFalse(rejected["accepted"])

        with self.assertRaises(self.mission_engine.MissionEngineError) as error:
            self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="wrong_answer",
                sequence=None,
            )
        self.assertEqual(error.exception.status_code, 409)

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "expired")
            self.assertEqual(player_mission.entry_count, 1)
            self.assertIsNotNone(player_mission.available_again_at)

        # Кулдаун прошёл: сдвигаем available_again_at в прошлое; следующий
        # accept через _synchronize_player_missions вернёт миссию в available.
        with self.SessionLocal.begin() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            player_mission.available_again_at = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(seconds=1)
            )

        # Второй accept ПОСЛЕ провала → entry_count=2 → submit списывает
        # "_entry_2" (другой reference_id — новый заход).
        second_accept = self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )
        self.assertIn("spawn", second_accept)
        completed = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(completed["accepted"])

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "completed")
            self.assertEqual(player_mission.entry_count, 2)
            # attempt_count сброшен при возврате из cooldown → 1 успешная
            # попытка во втором заходе.
            self.assertEqual(player_mission.attempt_count, 1)

            first_entry_reference = f"{player_mission.id}_entry_1"
            second_entry_reference = f"{player_mission.id}_entry_2"
            entry_references = {
                first_entry_reference,
                second_entry_reference,
            }

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            # 50 - 5 (вход захода 1) - 5 (вход захода 2) + 15 (награда) = 55.
            self.assertEqual(wallet.available_balance, 55)

            # Ровно два debit с разными per-run reference_id.
            debits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == "mission_entry_debit",
                    WalletTransaction.reference_id.in_(entry_references),
                )
            ).all()
            self.assertEqual(len(debits), 2)
            self.assertEqual(
                {debit.reference_id for debit in debits},
                entry_references,
            )
            self.assertEqual(
                {debit.amount for debit in debits},
                {5},
            )

            # Ключи: 2 (seed) - 1 (вход захода 1) - 1 (вход захода 2)
            # + 2 (награда) = 2. Попытки 2-3 того же захода не списывали
            # повторно (тот же reference_id → unique index).
            item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == ids["player"],
                    PlayerItem.item_id == ids["item"],
                )
            )
            self.assertIsNotNone(item)
            self.assertEqual(item.quantity, 2)

            # Два consumed-события — по одному на каждый заход.
            entry_events = session.scalars(
                select(InventoryEvent).where(
                    InventoryEvent.reference_type == "mission_entry",
                    InventoryEvent.reference_id.in_(entry_references),
                )
            ).all()
            self.assertEqual(len(entry_events), 2)
            self.assertEqual(
                {event.reference_id for event in entry_events},
                entry_references,
            )


    def test_zz_after_terminal_completed_to_available_no_cooldown(self) -> None:
        """Sprint 8.14 (шаг 5): after_terminal + cooldown=0 → completed сразу в available."""
        from app.models import PlayerMission

        ids = self._fixture()
        self._seed_policy(ids["target"], repeatability_policy="after_terminal")
        self._unlock(ids)
        self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )

        with self.SessionLocal.begin() as session:
            self.mission_engine._synchronize_player_missions(session, ids["player"])
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "available")
            self.assertEqual(player_mission.attempt_count, 0)
            # entry_count и successful_completions НЕ сбрасываются —
            # они накопительные (для reference_id).
            self.assertEqual(player_mission.successful_completions, 1)
            self.assertEqual(player_mission.entry_count, 0)
            self.assertIsNone(player_mission.available_again_at)
            self.assertIsNone(player_mission.completed_at)
            self.assertIsNone(player_mission.started_at)
            self.assertEqual(player_mission.progress, {})

    def test_zz_after_terminal_completed_to_available_with_cooldown(self) -> None:
        """Sprint 8.14 (шаг 5): after_terminal + cooldown=300 → ждём cooldown,
        затем sync возвращает в available."""
        from datetime import datetime, timedelta, timezone

        from app.models import Mission, PlayerMission

        ids = self._fixture()
        self._seed_policy(ids["target"], repeatability_policy="after_terminal")
        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, ids["target"])
            self.assertIsNotNone(mission)
            mission.reentry_cooldown_seconds = 300
        self._unlock(ids)
        self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )

        # Первый sync: completed → ставим available_again_at=completed_at+300,
        # статус остаётся completed (ещё в cooldown).
        with self.SessionLocal.begin() as session:
            self.mission_engine._synchronize_player_missions(session, ids["player"])
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "completed")
            self.assertIsNotNone(player_mission.available_again_at)
            self.assertIsNotNone(player_mission.completed_at)
            self.assertEqual(player_mission.successful_completions, 1)
            self.assertEqual(player_mission.entry_count, 0)

        # Перемотка cooldown в прошлое → следующий sync возвращает available.
        with self.SessionLocal.begin() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            player_mission.available_again_at = (
                datetime.now(timezone.utc).replace(tzinfo=None)
                - timedelta(seconds=1)
            )

        with self.SessionLocal.begin() as session:
            self.mission_engine._synchronize_player_missions(session, ids["player"])
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "available")
            self.assertEqual(player_mission.attempt_count, 0)
            self.assertIsNone(player_mission.available_again_at)
            self.assertIsNone(player_mission.completed_at)
            self.assertEqual(player_mission.successful_completions, 1)
            self.assertEqual(player_mission.entry_count, 0)

    def test_zz_once_policy_stays_completed(self) -> None:
        """Sprint 8.14 (шаг 5): one_time → после completed остаётся completed."""
        from app.models import PlayerMission

        ids = self._fixture()
        self._seed_policy(ids["target"], repeatability_policy="one_time")
        self._unlock(ids)
        self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )

        with self.SessionLocal.begin() as session:
            self.mission_engine._synchronize_player_missions(session, ids["player"])
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "completed")
            self.assertEqual(player_mission.successful_completions, 1)
            self.assertEqual(player_mission.entry_count, 0)

    def test_zz_no_policy_stays_completed(self) -> None:
        """Sprint 8.14 (шаг 5): legacy без policy → после completed остаётся completed."""
        from app.models import PlayerMission

        ids = self._fixture()
        # Без _seed_policy — published policy отсутствует (legacy-миссия).
        self._unlock(ids)
        self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )

        with self.SessionLocal.begin() as session:
            self.mission_engine._synchronize_player_missions(session, ids["player"])
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "completed")
            self.assertEqual(player_mission.successful_completions, 1)
            self.assertEqual(player_mission.entry_count, 0)

    def test_zz_attempt_deadline_resets_per_attempt(self) -> None:
        """Sprint 8.14 (шаг 6): per-attempt timer — deadline_at сбрасывается на
        каждую новую попытку по attempt_deadline_seconds из policy."""
        from datetime import datetime, timedelta, timezone

        from app.models import Mission, PlayerMission

        ids = self._fixture()
        self._seed_policy(ids["target"], attempt_deadline_seconds=60)
        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, ids["target"])
            self.assertIsNotNone(mission)
            # accept ставит deadline из execution_time_limit_seconds.
            mission.execution_time_limit_seconds = 60
        self._attach_geo_zone(ids)
        self._unlock(ids)

        self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertIsNotNone(player_mission.deadline_at)
            deadline_after_accept = self._as_naive_utc(
                player_mission.deadline_at
            )

        # Промах: attempt инкрементируется, deadline перезаписывается на now+60.
        before_submit = datetime.now(timezone.utc).replace(tzinfo=None)
        rejected = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong-answer",
            sequence=None,
        )
        self.assertFalse(rejected["accepted"])

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "in_progress")
            self.assertEqual(player_mission.attempt_count, 1)
            self.assertIsNotNone(player_mission.deadline_at)
            deadline_after_submit = self._as_naive_utc(
                player_mission.deadline_at
            )

        # deadline обновлён (новое, более позднее значение) и равен ~ now + 60.
        self.assertGreater(deadline_after_submit, deadline_after_accept)
        expected = before_submit + timedelta(seconds=60)
        self.assertLess(
            abs((deadline_after_submit - expected).total_seconds()),
            5,
        )

    def test_zz_attempt_deadline_fallback_to_execution_limit(self) -> None:
        """Sprint 8.14 (шаг 6): без policy — fallback на execution_time_limit_seconds,
        deadline не перезаписывается (ставится только при первом выставлении)."""
        from datetime import datetime, timedelta, timezone

        from app.models import Mission, PlayerMission

        ids = self._fixture()
        # policy отсутствует (legacy); лимит задан на уровне миссии.
        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, ids["target"])
            self.assertIsNotNone(mission)
            mission.execution_time_limit_seconds = 300
        self._attach_geo_zone(ids)
        self._unlock(ids)

        before_accept = datetime.now(timezone.utc).replace(tzinfo=None)
        self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertIsNotNone(player_mission.deadline_at)
            deadline_after_accept = self._as_naive_utc(
                player_mission.deadline_at
            )

        expected = before_accept + timedelta(seconds=300)
        self.assertLess(
            abs((deadline_after_accept - expected).total_seconds()),
            5,
        )

        rejected = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong-answer",
            sequence=None,
        )
        self.assertFalse(rejected["accepted"])

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertIsNotNone(player_mission.deadline_at)
            # Fallback не перезаписывает уже выставленный deadline.
            self.assertEqual(
                self._as_naive_utc(player_mission.deadline_at),
                deadline_after_accept,
            )

    def test_zz_attempt_deadline_no_policy_no_limit(self) -> None:
        """Sprint 8.14 (шаг 6): нет policy и нет execution_time_limit_seconds —
        deadline_at остаётся None (миссия без ограничения времени)."""
        from app.models import PlayerMission

        ids = self._fixture()
        # Ни policy, ни execution_time_limit_seconds (fixture default None).
        self._attach_geo_zone(ids)
        self._unlock(ids)

        self.mission_engine.accept_mission(
            ids["player"],
            ids["target"],
            latitude=55.751244,
            longitude=37.618423,
        )

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertIsNone(player_mission.deadline_at)

        rejected = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="wrong-answer",
            sequence=None,
        )
        self.assertFalse(rejected["accepted"])

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertIsNone(player_mission.deadline_at)

    def test_cipher_reward_per_run_reference_id(self) -> None:
        """Sprint 8.14 (шаг 2): первый успех помечает награду "<pm.id>_1"."""
        from app.models import PlayerMission, Wallet, WalletTransaction

        ids = self._fixture()
        self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
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

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 1)

            run_reference_id = f"{player_mission.id}_1"

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 15)

            credits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id == run_reference_id,
                )
            ).all()
            self.assertEqual(len(credits), 1)
            self.assertEqual(credits[0].transaction_type, "credit")
            self.assertEqual(credits[0].amount, 15)

    def test_cipher_second_run_creates_new_transaction(self) -> None:
        """Sprint 8.14 (шаг 2): второй проход — новый reference_id "<pm.id>_2"."""
        from app.models import PlayerMission, Wallet, WalletTransaction

        ids = self._fixture()
        self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )

        first = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(first["awarded"]["root"], 15)

        # Новый run: статус сбрасывается в available (after_terminal-поведение
        # появится на шаге 5), накопленный счётчик проходов НЕ обнуляется.
        with self.SessionLocal.begin() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 1)
            player_mission.status = "available"

        second = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(second["accepted"])
        self.assertFalse(second["alreadyCompleted"])
        self.assertEqual(second["awarded"]["root"], 15)

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.successful_completions, 2)

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 30)

            run_reference_ids = {f"{player_mission.id}_1", f"{player_mission.id}_2"}
            transactions = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id.in_(run_reference_ids),
                )
            ).all()
            self.assertEqual(len(transactions), 2)
            self.assertEqual(
                {transaction.reference_id for transaction in transactions},
                run_reference_ids,
            )

    def test_cipher_same_run_idempotent(self) -> None:
        """Sprint 8.14 (шаг 2): retry того же прохода не создаёт вторую награду."""
        from app.models import PlayerMission, Wallet, WalletTransaction

        ids = self._fixture()
        self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )

        accepted = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(accepted["awarded"]["root"], 15)

        # Симуляция retry: повторный submit уже завершённого прохода.
        retry = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(retry["accepted"])
        self.assertTrue(retry["alreadyCompleted"])
        self.assertEqual(
            retry["awarded"],
            {"root": 0, "items": [], "storyNodeIds": []},
        )

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            # Счётчик не инкрементирован повторно — reference_id тот же.
            self.assertEqual(player_mission.successful_completions, 1)

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 15)

            transaction_count = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id == f"{player_mission.id}_1",
                )
            )
            self.assertEqual(transaction_count, 1)

    def test_multiplier_applied_to_subsequent_attempts(self) -> None:
        """Sprint 8.14 (шаг 4): attempt 1 → 1.0, attempt 2 → 0.5, attempt 3 → 0.25.

        Policy attemptMultipliers = ["1", "0.5", "0.25"], награда 10 ROOT:
        10 → 5 → 2 (floor(10 * 250_000 // 1_000_000)).
        """
        from app.models import MissionReward, PlayerMission, Wallet, WalletTransaction

        ids = self._fixture()

        # Награда target = 10 ROOT (в базовой фикстуре 15).
        with self.SessionLocal.begin() as session:
            reward = session.scalar(
                select(MissionReward).where(
                    MissionReward.mission_id == ids["target"],
                    MissionReward.reward_type == "currency",
                )
            )
            self.assertIsNotNone(reward)
            reward.amount = 10

        self._seed_policy(
            ids["target"],
            reward_policy_json={
                "schemaVersion": 1,
                "attemptMultipliers": ["1", "0.5", "0.25"],
                "rewards": [],
            },
        )

        self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )

        def _reset_run() -> None:
            """Новый run: статус → available, attempt_count сохраняется."""
            with self.SessionLocal.begin() as session:
                player_mission = session.scalar(
                    select(PlayerMission).where(
                        PlayerMission.player_id == ids["player"],
                        PlayerMission.mission_id == ids["target"],
                    )
                )
                self.assertIsNotNone(player_mission)
                player_mission.status = "available"

        attempt_1 = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(attempt_1["awarded"]["root"], 10)

        _reset_run()
        attempt_2 = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(attempt_2["awarded"]["root"], 5)

        _reset_run()
        attempt_3 = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(attempt_3["awarded"]["root"], 2)

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.attempt_count, 3)
            self.assertEqual(player_mission.successful_completions, 3)

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 17)

            run_reference_ids = {
                f"{player_mission.id}_1",
                f"{player_mission.id}_2",
                f"{player_mission.id}_3",
            }
            transactions = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                    WalletTransaction.reference_id.in_(run_reference_ids),
                )
            ).all()
            self.assertEqual(len(transactions), 3)
            self.assertEqual(
                {transaction.amount for transaction in transactions}, {2, 5, 10}
            )

    def test_multiplier_without_policy_gives_full_reward(self) -> None:
        """Sprint 8.14 (шаг 4): без policy/множителей награда не масштабируется."""
        from app.models import MissionReward, Wallet

        ids = self._fixture()

        # Награда target = 10 ROOT (в базовой фикстуре 15), policy нет — как
        # legacy-миссии вне CMS: множителя нет, attempt 1 выдаёт полную сумму.
        with self.SessionLocal.begin() as session:
            reward = session.scalar(
                select(MissionReward).where(
                    MissionReward.mission_id == ids["target"],
                    MissionReward.reward_type == "currency",
                )
            )
            self.assertIsNotNone(reward)
            reward.amount = 10

        self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )
        accepted = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertTrue(accepted["accepted"])
        self.assertEqual(accepted["awarded"]["root"], 10)

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 10)

    def test_multiplier_zero_amount_skipped(self) -> None:
        """Sprint 8.14 (шаг 4): 1 ROOT * 0.5/0.25 → 0 → награда без проводки."""
        from app.models import MissionReward, PlayerMission, Wallet, WalletTransaction

        ids = self._fixture()

        with self.SessionLocal.begin() as session:
            reward = session.scalar(
                select(MissionReward).where(
                    MissionReward.mission_id == ids["target"],
                    MissionReward.reward_type == "currency",
                )
            )
            self.assertIsNotNone(reward)
            reward.amount = 1

        self._seed_policy(
            ids["target"],
            reward_policy_json={
                "schemaVersion": 1,
                "attemptMultipliers": ["1", "0.5", "0.25"],
                "rewards": [],
            },
        )

        self.mission_engine.submit_mission(
            ids["player"],
            ids["unlock"],
            answer="unlock",
            sequence=None,
        )
        first = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(first["awarded"]["root"], 1)

        def _reset_run() -> None:
            with self.SessionLocal.begin() as session:
                player_mission = session.scalar(
                    select(PlayerMission).where(
                        PlayerMission.player_id == ids["player"],
                        PlayerMission.mission_id == ids["target"],
                    )
                )
                self.assertIsNotNone(player_mission)
                player_mission.status = "available"

        # Attempt 2: 1 * 0.5 = 0 (доля округляется вниз) — проводки нет.
        _reset_run()
        second = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(second["awarded"]["root"], 0)

        # Attempt 3: 1 * 0.25 = 0 — тоже без проводки.
        _reset_run()
        third = self.mission_engine.submit_mission(
            ids["player"],
            ids["target"],
            answer="complete",
            sequence=None,
        )
        self.assertEqual(third["awarded"]["root"], 0)

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.attempt_count, 3)
            self.assertEqual(player_mission.successful_completions, 3)

            wallet = session.scalar(
                select(Wallet).where(Wallet.player_id == ids["player"])
            )
            self.assertIsNotNone(wallet)
            self.assertEqual(wallet.available_balance, 1)

            credits = session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type == "mission_reward",
                )
            ).all()
            self.assertEqual(len(credits), 1)
            self.assertEqual(credits[0].amount, 1)


    # ---- Sprint 8.14 (шаг 3): enforcement max_attempts ------------------

    def test_max_attempts_enforced_after_limit(self) -> None:
        """Sprint 8.14 (шаг 3): 3 успешных submit, 4-й → 409 + expired.

        Policy max_attempts=3. После исчерпания лимита новая попытка не
        начинается: attempt_count не инкрементируется, а PlayerMission
        переводится в expired.
        """
        from app.models import PlayerMission

        ids = self._fixture()
        self._seed_policy(ids["target"])  # max_attempts=3
        self._unlock(ids)

        def _reset_run() -> None:
            """Новый run: статус → available, attempt_count сохраняется."""
            with self.SessionLocal.begin() as session:
                player_mission = session.scalar(
                    select(PlayerMission).where(
                        PlayerMission.player_id == ids["player"],
                        PlayerMission.mission_id == ids["target"],
                    )
                )
                self.assertIsNotNone(player_mission)
                player_mission.status = "available"

        for _ in range(3):
            accepted = self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
            self.assertTrue(accepted["accepted"])
            _reset_run()

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
            "Попытки исчерпаны. Миссия переведена в expired.",
        )

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            # Отвергнутая попытка не инкрементировала счётчик.
            self.assertEqual(player_mission.attempt_count, 3)
            self.assertEqual(player_mission.status, "expired")
            # cooldown не задан → авто-возврат не планируется.
            self.assertIsNone(player_mission.available_again_at)

    def test_max_attempts_not_enforced_without_policy(self) -> None:
        """Sprint 8.14 (шаг 3): legacy-миссия без policy — лимита нет."""
        from app.models import PlayerMission

        ids = self._fixture()
        self._unlock(ids)

        def _reset_run() -> None:
            with self.SessionLocal.begin() as session:
                player_mission = session.scalar(
                    select(PlayerMission).where(
                        PlayerMission.player_id == ids["player"],
                        PlayerMission.mission_id == ids["target"],
                    )
                )
                self.assertIsNotNone(player_mission)
                player_mission.status = "available"

        for _ in range(5):
            accepted = self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
            self.assertTrue(accepted["accepted"])
            self.assertFalse(accepted["alreadyCompleted"])
            _reset_run()

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.attempt_count, 5)
            self.assertNotEqual(player_mission.status, "expired")


    def test_max_attempts_sets_available_again_at_with_cooldown(self) -> None:
        """Sprint 8.14 (шаг 3): expire по лимиту учитывает cooldown миссии."""
        from datetime import datetime, timedelta, timezone

        from app.models import Mission, PlayerMission

        ids = self._fixture()
        self._seed_policy(ids["target"])  # max_attempts=3

        with self.SessionLocal.begin() as session:
            mission = session.get(Mission, ids["target"])
            self.assertIsNotNone(mission)
            mission.reentry_cooldown_seconds = 300

        self._unlock(ids)

        def _reset_run() -> None:
            with self.SessionLocal.begin() as session:
                player_mission = session.scalar(
                    select(PlayerMission).where(
                        PlayerMission.player_id == ids["player"],
                        PlayerMission.mission_id == ids["target"],
                    )
                )
                self.assertIsNotNone(player_mission)
                player_mission.status = "available"

        for _ in range(3):
            self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
            _reset_run()

        before = datetime.now(timezone.utc).replace(tzinfo=None)
        with self.assertRaises(self.mission_engine.MissionEngineError) as error:
            self.mission_engine.submit_mission(
                ids["player"],
                ids["target"],
                answer="complete",
                sequence=None,
            )
        self.assertEqual(error.exception.status_code, 409)

        with self.SessionLocal() as session:
            player_mission = session.scalar(
                select(PlayerMission).where(
                    PlayerMission.player_id == ids["player"],
                    PlayerMission.mission_id == ids["target"],
                )
            )
            self.assertIsNotNone(player_mission)
            self.assertEqual(player_mission.status, "expired")
            self.assertIsNotNone(player_mission.available_again_at)

            available_again_at = player_mission.available_again_at
            if available_again_at.tzinfo is not None:
                available_again_at = available_again_at.astimezone(
                    timezone.utc
                ).replace(tzinfo=None)
            expected = before + timedelta(seconds=300)
            self.assertLess(
                abs((available_again_at - expected).total_seconds()),
                5,
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
