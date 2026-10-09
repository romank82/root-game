from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.team_missions_service import list_my_team_sessions_entrypoint

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


if __name__ == "__main__":
    unittest.main()
