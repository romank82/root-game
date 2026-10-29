from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError
from app.team_missions_service import (
    activate_session_entrypoint,
    create_team_session_entrypoint,
    join_team_session,
    list_my_team_sessions_entrypoint,
    mark_ready_entrypoint,
    submit_location_entrypoint,
)
from tests.test_geo_team_contract import valid_team_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class TeamMissionsServiceTests(unittest.TestCase):
    """7.1.a: list_my_team_sessions_entrypoint — активные командные сессии игрока.

    Патчится app.db.SessionLocal (не атрибут модуля): сервис импортирует
    SessionLocal лениво внутри функций (from app.db import SessionLocal),
    поэтому подмена на уровне app.db перехватывает вызов.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-team-missions-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "team_missions.sqlite3"
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

        cls._session_local_patch = patch("app.db.SessionLocal", cls.SessionLocal)
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------
    def _make_player(self) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=f"Player-{player_id[-6:]}",
                    auth_provider="telegram",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _make_session(
        self,
        player_id: str,
        *,
        status: str = "active",
        member_status: str = "joined",
        ready_at: datetime | None = None,
        mission_title: str = "Team mission",
        created_at: datetime | None = None,
    ) -> str:
        from app.geo_team_runtime_models import (
            MissionRun,
            TeamSession,
            TeamSessionMember,
        )
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
                title=mission_title,
                status="published",
                content={},
                validation_config={},
            )
            session.add(mission)
            session.flush()
            run = MissionRun(
                id=f"run-{suffix}",
                player_id=player_id,
                mission_id=mission.id,
                status="active",
                effective_config_snapshot={},
            )
            session.add(run)
            session.flush()
            team_session_kwargs: dict = {
                "id": f"session-{suffix}",
                "mission_id": mission.id,
                "status": status,
                "effective_config_snapshot": {},
            }
            if created_at is not None:
                team_session_kwargs["created_at"] = created_at
            team_session = TeamSession(**team_session_kwargs)
            session.add(team_session)
            session.flush()
            session.add(
                TeamSessionMember(
                    id=f"tsm-{suffix}",
                    team_session_id=team_session.id,
                    player_id=player_id,
                    mission_run_id=run.id,
                    status=member_status,
                    ready_at=ready_at,
                )
            )
        return team_session.id

    def _add_session_member(
        self,
        team_session_id: str,
        player_id: str,
        *,
        status: str = "joined",
    ) -> None:
        from app.geo_team_runtime_models import (
            MissionRun,
            TeamSession,
            TeamSessionMember,
        )

        suffix = uuid.uuid4().hex
        with self.SessionLocal.begin() as session:
            team_session = session.get(TeamSession, team_session_id)
            run = MissionRun(
                id=f"run-{suffix}",
                player_id=player_id,
                mission_id=team_session.mission_id,
                status="active",
                effective_config_snapshot={},
            )
            session.add(run)
            session.flush()
            session.add(
                TeamSessionMember(
                    id=f"tsm-{suffix}",
                    team_session_id=team_session_id,
                    player_id=player_id,
                    mission_run_id=run.id,
                    status=status,
                )
            )

    def _make_team(
        self,
        leader_id: str,
        member_ids: list[str] | None = None,
    ) -> str:
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
        return team_id

    def _make_team_mission(
        self,
        *,
        mission_type: str = "team",
        status: str = "published",
        validation_config: dict | None = None,
    ) -> str:
        """Командная миссия с валидным team/geo validation_config."""
        from app.models import Chapter, Mission, Season
        from tests.test_geo_team_contract import valid_team_config

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
                mission_type=mission_type,
                mission_category="team" if mission_type == "team" else "solo",
                title="Team mission",
                status=status,
                content={},
                validation_config=(
                    valid_team_config()
                    if validation_config is None
                    else validation_config
                ),
            )
            session.add(mission)
        return mission.id

    # ---- Хелперы шага 7.1.c (кошельки/ключи — паттерны
    #      test_mission_engine_integration.py) -----------------------------

    def _make_ready_fixture(
        self,
        leader_id: str,
        member_id: str,
    ) -> tuple[str, str, str]:
        """Сессия двух игроков (создатель + присоединившийся) с командной
        миссией и уникальным ключом.

        Возвращает (mission_id, session_id, item_id). Сессия создаётся через
        7.1.b, участник входит через join_team_session — оба status='joined'.
        """
        config = valid_team_config()
        item_id = f"item-{uuid.uuid4().hex}"
        config["economy"]["requiredItems"] = [{"itemId": item_id, "quantity": 1}]
        mission_id = self._make_team_mission(validation_config=config)
        session_id = create_team_session_entrypoint(leader_id, mission_id)["id"]
        join_team_session(member_id, session_id)
        return mission_id, session_id, item_id

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

    def _get_member(self, session_id: str, player_id: str):
        from app.geo_team_runtime_models import TeamSessionMember

        with self.SessionLocal() as session:
            return session.scalar(
                select(TeamSessionMember).where(
                    TeamSessionMember.team_session_id == session_id,
                    TeamSessionMember.player_id == player_id,
                )
            )

    def _set_member_status(
        self,
        session_id: str,
        player_id: str,
        status: str,
    ) -> None:
        from app.geo_team_runtime_models import TeamSessionMember

        with self.SessionLocal.begin() as session:
            member = session.scalar(
                select(TeamSessionMember).where(
                    TeamSessionMember.team_session_id == session_id,
                    TeamSessionMember.player_id == player_id,
                )
            )
            member.status = status

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

    def _key_quantity(self, player_id: str, item_id: str) -> int:
        from app.models import PlayerItem

        with self.SessionLocal() as session:
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == player_id,
                    PlayerItem.item_id == item_id,
                )
            )
            return player_item.quantity if player_item is not None else 0

    # ---- Тесты ---------------------------------------------------------
    def test_list_returns_empty_when_no_sessions(self) -> None:
        player_id = self._make_player()

        result = list_my_team_sessions_entrypoint(player_id)

        self.assertEqual(result, {"sessions": []})

    def test_list_returns_empty_when_not_in_team(self) -> None:
        member_id = self._make_player()
        outsider_id = self._make_player()
        self._make_session(member_id)

        result = list_my_team_sessions_entrypoint(outsider_id)

        self.assertEqual(result, {"sessions": []})

    def test_list_returns_active_sessions_only(self) -> None:
        player_id = self._make_player()
        self._make_session(player_id, status="collecting")
        self._make_session(player_id, status="succeeded")
        self._make_session(player_id, status="cancelled_before_start")

        result = list_my_team_sessions_entrypoint(player_id)

        self.assertEqual(len(result["sessions"]), 1)
        self.assertEqual(result["sessions"][0]["status"], "collecting")

    def test_list_returns_only_player_sessions(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        self._make_session(player_a)
        self._make_session(player_b)

        result_a = list_my_team_sessions_entrypoint(player_a)
        result_b = list_my_team_sessions_entrypoint(player_b)

        self.assertEqual(len(result_a["sessions"]), 1)
        self.assertEqual(len(result_b["sessions"]), 1)
        self.assertNotEqual(
            result_a["sessions"][0]["id"],
            result_b["sessions"][0]["id"],
        )

    def test_list_includes_mission_title_and_member_count(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id = self._make_session(
            player_a,
            mission_title="Совместный квест",
            ready_at=datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc),
        )
        self._add_session_member(session_id, player_b)

        result = list_my_team_sessions_entrypoint(player_a)

        self.assertEqual(len(result["sessions"]), 1)
        session = result["sessions"][0]
        self.assertEqual(session["missionTitle"], "Совместный квест")
        self.assertEqual(session["memberCount"], 2)
        self.assertEqual(session["myStatus"], "joined")
        self.assertIsNotNone(session["myReadyAt"])

    def test_list_sorts_by_created_at_desc(self) -> None:
        player_id = self._make_player()
        self._make_session(
            player_id,
            created_at=datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone.utc),
        )
        self._make_session(
            player_id,
            created_at=datetime(2026, 10, 2, 8, 0, 0, tzinfo=timezone.utc),
        )
        self._make_session(
            player_id,
            created_at=datetime(2026, 10, 3, 8, 0, 0, tzinfo=timezone.utc),
        )

        result = list_my_team_sessions_entrypoint(player_id)

        self.assertEqual(len(result["sessions"]), 3)
        created = [
            datetime.fromisoformat(item["createdAt"]) for item in result["sessions"]
        ]
        self.assertEqual(created, sorted(created, reverse=True))


    def test_create_session_by_any_player_succeeds(self) -> None:
        player_id = self._make_player()
        mission_id = self._make_team_mission()

        result = create_team_session_entrypoint(player_id, mission_id)

        self.assertEqual(result["status"], "collecting")
        self.assertEqual(result["mission_id"], mission_id)
        # Сессия стартует с одним участником — создателем.
        self.assertEqual(result["memberCount"], 1)
        self.assertEqual(result["myStatus"], "joined")

        from app.geo_team_runtime_models import TeamSessionMember

        with self.SessionLocal.begin() as session:
            rows = session.scalars(
                select(TeamSessionMember).where(
                    TeamSessionMember.team_session_id == result["id"],
                )
            ).all()
        self.assertEqual([row.player_id for row in rows], [player_id])

    def test_create_session_unknown_mission_returns_404(self) -> None:
        player_id = self._make_player()

        with self.assertRaises(MissionEngineError) as captured:
            create_team_session_entrypoint(player_id, f"mission-{uuid.uuid4().hex}")

        self.assertEqual(captured.exception.status_code, 404)

    def test_create_session_wrong_mission_type_returns_409(self) -> None:
        player_id = self._make_player()
        mission_id = self._make_team_mission(mission_type="solo")

        with self.assertRaises(MissionEngineError) as captured:
            create_team_session_entrypoint(player_id, mission_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Эта миссия не командная.")

    def test_create_session_second_active_blocked_returns_409(self) -> None:
        player_id = self._make_player()
        mission_id = self._make_team_mission()
        create_team_session_entrypoint(player_id, mission_id)

        with self.assertRaises(MissionEngineError) as captured:
            create_team_session_entrypoint(player_id, mission_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "У вас уже есть активная командная сессия.",
        )

    # ---- 7.1.b-2: join_team_session -------------------------------------

    def test_join_session_succeeds(self) -> None:
        creator = self._make_player()
        member = self._make_player()
        mission_id = self._make_team_mission()
        session_id = create_team_session_entrypoint(creator, mission_id)["id"]

        result = join_team_session(member, session_id)

        self.assertEqual(result["status"], "collecting")
        self.assertEqual(result["mission_id"], mission_id)
        self.assertEqual(result["memberCount"], 2)
        self.assertEqual(result["myStatus"], "joined")

        from app.geo_team_runtime_models import TeamSessionMember

        with self.SessionLocal.begin() as session:
            rows = session.scalars(
                select(TeamSessionMember).where(
                    TeamSessionMember.team_session_id == session_id,
                )
            ).all()
        self.assertEqual({row.player_id for row in rows}, {creator, member})

    def test_join_session_unknown_session_returns_404(self) -> None:
        player_id = self._make_player()

        with self.assertRaises(MissionEngineError) as captured:
            join_team_session(player_id, f"session-{uuid.uuid4().hex}")

        self.assertEqual(captured.exception.status_code, 404)
        self.assertEqual(captured.exception.detail, "Командная сессия не найдена.")

    def test_join_session_not_collecting_returns_409(self) -> None:
        owner = self._make_player()
        joiner = self._make_player()
        session_id = self._make_session(owner, status="active")

        with self.assertRaises(MissionEngineError) as captured:
            join_team_session(joiner, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Сессия уже не в сборе.")

    def test_join_session_already_member_returns_409(self) -> None:
        creator = self._make_player()
        mission_id = self._make_team_mission()
        session_id = create_team_session_entrypoint(creator, mission_id)["id"]

        with self.assertRaises(MissionEngineError) as captured:
            join_team_session(creator, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Вы уже участник этой сессии.")

    def test_join_session_other_active_session_returns_409(self) -> None:
        creator_a = self._make_player()
        creator_b = self._make_player()
        joiner = self._make_player()
        session_a = create_team_session_entrypoint(
            creator_a, self._make_team_mission()
        )["id"]
        session_b = create_team_session_entrypoint(
            creator_b, self._make_team_mission()
        )["id"]
        join_team_session(joiner, session_a)

        with self.assertRaises(MissionEngineError) as captured:
            join_team_session(joiner, session_b)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "У вас уже есть активная командная сессия.",
        )

    def test_join_session_full_returns_409(self) -> None:
        creator = self._make_player()
        member = self._make_player()
        late = self._make_player()
        config = valid_team_config()
        config["team"]["maxMembers"] = 2
        mission_id = self._make_team_mission(validation_config=config)
        session_id = create_team_session_entrypoint(creator, mission_id)["id"]
        join_team_session(member, session_id)

        with self.assertRaises(MissionEngineError) as captured:
            join_team_session(late, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Слишком много участников для этой миссии.",
        )



    def _seed_geo_zone(
        self,
        *,
        slug: str | None = None,
        latitude: float = 55.7558,
        longitude: float = 37.6173,
        radius_meters: int = 500,
    ) -> str:
        from app.models import GeoZone


        zone_slug = slug or f"zone-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GeoZone(
                    id=f"geo-zone-{uuid.uuid4().hex}",
                    slug=zone_slug,
                    title="Central Park",
                    description="Test geo zone",
                    zone_type="radius",
                    status="published",
                    sort_order=0,
                    latitude=latitude,
                    longitude=longitude,
                    radius_meters=radius_meters,
                    polygon_coordinates=None,
                    timezone="UTC",
                    starts_at=None,
                    ends_at=None,
                    max_location_accuracy_meters=None,
                    minimum_presence_seconds=0,
                )
            )
        return zone_slug

    def _make_location_fixture(
        self,
        leader_id: str,
        member_id: str,
    ) -> tuple[str, str]:
        self._make_team(leader_id, [member_id])
        zone_id = self._seed_geo_zone()
        config = valid_team_config()
        config["geo"]["zoneId"] = zone_id
        mission_id = self._make_team_mission(validation_config=config)
        session_id = create_team_session_entrypoint(leader_id, mission_id)["id"]
        return session_id, zone_id

    def _make_activation_fixture(
        self,
        leader_id: str,
        member_id: str,
    ) -> tuple[str, str]:
        """Готовит ready_to_start-сессию с verified proof у обоих участников.

        Возвращает (session_id, zone_id): оба игрока 'ready' (7.1.c),
        у каждого свежий verified LocationProof (7.1.d). Зона из конфига.
        """
        mission_id, session_id, item_id = self._make_ready_fixture(
            leader_id, member_id
        )
        self._seed_item(item_id)
        self._seed_root_wallet(leader_id, 100)
        self._seed_key(leader_id, item_id, 1)
        self._seed_root_wallet(member_id, 100)
        self._seed_key(member_id, item_id, 1)

        mark_ready_entrypoint(leader_id, session_id)
        mark_ready_entrypoint(member_id, session_id)  # -> ready_to_start

        from app.geo_team_runtime_models import LocationProof, TeamSession
        from app.models import Mission

        with self.SessionLocal.begin() as session:
            team_session = session.get(TeamSession, session_id)
            mission = session.get(Mission, team_session.mission_id)
            config = mission.validation_config
            zone_id = config["geo"]["zoneId"]
            freshness = config["geo"]["proofFreshnessSeconds"]
            now = datetime.now(timezone.utc)
            for proof_player_id in (leader_id, member_id):
                session.add(
                    LocationProof(
                        id=f"location-proof-{uuid.uuid4().hex}",
                        player_id=proof_player_id,
                        provider="dev_mock",
                        status="verified",
                        zone_id=zone_id,
                        verifier_reference=None,
                        issued_at=now,
                        expires_at=now + timedelta(seconds=freshness),
                    )
                )
        return session_id, zone_id

    def _make_active_session_fixture(
        self,
        leader_id: str,
        member_id: str,
    ) -> str:
        """Активированная сессия с готовыми MissionRun у обоих участников.

        Переиспользует _make_activation_fixture (ready_to_start + verified
        proofs), затем активирует сессию лидером — status='active'.
        """
        session_id, _ = self._make_activation_fixture(leader_id, member_id)
        activate_session_entrypoint(leader_id, session_id)
        return session_id

    def _make_team_mission_with_rewards(
        self,
        session_id: str,
        *,
        root_amount: int = 10,
        item_amount: int = 1,
    ) -> str:
        """Key-item + MissionReward (ROOT currency + item) на миссию сессии.

        Item/KeyRules создаются как полноценный CMS-ключ; награды вешаются
        на миссию, к которой привязана активная командная сессия.
        Возвращает item_id награждаемого ключа.
        """
        from app.geo_team_runtime_models import TeamSession
        from app.models import Item, KeyRules, MissionReward

        item_id = f"item-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            team_session = session.get(TeamSession, session_id)
            session.add(
                Item(
                    id=item_id,
                    slug=f"slug-{item_id}-{uuid.uuid4().hex[:8]}",
                    code=f"CODE-{uuid.uuid4().hex[:12]}",
                    title="Team reward key",
                    description="Team mission reward key",
                    symbol="★",
                    category="key",
                    rarity="epic",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            )
            session.add(
                KeyRules(
                    id=f"key-rules-{uuid.uuid4().hex}",
                    item_id=item_id,
                    is_consumable=True,
                )
            )
            session.flush()
            mission_id = team_session.mission_id
            session.add(
                MissionReward(
                    id=f"reward-{uuid.uuid4().hex}",
                    mission_id=mission_id,
                    reward_type="currency",
                    amount=root_amount,
                    reward_value={"currency": "ROOT"},
                    sort_order=1,
                )
            )
            session.add(
                MissionReward(
                    id=f"reward-{uuid.uuid4().hex}",
                    mission_id=mission_id,
                    reward_type="item",
                    item_id=item_id,
                    amount=item_amount,
                    reward_value={},
                    sort_order=2,
                )
            )
        return item_id


    # ---- 7.1.c: mark_ready ---------------------------------------------

    def test_ready_marks_member_and_debits_root_and_item(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, item_id = self._make_ready_fixture(leader, member)
        self._seed_item(item_id)
        self._seed_root_wallet(leader, 100)
        self._seed_key(leader, item_id, 2)

        result = mark_ready_entrypoint(leader, session_id)

        self.assertEqual(result["myStatus"], "ready")
        self.assertIsNotNone(result["myReadyAt"])
        # Второй участник ещё 'joined' — сессия остаётся в состоянии сбора.
        self.assertEqual(result["status"], "collecting")
        # entryFeeRootAtomic=25 списан, ключ quantity=1 списан.
        self.assertEqual(self._root_balance(leader), 75)
        self.assertEqual(self._key_quantity(leader, item_id), 1)

        member_row = self._get_member(session_id, leader)
        self.assertEqual(member_row.status, "ready")
        self.assertIsNotNone(member_row.ready_at)

    def test_ready_unknown_session_returns_404(self) -> None:
        player_id = self._make_player()

        with self.assertRaises(MissionEngineError) as captured:
            mark_ready_entrypoint(player_id, f"session-{uuid.uuid4().hex}")

        self.assertEqual(captured.exception.status_code, 404)
        self.assertEqual(captured.exception.detail, "Командная сессия не найдена.")

    def test_ready_not_a_member_returns_404(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        outsider = self._make_player()
        _, session_id, _ = self._make_ready_fixture(leader, member)

        with self.assertRaises(MissionEngineError) as captured:
            mark_ready_entrypoint(outsider, session_id)

        self.assertEqual(captured.exception.status_code, 404)
        self.assertEqual(captured.exception.detail, "Вы не участник этой сессии.")

    def test_ready_already_ready_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, _ = self._make_ready_fixture(leader, member)
        self._set_member_status(session_id, leader, "ready")

        with self.assertRaises(MissionEngineError) as captured:
            mark_ready_entrypoint(leader, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Вы уже отметились готовым.")

    def test_ready_insufficient_root_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, _ = self._make_ready_fixture(leader, member)
        self._seed_root_wallet(leader, 10)  # entryFeeRootAtomic = 25

        with self.assertRaises(MissionEngineError) as captured:
            mark_ready_entrypoint(leader, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Недостаточно ROOT для взятия миссии.",
        )

    def test_ready_missing_required_item_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, _ = self._make_ready_fixture(leader, member)
        self._seed_root_wallet(leader, 100)  # ключа нет → 409

        with self.assertRaises(MissionEngineError) as captured:
            mark_ready_entrypoint(leader, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Недостаточно ключей для взятия миссии.",
        )

    def test_ready_first_of_two_stays_collecting(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, item_id = self._make_ready_fixture(leader, member)
        self._seed_item(item_id)
        self._seed_root_wallet(leader, 100)
        self._seed_key(leader, item_id, 1)

        result = mark_ready_entrypoint(leader, session_id)

        self.assertEqual(result["status"], "collecting")

    def test_ready_last_member_transitions_to_ready_to_start(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, item_id = self._make_ready_fixture(leader, member)
        self._seed_item(item_id)
        self._seed_root_wallet(leader, 100)
        self._seed_key(leader, item_id, 1)
        self._seed_root_wallet(member, 100)
        self._seed_key(member, item_id, 1)

        mark_ready_entrypoint(leader, session_id)
        result = mark_ready_entrypoint(member, session_id)

        self.assertEqual(result["status"], "ready_to_start")

    def test_ready_after_leaving_session_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, item_id = self._make_ready_fixture(leader, member)
        self._seed_item(item_id)
        self._seed_root_wallet(leader, 100)
        self._seed_key(leader, item_id, 1)
        self._set_member_status(session_id, leader, "left")

        with self.assertRaises(MissionEngineError) as captured:
            mark_ready_entrypoint(leader, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Вы вышли из сессии.")


    # ---- 7.1.e: activate ------------------------------------------------
    def test_activate_by_creator_succeeds(self) -> None:
        creator = self._make_player()
        member = self._make_player()
        session_id, _ = self._make_activation_fixture(creator, member)

        result = activate_session_entrypoint(creator, session_id)

        self.assertEqual(result["status"], "active")
        self.assertIsNotNone(result["started_at"])

        from app.geo_team_runtime_models import TeamSession

        with self.SessionLocal() as session:
            team_session = session.get(TeamSession, session_id)
            self.assertEqual(team_session.status, "active")
            self.assertIsNotNone(team_session.started_at)

    def test_activate_by_member_succeeds(self) -> None:
        creator = self._make_player()
        member = self._make_player()
        session_id, _ = self._make_activation_fixture(creator, member)

        # Лидера больше нет: сессию может активировать любой участник.
        result = activate_session_entrypoint(member, session_id)

        self.assertEqual(result["status"], "active")

    def test_activate_not_ready_to_start_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, _ = self._make_ready_fixture(leader, member)

        with self.assertRaises(MissionEngineError) as captured:
            activate_session_entrypoint(leader, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail, "Сессия ещё не готова к старту."
        )

    def test_activate_without_fresh_proof_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        _, session_id, item_id = self._make_ready_fixture(leader, member)
        self._seed_item(item_id)
        self._seed_root_wallet(leader, 100)
        self._seed_key(leader, item_id, 1)
        self._seed_root_wallet(member, 100)
        self._seed_key(member, item_id, 1)

        mark_ready_entrypoint(leader, session_id)
        mark_ready_entrypoint(member, session_id)  # -> ready_to_start

        # Verified proof только у лидера; у участника proof'а нет -> 409.
        from app.geo_team_runtime_models import LocationProof, TeamSession
        from app.models import Mission

        with self.SessionLocal.begin() as session:
            team_session = session.get(TeamSession, session_id)
            mission = session.get(Mission, team_session.mission_id)
            config = mission.validation_config
            zone_id = config["geo"]["zoneId"]
            freshness = config["geo"]["proofFreshnessSeconds"]
            session.add(
                LocationProof(
                    id=f"location-proof-{uuid.uuid4().hex}",
                    player_id=leader,
                    provider="dev_mock",
                    status="verified",
                    zone_id=zone_id,
                    verifier_reference=None,
                    issued_at=datetime.now(timezone.utc),
                    expires_at=(
                        datetime.now(timezone.utc)
                        + timedelta(seconds=freshness)
                    ),
                )
            )

        with self.assertRaises(MissionEngineError) as captured:
            activate_session_entrypoint(leader, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Не у всех участников свежая отметка присутствия.",
        )

    def test_activate_with_expired_proof_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        session_id, zone_id = self._make_activation_fixture(leader, member)

        # Протухаем proof участника - expires_at в прошлом.
        from app.geo_team_runtime_models import LocationProof

        with self.SessionLocal.begin() as session:
            proof = session.scalar(
                select(LocationProof).where(
                    LocationProof.player_id == member,
                    LocationProof.zone_id == zone_id,
                ))
            proof.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)

        with self.assertRaises(MissionEngineError) as captured:
            activate_session_entrypoint(leader, session_id)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Не у всех участников свежая отметка присутствия.",
        )

    def test_submit_location_inside_zone_creates_verified_proof(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        session_id, zone_id = self._make_location_fixture(leader, member)

        result = submit_location_entrypoint(
            leader, session_id, 55.7558, 37.6173, 10.0,
        )

        self.assertTrue(result["verified"])
        self.assertEqual(result["sessionId"], session_id)
        self.assertEqual(result["zoneId"], zone_id)
        self.assertIsNotNone(result["expiresAt"])

        from app.geo_team_runtime_models import LocationProof

        with self.SessionLocal() as session:

            proof = session.scalar(
                select(LocationProof).where(
                    LocationProof.player_id == leader,
                    LocationProof.zone_id == zone_id,
                ))

            self.assertEqual(proof.status, "verified")
            self.assertEqual(proof.provider, "dev_mock")
            self.assertIsNone(proof.verifier_reference)
            self.assertIsNotNone(proof.expires_at)

        # Session/member status stays unchanged (? 7.1.e).
        member_row = self._get_member(session_id, leader)
        self.assertEqual(member_row.status, "joined")


    def test_submit_location_outside_zone_creates_rejected_proof(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        session_id, zone_id = self._make_location_fixture(leader, member)

        result = submit_location_entrypoint(
            leader, session_id, 65.7558, 37.6173, 10.0,
        )

        self.assertFalse(result["verified"])

        from app.geo_team_runtime_models import LocationProof

        with self.SessionLocal() as session:

            proof = session.scalar(
                select(LocationProof).where(
                    LocationProof.player_id == leader,
                ))
            self.assertEqual(proof.status, "rejected")
            self.assertEqual(proof.zone_id, zone_id)

    def test_submit_location_not_member_returns_404(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        session_id, _ = self._make_location_fixture(leader, member)
        outsider = self._make_player()

        with self.assertRaises(MissionEngineError) as captured:
            submit_location_entrypoint(outsider, session_id, 55.7558, 37.6173, 10.0)

        self.assertEqual(captured.exception.status_code, 404)
        self.assertEqual(captured.exception.detail, "Вы не участник этой сессии.")

    def test_submit_location_after_left_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        session_id, _ = self._make_location_fixture(leader, member)
        self._set_member_status(session_id, leader, "left")

        with self.assertRaises(MissionEngineError) as captured:
            submit_location_entrypoint(leader, session_id, 55.7558, 37.6173, 10.0)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Вы больше не в сессии.")

    def test_submit_location_unknown_zone_returns_409(self) -> None:
        leader = self._make_player()
        member = self._make_player()
        self._make_team(leader, [member])
        config = valid_team_config()
        config["geo"]["zoneId"] = "zone-does-not-exist"
        mission_id = self._make_team_mission(validation_config=config)
        session_id = create_team_session_entrypoint(leader, mission_id)["id"]

        with self.assertRaises(MissionEngineError) as captured:
            submit_location_entrypoint(leader, session_id, 55.7558, 37.6173, 10.0)

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(captured.exception.detail, "Геозона недоступна.")

    def test_submit_location_unknown_session_returns_404(self) -> None:
        player_id = self._make_player()

        with self.assertRaises(MissionEngineError) as captured:
            submit_location_entrypoint(player_id, f"session-{uuid.uuid4().hex}", 55.7558, 37.6173, 10.0)

        self.assertEqual(captured.exception.status_code, 404)
        self.assertEqual(captured.exception.detail, "Командная сессия не найдена.")


class OpenAPIContractTests(unittest.TestCase):
    """Защита: OpenAPI строится без PydanticUserError.

    Ловит отсутствующие Pydantic-схемы, на которые ссылаются роуты,
    но которые забыли определить (from __future__ import annotations
    маскирует это на этапе ast.parse).
    """

    def test_openapi_schema_builds_without_errors(self) -> None:
        from app.main import app

        schema = app.openapi()
        self.assertIn("paths", schema)

        # Дополнительно: ключевые team-missions роуты присутствуют в схеме.
        paths = schema["paths"]
        for expected in (
            "/api/v1/engine/team-missions/sessions",
            "/api/v1/engine/team-missions/sessions/me",
            "/api/v1/engine/team-missions/sessions/{session_id}/join",
            "/api/v1/engine/team-missions/sessions/{session_id}/ready",
            "/api/v1/engine/team-missions/sessions/{session_id}/location",
            "/api/v1/engine/team-missions/sessions/{session_id}/activate",
        ):
            message = "роут отсутствует в OpenAPI: {0}".format(expected)
            self.assertIn(expected, paths, message)


if __name__ == "__main__":
    unittest.main()
