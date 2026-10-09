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
from app.datetime_utils import ensure_utc


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class TeamsServiceTests(unittest.TestCase):
    """6.4: командный сервис — create/me/get/update, join/leave,
    kick, transfer-leadership, disband + guard 5.3 (активная сессия).
    6.5: приглашения (invite/accept/reject/cancel) и заявки
    (create/cancel, approve/reject лидера, списки) + joinPolicy.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-teams-tests-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "teams.sqlite3"
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

        from app import teams_service

        cls.teams_service = teams_service
        cls._session_local_patch = patch.object(
            teams_service,
            "SessionLocal",
            cls.SessionLocal,
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------
    def _make_player(self, *, display_name: str | None = None) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=display_name or f"Player-{player_id[-6:]}",
                    auth_provider="telegram",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _make_team(
        self,
        leader_id: str,
        *,
        join_policy: str = "by_request",
        max_members: int | None = None,
        name: str | None = None,
    ) -> str:
        from app.models import Team, TeamMember

        team_id = f"team-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            team = Team(
                id=team_id,
                name=name or f"Team-{team_id[-6:]}",
                leader_id=leader_id,
                status="active",
                join_policy=join_policy,
                max_members=max_members,
            )
            session.add(team)
            session.flush()
            session.add(
                TeamMember(
                    id=f"tm-{uuid.uuid4().hex}",
                    team_id=team.id,
                    player_id=leader_id,
                    role="leader",
                    status="active",
                    joined_at=datetime.now(timezone.utc),
                )
            )
        return team_id

    def _add_member(
        self,
        team_id: str,
        player_id: str,
        *,
        role: str = "member",
    ) -> None:
        from app.models import TeamMember

        with self.SessionLocal.begin() as session:
            session.add(
                TeamMember(
                    id=f"tm-{uuid.uuid4().hex}",
                    team_id=team_id,
                    player_id=player_id,
                    role=role,
                    status="active",
                    joined_at=datetime.now(timezone.utc),
                )
            )

    def _create_active_session_for(self, player_id: str) -> str:
        """Полный fixture активной командной миссии (status='active')."""
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
                title="Team mission",
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
            team_session = TeamSession(
                id=f"session-{suffix}",
                mission_id=mission.id,
                status="active",
                effective_config_snapshot={},
            )
            session.add(team_session)
            session.flush()
            session.add(
                TeamSessionMember(
                    id=f"tsm-{suffix}",
                    team_session_id=team_session.id,
                    player_id=player_id,
                    mission_run_id=run.id,
                    status="joined",
                )
            )
        return team_session.id

    def _get_membership(self, team_id: str, player_id: str):
        from app.models import TeamMember

        with self.SessionLocal() as session:
            return session.scalar(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                    TeamMember.player_id == player_id,
                )
            )

    def _get_history(self, team_id: str):
        from app.models import TeamMembershipHistory

        with self.SessionLocal() as session:
            return session.scalars(
                select(TeamMembershipHistory)
                .where(TeamMembershipHistory.team_id == team_id)
                .order_by(TeamMembershipHistory.created_at)
            ).all()

    def _make_invitation(
        self,
        team_id: str,
        invited_player_id: str,
        invited_by_player_id: str,
        *,
        message: str | None = None,
        status: str = "pending",
        expires_at=None,
    ) -> str:
        from app.models import TeamInvitation

        invitation_id = f"inv-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                TeamInvitation(
                    id=invitation_id,
                    team_id=team_id,
                    invited_player_id=invited_player_id,
                    invited_by_player_id=invited_by_player_id,
                    status=status,
                    message=message,
                    expires_at=expires_at,
                )
            )
        return invitation_id

    def _make_join_request(
        self,
        team_id: str,
        player_id: str,
        *,
        message: str | None = None,
        status: str = "pending",
    ) -> str:
        from app.models import TeamJoinRequest

        request_id = f"jr-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                TeamJoinRequest(
                    id=request_id,
                    team_id=team_id,
                    player_id=player_id,
                    status=status,
                    message=message,
                )
            )
        return request_id

    def _get_invitation(self, invitation_id: str):
        from app.models import TeamInvitation

        with self.SessionLocal() as session:
            return session.get(TeamInvitation, invitation_id)

    def _get_join_request(self, request_id: str):
        from app.models import TeamJoinRequest

        with self.SessionLocal() as session:
            return session.get(TeamJoinRequest, request_id)

    # ---- Создание ------------------------------------------------------
    def test_create_team_creates_leader_member_and_history(self):
        from app.models import Team, TeamMember

        player_id = self._make_player()
        created = self.teams_service.create_team_entrypoint(
            player_id,
            name="Alpha",
            description="desc",
            join_policy="open",
        )
        team_id = created["id"]

        with self.SessionLocal() as session:
            team = session.get(Team, team_id)
            self.assertEqual(team.status, "active")
            self.assertEqual(team.leader_id, player_id)
            self.assertEqual(team.join_policy, "open")
            member = session.scalar(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                    TeamMember.player_id == player_id,
                )
            )
            self.assertIsNotNone(member)
            self.assertEqual(member.role, "leader")
            self.assertEqual(member.status, "active")

        history = self._get_history(team_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "joined")
        self.assertEqual(history[0].actor_player_id, player_id)

    def test_create_team_while_in_active_team_returns_409(self):
        player_id = self._make_player()
        self.teams_service.create_team_entrypoint(player_id, name="First")

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.create_team_entrypoint(player_id, name="Second")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_create_team_validation_name_length(self):
        player_id = self._make_player()
        for bad_name in ("", "x" * 129):
            with self.assertRaises(MissionEngineError) as ctx:
                self.teams_service.create_team_entrypoint(
                    player_id,
                    name=bad_name,
                )
            self.assertEqual(ctx.exception.status_code, 400)

    # ---- Чтение ---------------------------------------------------------
    def test_get_my_team_returns_none_when_no_team(self):
        player_id = self._make_player()
        self.assertIsNone(self.teams_service.get_my_team(player_id))

    def test_get_team_returns_serialized_with_members(self):
        from app.models import TeamMember

        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")

        with self.SessionLocal.begin() as session:
            session.add(
                TeamMember(
                    id=f"tm-{uuid.uuid4().hex}",
                    team_id=team_id,
                    player_id=member_id,
                    role="member",
                    status="active",
                    joined_at=datetime.now(timezone.utc),
                )
            )

        team = self.teams_service.get_team(team_id, requester_id=member_id)
        self.assertEqual(team["id"], team_id)
        self.assertEqual(team["leader"]["id"], leader_id)
        self.assertEqual(team["memberCount"], 2)
        roles = {member["role"] for member in team["members"]}
        self.assertEqual(roles, {"leader", "member"})

    def test_get_team_disbanded_returns_404(self):
        leader_id = self._make_player()
        team_id = self.teams_service.create_team_entrypoint(
            leader_id,
            name="Dx",
        )["id"]
        self.teams_service.disband_team_entrypoint(leader_id, team_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.get_team(team_id, requester_id=leader_id)
        self.assertEqual(ctx.exception.status_code, 404)

    # ---- Обновление -----------------------------------------------------
    def test_update_team_by_leader_succeeds(self):
        from app.models import Team

        leader_id = self._make_player()
        team_id = self._make_team(leader_id)

        updated = self.teams_service.update_team_entrypoint(
            leader_id,
            team_id,
            name="NewName",
            join_policy="open",
            max_members=4,
        )
        self.assertEqual(updated["name"], "NewName")
        self.assertEqual(updated["joinPolicy"], "open")

        with self.SessionLocal() as session:
            team = session.get(Team, team_id)
            self.assertEqual(team.name, "NewName")
            self.assertEqual(team.join_policy, "open")
            self.assertEqual(team.max_members, 4)

    def test_update_team_by_non_leader_returns_403(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id)
        self._add_member(team_id, member_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.update_team_entrypoint(
                member_id,
                team_id,
                name="Hacked",
            )
        self.assertEqual(ctx.exception.status_code, 403)

    # ---- Вступление -----------------------------------------------------
    def test_join_open_team_creates_member_and_history(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self.teams_service.create_team_entrypoint(
            leader_id,
            name="Open",
            join_policy="open",
        )["id"]

        result = self.teams_service.join_team_entrypoint(member_id, team_id)
        self.assertEqual(result["memberCount"], 2)

        membership = self._get_membership(team_id, member_id)
        self.assertEqual(membership.role, "member")
        self.assertEqual(membership.status, "active")

        history = self._get_history(team_id)
        self.assertEqual(len(history), 2)
        joined_rows = [row for row in history if row.event_type == "joined"]
        self.assertEqual(len(joined_rows), 2)
        self.assertEqual(joined_rows[1].player_id, member_id)

    def test_join_by_request_team_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.join_team_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_join_when_already_in_team_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.join_team_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_join_reactivates_previous_left_membership(self):
        from app.models import TeamMember

        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")

        self.teams_service.join_team_entrypoint(member_id, team_id)
        self.teams_service.leave_team_entrypoint(member_id, team_id)

        result = self.teams_service.join_team_entrypoint(member_id, team_id)
        self.assertEqual(result["memberCount"], 2)

        # uq_team_members_team_player: ровно одна строка, статус снова active.
        with self.SessionLocal() as session:
            memberships = session.scalars(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                    TeamMember.player_id == member_id,
                )
            ).all()
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0].status, "active")
        self.assertIsNone(memberships[0].left_at)

        history = self._get_history(team_id)
        joined = [row for row in history if row.event_type == "joined"]
        left = [row for row in history if row.event_type == "left"]
        self.assertEqual(len(joined), 2)
        self.assertEqual(len(left), 1)

    def test_join_full_team_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open", max_members=1)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.join_team_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    # ---- Выход ----------------------------------------------------------
    def test_leave_team_succeeds_and_records_left(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)

        result = self.teams_service.leave_team_entrypoint(member_id, team_id)
        self.assertIsNone(result)

        membership = self._get_membership(team_id, member_id)
        self.assertEqual(membership.status, "left")
        self.assertIsNotNone(membership.left_at)

        history = self._get_history(team_id)
        self.assertEqual(history[-1].event_type, "left")
        self.assertEqual(history[-1].player_id, member_id)

    def test_leave_leader_returns_409(self):
        leader_id = self._make_player()
        team_id = self._make_team(leader_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.leave_team_entrypoint(leader_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_leave_with_active_team_session_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)
        self._create_active_session_for(member_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.leave_team_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    # ---- Исключение -----------------------------------------------------
    def test_kick_member_by_leader_succeeds(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)

        result = self.teams_service.kick_member_entrypoint(
            leader_id,
            team_id,
            member_id,
        )
        self.assertIsNone(result)

        membership = self._get_membership(team_id, member_id)
        self.assertEqual(membership.status, "left")

        history = self._get_history(team_id)
        self.assertEqual(history[-1].event_type, "kicked")
        self.assertEqual(history[-1].actor_player_id, leader_id)

    def test_kick_self_returns_409(self):
        leader_id = self._make_player()
        team_id = self._make_team(leader_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.kick_member_entrypoint(
                leader_id,
                team_id,
                leader_id,
            )
        self.assertEqual(ctx.exception.status_code, 409)

    # ---- Передача лидерства ----------------------------------------------
    def test_transfer_leadership_atomic_swaps_roles_and_updates_team(self):
        from app.models import Team

        leader_id = self._make_player()
        new_leader_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(new_leader_id, team_id)

        result = self.teams_service.transfer_leadership_entrypoint(
            leader_id,
            team_id,
            new_leader_id,
        )
        self.assertIsNone(result)

        with self.SessionLocal() as session:
            team = session.get(Team, team_id)
            self.assertEqual(team.leader_id, new_leader_id)

        old = self._get_membership(team_id, leader_id)
        self.assertEqual(old.role, "member")
        new = self._get_membership(team_id, new_leader_id)
        self.assertEqual(new.role, "leader")

        history = self._get_history(team_id)
        self.assertEqual(history[-1].event_type, "leadership_transferred")
        self.assertEqual(
            history[-1].metadata_json["newLeaderId"],
            new_leader_id,
        )

    # ---- Расформирование -------------------------------------------------
    def test_disband_team_by_leader_records_history_for_all_members(self):
        from app.models import Team, TeamMember

        leader_id = self._make_player()
        member_one = self._make_player()
        member_two = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_one, team_id)
        self.teams_service.join_team_entrypoint(member_two, team_id)

        result = self.teams_service.disband_team_entrypoint(leader_id, team_id)
        self.assertIsNone(result)

        with self.SessionLocal() as session:
            team = session.get(Team, team_id)
            self.assertEqual(team.status, "disbanded")
            members = session.scalars(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                )
            ).all()
        for member in members:
            self.assertEqual(member.status, "left")
            self.assertIsNotNone(member.left_at)

        history = self._get_history(team_id)
        disbanded = [row for row in history if row.event_type == "disbanded"]
        self.assertEqual(len(disbanded), 3)
        self.assertEqual(
            {row.player_id for row in disbanded},
            {leader_id, member_one, member_two},
        )

    def test_disband_with_active_team_session_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)
        self._create_active_session_for(member_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.disband_team_entrypoint(leader_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    # ---- Приглашения (шаг 6.5) ------------------------------------------
    def test_invite_player_by_leader_succeeds(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")

        result = self.teams_service.invite_player_entrypoint(
            leader_id,
            team_id,
            target_id,
            message="Вступай!",
        )

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["teamId"], team_id)
        self.assertEqual(result["invitedPlayerId"], target_id)
        self.assertEqual(result["invitedByPlayerId"], leader_id)
        self.assertEqual(result["message"], "Вступай!")
        self.assertIsNotNone(result["expiresAt"])

        invitation = self._get_invitation(result["id"])
        self.assertEqual(invitation.status, "pending")
        self.assertIsNotNone(invitation.expires_at)
        self.assertGreater(
            ensure_utc(invitation.expires_at),
            datetime.now(timezone.utc),
        )

    def test_invite_self_returns_409(self):
        leader_id = self._make_player()
        team_id = self._make_team(leader_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.invite_player_entrypoint(
                leader_id, team_id, leader_id
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_invite_player_already_in_active_team_returns_409(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id)
        # target — лидер другой активной команды.
        self._make_team(target_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.invite_player_entrypoint(
                leader_id, team_id, target_id
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_invite_duplicate_pending_returns_409(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id)

        self.teams_service.invite_player_entrypoint(leader_id, team_id, target_id)

        # uq_team_invitations_pending + явный сервисный guard.
        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.invite_player_entrypoint(
                leader_id, team_id, target_id
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_invite_by_non_leader_returns_403(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.invite_player_entrypoint(
                member_id, team_id, target_id
            )
        self.assertEqual(ctx.exception.status_code, 403)

    def test_get_my_invitations_returns_only_pending(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id)
        self.teams_service.invite_player_entrypoint(leader_id, team_id, target_id)
        self._make_invitation(
            team_id,
            target_id,
            leader_id,
            status="rejected",
        )

        result = self.teams_service.get_my_invitations(target_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "pending")
        self.assertEqual(result[0]["teamId"], team_id)

    def test_accept_invitation_creates_membership_and_history(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")
        invitation = self.teams_service.invite_player_entrypoint(
            leader_id, team_id, member_id
        )

        result = self.teams_service.accept_invitation_entrypoint(
            member_id, invitation["id"]
        )
        self.assertEqual(result["id"], team_id)
        self.assertEqual(result["memberCount"], 2)

        membership = self._get_membership(team_id, member_id)
        self.assertEqual(membership.status, "active")
        self.assertEqual(membership.role, "member")

        stored = self._get_invitation(invitation["id"])
        self.assertEqual(stored.status, "accepted")
        self.assertIsNotNone(stored.responded_at)

        history = self._get_history(team_id)
        self.assertEqual(history[-1].event_type, "joined")
        self.assertEqual(history[-1].player_id, member_id)
        self.assertEqual(
            history[-1].metadata_json["via"],
            "invitation",
        )

    def test_accept_invitation_when_already_in_team_returns_409(self):
        leader_one = self._make_player()
        leader_two = self._make_player()
        member_id = self._make_player()
        team_one = self._make_team(leader_one, join_policy="by_request")
        team_two = self._make_team(leader_two, join_policy="open")
        invitation = self.teams_service.invite_player_entrypoint(
            leader_one, team_one, member_id
        )
        self.teams_service.join_team_entrypoint(member_id, team_two)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.accept_invitation_entrypoint(
                member_id, invitation["id"]
            )
        self.assertEqual(ctx.exception.status_code, 409)

    def test_accept_invitation_reactivates_left_membership(self):
        from app.models import TeamMember

        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")

        self.teams_service.join_team_entrypoint(member_id, team_id)
        self.teams_service.leave_team_entrypoint(member_id, team_id)

        invitation = self.teams_service.invite_player_entrypoint(
            leader_id, team_id, member_id
        )
        result = self.teams_service.accept_invitation_entrypoint(
            member_id, invitation["id"]
        )
        self.assertEqual(result["memberCount"], 2)

        # uq_team_members_team_player: ровно одна строка, статус снова active.
        with self.SessionLocal() as session:
            memberships = session.scalars(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                    TeamMember.player_id == member_id,
                )
            ).all()
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0].status, "active")
        self.assertIsNone(memberships[0].left_at)

    def test_accept_invitation_for_other_player_returns_404(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        other_id = self._make_player()
        team_id = self._make_team(leader_id)
        invitation = self.teams_service.invite_player_entrypoint(
            leader_id, team_id, target_id
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.accept_invitation_entrypoint(
                other_id, invitation["id"]
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_accept_expired_invitation_returns_409(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id)
        invitation_id = self._make_invitation(
            team_id,
            target_id,
            leader_id,
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.accept_invitation_entrypoint(
                target_id, invitation_id
            )
        self.assertEqual(ctx.exception.status_code, 409)

        # Ленивое протухание фиксируется при успешном чтении списка:
        # просроченное приглашение исчезает и получает status=expired.
        result = self.teams_service.get_my_invitations(target_id)
        self.assertEqual(result, [])

        stored = self._get_invitation(invitation_id)
        self.assertEqual(stored.status, "expired")
        self.assertIsNotNone(stored.responded_at)

    def test_reject_invitation_succeeds(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id)
        invitation = self.teams_service.invite_player_entrypoint(
            leader_id, team_id, target_id
        )

        result = self.teams_service.reject_invitation_entrypoint(
            target_id, invitation["id"]
        )
        self.assertIsNone(result)

        stored = self._get_invitation(invitation["id"])
        self.assertEqual(stored.status, "rejected")
        self.assertIsNotNone(stored.responded_at)

    def test_cancel_invitation_by_leader_succeeds(self):
        leader_id = self._make_player()
        target_id = self._make_player()
        team_id = self._make_team(leader_id)
        invitation = self.teams_service.invite_player_entrypoint(
            leader_id, team_id, target_id
        )

        result = self.teams_service.cancel_invitation_entrypoint(
            leader_id, team_id, invitation["id"]
        )
        self.assertIsNone(result)

        stored = self._get_invitation(invitation["id"])
        self.assertEqual(stored.status, "cancelled")
        self.assertIsNotNone(stored.responded_at)

    # ---- Заявки (шаг 6.5) -------------------------------------------------
    def test_create_join_request_for_by_request_team_succeeds(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")

        result = self.teams_service.create_join_request_entrypoint(
            member_id,
            team_id,
            message="Возьмите меня",
        )

        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["teamId"], team_id)
        self.assertEqual(result["playerId"], member_id)
        self.assertEqual(result["message"], "Возьмите меня")

        stored = self._get_join_request(result["id"])
        self.assertEqual(stored.status, "pending")
        self.assertEqual(stored.team_id, team_id)

    def test_create_join_request_for_open_team_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.create_join_request_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_create_join_request_for_invite_only_team_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="invite_only")

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.create_join_request_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_create_join_request_when_already_in_team_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")
        # member — лидер другой активной команды.
        self._make_team(member_id)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.create_join_request_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_create_duplicate_pending_request_returns_409(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")
        self.teams_service.create_join_request_entrypoint(member_id, team_id)

        # uq_team_join_requests_pending + явный сервисный guard.
        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.create_join_request_entrypoint(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 409)

    def test_get_my_join_requests_returns_only_pending(self):
        leader_one = self._make_player()
        leader_two = self._make_player()
        member_id = self._make_player()
        team_one = self._make_team(leader_one, join_policy="by_request")
        team_two = self._make_team(leader_two, join_policy="by_request")
        self.teams_service.create_join_request_entrypoint(member_id, team_one)
        self._make_join_request(team_two, member_id, status="rejected")

        result = self.teams_service.get_my_join_requests(member_id)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["teamId"], team_one)
        self.assertEqual(result[0]["status"], "pending")

    def test_cancel_join_request_by_author_succeeds(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")
        request = self.teams_service.create_join_request_entrypoint(
            member_id, team_id
        )

        result = self.teams_service.cancel_join_request_entrypoint(
            member_id, request["id"]
        )
        self.assertIsNone(result)

        stored = self._get_join_request(request["id"])
        self.assertEqual(stored.status, "cancelled")
        self.assertIsNotNone(stored.responded_at)

    def test_approve_join_request_creates_membership_and_history(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")
        request = self.teams_service.create_join_request_entrypoint(
            member_id, team_id
        )

        result = self.teams_service.approve_join_request_entrypoint(
            leader_id, team_id, request["id"]
        )
        self.assertEqual(result["id"], team_id)
        self.assertEqual(result["memberCount"], 2)

        membership = self._get_membership(team_id, member_id)
        self.assertEqual(membership.status, "active")

        stored = self._get_join_request(request["id"])
        self.assertEqual(stored.status, "accepted")
        self.assertEqual(stored.responded_by_player_id, leader_id)
        self.assertIsNotNone(stored.responded_at)

        history = self._get_history(team_id)
        self.assertEqual(history[-1].event_type, "joined")
        self.assertEqual(history[-1].player_id, member_id)
        self.assertEqual(history[-1].actor_player_id, leader_id)
        self.assertEqual(
            history[-1].metadata_json["via"],
            "join_request",
        )

    def test_approve_join_request_reactivates_left_membership(self):
        from app.models import TeamMember

        leader_id = self._make_player()
        member_id = self._make_player()
        # Открытый набор → вступить и выйти, затем перевести команду
        # в режим by_request и подать заявку.
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)
        self.teams_service.leave_team_entrypoint(member_id, team_id)
        self.teams_service.update_team_entrypoint(
            leader_id, team_id, join_policy="by_request"
        )
        request = self.teams_service.create_join_request_entrypoint(
            member_id, team_id
        )

        result = self.teams_service.approve_join_request_entrypoint(
            leader_id, team_id, request["id"]
        )
        self.assertEqual(result["memberCount"], 2)

        # uq_team_members_team_player: ровно одна строка, статус снова active.
        with self.SessionLocal() as session:
            memberships = session.scalars(
                select(TeamMember).where(
                    TeamMember.team_id == team_id,
                    TeamMember.player_id == member_id,
                )
            ).all()
        self.assertEqual(len(memberships), 1)
        self.assertEqual(memberships[0].status, "active")
        self.assertIsNone(memberships[0].left_at)

    def test_reject_join_request_succeeds(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        team_id = self._make_team(leader_id, join_policy="by_request")
        request = self.teams_service.create_join_request_entrypoint(
            member_id, team_id
        )

        result = self.teams_service.reject_join_request_entrypoint(
            leader_id, team_id, request["id"]
        )
        self.assertIsNone(result)

        stored = self._get_join_request(request["id"])
        self.assertEqual(stored.status, "rejected")
        self.assertEqual(stored.responded_by_player_id, leader_id)
        self.assertIsNotNone(stored.responded_at)

    def test_get_team_join_requests_leader_only_and_filters(self):
        leader_id = self._make_player()
        member_id = self._make_player()
        requester_one = self._make_player()
        requester_two = self._make_player()
        team_id = self._make_team(leader_id, join_policy="open")
        self.teams_service.join_team_entrypoint(member_id, team_id)
        self.teams_service.update_team_entrypoint(
            leader_id, team_id, join_policy="by_request"
        )
        self.teams_service.create_join_request_entrypoint(
            requester_one, team_id, message="первый"
        )
        self.teams_service.create_join_request_entrypoint(
            requester_two, team_id, message="второй"
        )

        # Участник (не лидер) заявки не видит; для не-участника — 404.
        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.get_team_join_requests(member_id, team_id)
        self.assertEqual(ctx.exception.status_code, 403)

        result = self.teams_service.get_team_join_requests(leader_id, team_id)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(row["status"] == "pending" for row in result))
        self.assertCountEqual(
            {row["message"] for row in result},
            {"первый", "второй"},
        )

        # фильтр по не-pending статусу не возвращает pending записи.
        processed = self.teams_service.get_team_join_requests(
            leader_id, team_id, status="rejected"
        )
        self.assertEqual(processed, [])

    def test_team_full_blocks_accept_and_approve(self):
        # accept: слоты заполнились между приглашением и действием игрока.
        leader_one = self._make_player()
        invited_id = self._make_player()
        filler_id = self._make_player()
        team_open = self._make_team(
            leader_one, join_policy="open", max_members=2
        )
        invitation = self.teams_service.invite_player_entrypoint(
            leader_one, team_open, invited_id
        )
        self.teams_service.join_team_entrypoint(filler_id, team_open)

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.accept_invitation_entrypoint(
                invited_id, invitation["id"]
            )
        self.assertEqual(ctx.exception.status_code, 409)

        # approve: вторая заявка не помещается в заполненную команду.
        leader_two = self._make_player()
        member_one = self._make_player()
        member_two = self._make_player()
        team_req = self._make_team(
            leader_two, join_policy="by_request", max_members=2
        )
        request_one = self.teams_service.create_join_request_entrypoint(
            member_one, team_req
        )
        self.teams_service.approve_join_request_entrypoint(
            leader_two, team_req, request_one["id"]
        )
        request_two = self.teams_service.create_join_request_entrypoint(
            member_two, team_req
        )

        with self.assertRaises(MissionEngineError) as ctx:
            self.teams_service.approve_join_request_entrypoint(
                leader_two, team_req, request_two["id"]
            )
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()