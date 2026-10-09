"""Admin Teams API — шаг 6.7.a (только команды, без чата).

Live SQLite + alembic upgrade head (как test_teams_service.py): disposable
БД, permissions teams.read/teams.manage создаются миграцией-сидом.
Endpoint-функции вызываются напрямую с реальными AdminUser из БД и
замоканными SessionLocal (паттерн test_admin_player_mission).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_access import (
    APPROVAL_EXECUTION_MODE,
    DIRECT_EXECUTION_MODE,
    require_permission,
)
from app.admin_teams import (
    ACTION_TYPE_FORCE_DISBAND,
    ACTION_TYPE_FORCE_KICK,
    TEAMS_MANAGE_PERMISSION,
    TEAMS_READ_PERMISSION,
    ForceDisbandPayload,
    ForceKickPayload,
    create_force_disband,
    create_force_kick,
    execute_force_disband,
    execute_force_kick,
    get_admin_team_detail,
    list_admin_team_history,
    list_admin_team_invitations,
    list_admin_team_join_requests,
    list_admin_team_members,
    list_admin_teams,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class AdminTeamsTests(unittest.TestCase):
    """6.7.a: админ read-эндпоинты команд + force-disband/force-kick.

    Покрытие: filter/pagination, member/history/invitation/join-request
    списки, прямые мутации, approval-заявки (202), dedicated executors.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-teams-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "admin-teams.sqlite3"
        database_url = f"sqlite:///{cls.database_path}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url

        # Новая миграция-сид teams.read/teams.manage применяется именно здесь:
        # permission-гранты в тестах ссылаются на них по FK.
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

        from app import admin_access, admin_teams

        cls.admin_teams = admin_teams
        cls._session_local_patch = patch.object(
            admin_teams, "SessionLocal", cls.SessionLocal
        )
        cls._session_local_patch.start()
        cls._access_session_local_patch = patch.object(
            admin_access, "SessionLocal", cls.SessionLocal
        )
        cls._access_session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._access_session_local_patch.stop()
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

# ---- Fixtures и хелперы -------------------------------------------------

    def _request(self) -> SimpleNamespace:
        return SimpleNamespace(
            client=SimpleNamespace(host="203.0.113.7"),
            headers={},
            state=SimpleNamespace(),
        )

    def _make_admin(self, *, username: str | None = None, super_admin: bool = False):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=username or f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin" if super_admin else "admin",
                    is_super_admin=super_admin,
                    is_active=True,
                    is_deleted=False,
                )
            )
        return self._load_admin(admin_id)

    def _load_admin(self, admin_id: str):
        from app.models import AdminUser

        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _grant(
        self,
        admin_id: str,
        permission_code: str,
        *,
        execution_mode: str = DIRECT_EXECUTION_MODE,
    ) -> None:
        from app.models import AdminUserPermission

        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode=execution_mode,
                    is_active=True,
                )
            )

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

    def _mark_team_disbanded(self, team_id: str) -> None:
        from app.models import Team

        with self.SessionLocal.begin() as session:
            team = session.get(Team, team_id)
            team.status = "disbanded"

    def _get_team(self, team_id: str):
        from app.models import Team

        with self.SessionLocal() as session:
            return session.get(Team, team_id)

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
        status: str = "pending",
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
                )
            )
        return invitation_id

    def _make_join_request(
        self,
        team_id: str,
        player_id: str,
        *,
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
                )
            )
        return request_id

    def _create_active_session(self, player_id: str) -> str:
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

    def _json(self, response) -> dict:
        return json.loads(response.body)

    def _get_approval(self, approval_id: str):
        from app.models import AdminApprovalRequest

        with self.SessionLocal() as session:
            return session.get(AdminApprovalRequest, approval_id)

    # ---- Read-эндпоинты команд (шаг 6.7.5a) -----------------------------

    def test_list_teams_default_returns_active(self) -> None:
        prefix = f"t-{uuid.uuid4().hex[:8]}"
        leader_a = self._make_player()
        leader_b = self._make_player()
        leader_c = self._make_player()
        self._make_team(leader_id=leader_a, name=f"{prefix}-a")
        self._make_team(leader_id=leader_b, name=f"{prefix}-b")
        team_d = self._make_team(leader_id=leader_c, name=f"{prefix}-d")
        self._mark_team_disbanded(team_d)

        admin = self._make_admin(super_admin=True)
        self._grant(admin.id, TEAMS_READ_PERMISSION)
        result = list_admin_teams(q=prefix, _admin=admin)

        names = sorted(t["name"] for t in result["teams"])
        self.assertEqual(names, [f"{prefix}-a", f"{prefix}-b"])

    def test_list_teams_filter_by_status_disbanded(self) -> None:
        prefix = f"t-{uuid.uuid4().hex[:8]}"
        leader_a = self._make_player()
        leader_b = self._make_player()
        leader_c = self._make_player()
        self._make_team(leader_id=leader_a, name=f"{prefix}-a")
        self._make_team(leader_id=leader_b, name=f"{prefix}-b")
        team_d = self._make_team(leader_id=leader_c, name=f"{prefix}-d")
        self._mark_team_disbanded(team_d)

        admin = self._make_admin(super_admin=True)
        self._grant(admin.id, TEAMS_READ_PERMISSION)
        result = list_admin_teams(status="disbanded", q=prefix, _admin=admin)

        self.assertEqual(len(result["teams"]), 1)
        self.assertEqual(result["teams"][0]["id"], team_d)
        self.assertEqual(result["teams"][0]["status"], "disbanded")

    def test_list_teams_search_by_name(self) -> None:
        prefix = f"t-{uuid.uuid4().hex[:8]}"
        leader_a = self._make_player()
        leader_b = self._make_player()
        leader_c = self._make_player()
        self._make_team(leader_id=leader_a, name=f"{prefix}-a")
        self._make_team(leader_id=leader_b, name=f"{prefix}-b")
        self._make_team(leader_id=leader_c, name=f"{prefix}-c")

        admin = self._make_admin(super_admin=True)
        self._grant(admin.id, TEAMS_READ_PERMISSION)

        result = list_admin_teams(q=prefix, _admin=admin)
        self.assertEqual(len(result["teams"]), 3)

        result_a = list_admin_teams(q=f"{prefix}-a", _admin=admin)
        self.assertEqual(len(result_a["teams"]), 1)
        self.assertEqual(result_a["teams"][0]["name"], f"{prefix}-a")

    def test_list_teams_filter_by_status_all(self) -> None:
        prefix = f"t-{uuid.uuid4().hex[:8]}"
        leader_a = self._make_player()
        leader_b = self._make_player()
        leader_c = self._make_player()
        self._make_team(leader_id=leader_a, name=f"{prefix}-a")
        self._make_team(leader_id=leader_b, name=f"{prefix}-b")
        team_d = self._make_team(leader_id=leader_c, name=f"{prefix}-d")
        self._mark_team_disbanded(team_d)

        admin = self._make_admin(super_admin=True)
        self._grant(admin.id, TEAMS_READ_PERMISSION)

        result_all = list_admin_teams(status="all", q=prefix, _admin=admin)
        self.assertEqual(len(result_all["teams"]), 3)

        result_active = list_admin_teams(status="active", q=prefix, _admin=admin)
        self.assertEqual(
            sorted(t["name"] for t in result_active["teams"]),
            [f"{prefix}-a", f"{prefix}-b"],
        )

        result_disbanded = list_admin_teams(
            status="disbanded", q=prefix, _admin=admin
        )
        self.assertEqual(len(result_disbanded["teams"]), 1)
        self.assertEqual(result_disbanded["teams"][0]["id"], team_d)

    def test_list_teams_invalid_status_returns_422(self) -> None:
        admin = self._make_admin(super_admin=True)
        self._grant(admin.id, TEAMS_READ_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            list_admin_teams(status="banana", q="x", _admin=admin)
        self.assertEqual(caught.exception.status_code, 422)

        result = list_admin_teams(status="all", q="x", _admin=admin)
        self.assertEqual(result["teams"], [])

    def test_get_team_detail_returns_disbanded_too(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, TEAMS_READ_PERMISSION)

        leader = self._make_player()
        team_id = self._make_team(leader, name="Призраки")
        self._mark_team_disbanded(team_id)

        result = get_admin_team_detail(team_id=team_id, _admin=admin)

        self.assertEqual(result["team"]["id"], team_id)
        self.assertEqual(result["team"]["status"], "disbanded")

    def test_get_team_detail_404_for_unknown(self) -> None:
        admin = self._make_admin()
        self._grant(admin.id, TEAMS_READ_PERMISSION)

        with self.assertRaises(HTTPException) as caught:
            get_admin_team_detail(team_id="team-does-not-exist", _admin=admin)

        self.assertEqual(caught.exception.status_code, 404)

    def test_list_members_default_active_only(self) -> None:
        from app.models import TeamMember

        admin = self._make_admin()
        self._grant(admin.id, TEAMS_READ_PERMISSION)

        leader = self._make_player()
        active_member = self._make_player()
        left_member = self._make_player()
        team_id = self._make_team(leader)
        self._add_member(team_id, active_member)
        with self.SessionLocal.begin() as session:
            session.add(
                TeamMember(
                    id=f"tm-{uuid.uuid4().hex}",
                    team_id=team_id,
                    player_id=left_member,
                    role="member",
                    status="left",
                    joined_at=datetime.now(timezone.utc),
                    left_at=datetime.now(timezone.utc),
                )
            )

        result = list_admin_team_members(team_id=team_id, _admin=admin)

        member_player_ids = {m["playerId"] for m in result["members"]}
        self.assertEqual(len(result["members"]), 2)
        self.assertEqual(member_player_ids, {leader, active_member})

    def test_list_members_status_all_returns_left_too(self) -> None:
        from app.models import TeamMember

        admin = self._make_admin()
        self._grant(admin.id, TEAMS_READ_PERMISSION)

        leader = self._make_player()
        active_member = self._make_player()
        left_member = self._make_player()
        team_id = self._make_team(leader)
        self._add_member(team_id, active_member)
        with self.SessionLocal.begin() as session:
            session.add(
                TeamMember(
                    id=f"tm-{uuid.uuid4().hex}",
                    team_id=team_id,
                    player_id=left_member,
                    role="member",
                    status="left",
                    joined_at=datetime.now(timezone.utc),
                    left_at=datetime.now(timezone.utc),
                )
            )

        result = list_admin_team_members(
            team_id=team_id, status="all", _admin=admin
        )

        by_player = {m["playerId"]: m for m in result["members"]}
        self.assertEqual(len(result["members"]), 3)
        self.assertEqual(
            {m["playerId"] for m in result["members"]},
            {leader, active_member, left_member},
        )
        self.assertEqual(by_player[left_member]["status"], "left")

    # ---- Мутирующие операции (teams.manage: approval-режим) ----------------------------

    def _assert_no_pending_approvals(self, admin_id: str) -> None:
        from app.models import AdminApprovalRequest

        with self.SessionLocal() as session:
            pending = session.scalars(
                select(AdminApprovalRequest).where(
                    AdminApprovalRequest.requested_by_admin_id == admin_id,
                    AdminApprovalRequest.status == "pending",
                )
            ).all()
        self.assertEqual(pending, [])

    def test_create_force_disband_approval_mode_404_for_unknown_team(self) -> None:
        admin = self._make_admin()
        self._grant(
            admin.id,
            TEAMS_MANAGE_PERMISSION,
            execution_mode=APPROVAL_EXECUTION_MODE,
        )

        with self.assertRaises(HTTPException) as caught:
            create_force_disband(
                team_id="team-does-not-exist",
                payload=ForceDisbandPayload(reason="test"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 404)

        self._assert_no_pending_approvals(admin.id)

    def test_create_force_kick_approval_mode_404_for_unknown_membership(self) -> None:
        admin = self._make_admin()
        self._grant(
            admin.id,
            TEAMS_MANAGE_PERMISSION,
            execution_mode=APPROVAL_EXECUTION_MODE,
        )

        leader = self._make_player()
        team_id = self._make_team(leader)

        with self.assertRaises(HTTPException) as caught:
            create_force_kick(
                team_id=team_id,
                player_id="player-does-not-exist",
                payload=ForceKickPayload(reason="test"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 404)

        self._assert_no_pending_approvals(admin.id)

    def test_execute_force_disband_replay_returns_idempotent_true(self) -> None:
        from app.models import AdminApprovalRequest

        admin = self._make_admin(super_admin=True)
        leader = self._make_player()
        team_id = self._make_team(leader)

        approval_id = f"admin-approval-{uuid.uuid4().hex[:8]}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminApprovalRequest(
                    id=approval_id,
                    status="executed",
                    action_type=ACTION_TYPE_FORCE_DISBAND,
                    target_entity_type="team",
                    target_entity_id=team_id,
                    payload_snapshot={},
                    reason="test",
                    requested_by_admin_id=admin.id,
                    required_permission_code=TEAMS_MANAGE_PERMISSION,
                    execution_result={},
                )
            )

        result = execute_force_disband(
            approval_id=approval_id,
            request=self._request(),
            admin=admin,
        )

        self.assertIs(result["idempotent"], True)
        self.assertNotIn("teamId", result)
        self.assertNotIn("disbanded", result)
        self.assertEqual(result["approval"]["status"], "executed")

        team = self._get_team(team_id)
        self.assertEqual(team.status, "active")

    def test_force_disband_direct_mode_disbands_team(self) -> None:
        admin = self._make_admin(super_admin=True)
        self._grant(
            admin.id,
            TEAMS_MANAGE_PERMISSION,
            execution_mode=DIRECT_EXECUTION_MODE,
        )

        leader_id = self._make_player()
        member_player_id = self._make_player()
        team_id = self._make_team(leader_id)
        self._add_member(team_id, member_player_id)

        result = create_force_disband(
            team_id=team_id,
            payload=ForceDisbandPayload(reason="test"),
            request=self._request(),
            admin=admin,
        )

        self.assertEqual(result["teamId"], team_id)
        self.assertIs(result["disbanded"], True)

        team = self._get_team(team_id)
        self.assertEqual(team.status, "disbanded")

        leader_membership = self._get_membership(team_id, leader_id)
        member_membership = self._get_membership(team_id, member_player_id)
        self.assertEqual(leader_membership.status, "left")
        self.assertEqual(member_membership.status, "left")

        history = self._get_history(team_id)
        self.assertEqual(len(history), 2)
        self.assertTrue(all(h.event_type == "disbanded" for h in history))

    def test_force_disband_direct_mode_409_when_active_team_session(self) -> None:
        admin = self._make_admin(super_admin=True)
        self._grant(
            admin.id,
            TEAMS_MANAGE_PERMISSION,
            execution_mode=DIRECT_EXECUTION_MODE,
        )

        leader_id = self._make_player()
        member_player_id = self._make_player()
        team_id = self._make_team(leader_id)
        self._add_member(team_id, member_player_id)
        self._create_active_session(member_player_id)

        with self.assertRaises(HTTPException) as caught:
            create_force_disband(
                team_id=team_id,
                payload=ForceDisbandPayload(reason="test"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)

        team = self._get_team(team_id)
        self.assertEqual(team.status, "active")

    def test_force_kick_direct_mode_kicks_member(self) -> None:
        admin = self._make_admin(super_admin=True)
        self._grant(
            admin.id,
            TEAMS_MANAGE_PERMISSION,
            execution_mode=DIRECT_EXECUTION_MODE,
        )

        leader_id = self._make_player()
        member_player_id = self._make_player()
        team_id = self._make_team(leader_id)
        self._add_member(team_id, member_player_id)

        result = create_force_kick(
            team_id=team_id,
            player_id=member_player_id,
            payload=ForceKickPayload(reason="test"),
            request=self._request(),
            admin=admin,
        )

        self.assertEqual(result["teamId"], team_id)
        self.assertEqual(result["playerId"], member_player_id)
        self.assertIs(result["kicked"], True)

        membership = self._get_membership(team_id, member_player_id)
        self.assertEqual(membership.status, "left")
        self.assertIsNotNone(membership.left_at)

        history = self._get_history(team_id)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].event_type, "kicked")
        self.assertEqual(history[0].metadata_json["via"], "admin")

    def test_force_kick_direct_mode_409_for_leader(self) -> None:
        admin = self._make_admin(super_admin=True)
        self._grant(
            admin.id,
            TEAMS_MANAGE_PERMISSION,
            execution_mode=DIRECT_EXECUTION_MODE,
        )

        leader_id = self._make_player()
        team_id = self._make_team(leader_id)

        with self.assertRaises(HTTPException) as caught:
            create_force_kick(
                team_id=team_id,
                player_id=leader_id,
                payload=ForceKickPayload(reason="test"),
                request=self._request(),
                admin=admin,
            )
        self.assertEqual(caught.exception.status_code, 409)

        membership = self._get_membership(team_id, leader_id)
        self.assertEqual(membership.status, "active")
