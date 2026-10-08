"""Unit-тесты админ-ограничений игрока (шаг 5.7).

Unit-style: fake-объекты (SimpleNamespace) + FakeSession для endpoint-функций
(SessionLocal, get_permission_execution_mode и write_admin_audit замоканы;
recompute_player_status НЕ мокается — write-through идёт настоящим кодом).
Дополнительно — реальный SQLite (alembic): кэш GamePlayer.status, lazy-expiry
просроченных ограничений и lazy-рикавери гейтов (get_current_player_id,
mission_engine._ensure_player) end-to-end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_access import APPROVAL_EXECUTION_MODE, DIRECT_EXECUTION_MODE
from app.admin_player_restrictions import (
    ACTION_TYPE_RESTRICTION_CREATE,
    ACTION_TYPE_RESTRICTION_REVOKE,
    PLAYERS_BLOCK_PERMISSION,
    PLAYERS_RESTRICT_PERMISSION,
    RestrictionPayload,
    RestrictionRevokePayload,
    create_player_restriction,
    execute_player_restriction_create,
    execute_player_restriction_revoke,
    revoke_player_restriction,
)
from app.player_restrictions_engine import recompute_player_status

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class _Ctx:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


class _ScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class FakeSession:
    """Минимальная фейк-сессия: очередь scalar/scalars + запись add/flush."""

    def __init__(self, scalar_script=None, scalars_script=None, get_results=None):
        self.scalar_script = list(scalar_script or [])
        self.scalars_script = list(scalars_script or [])
        self.get_results = dict(get_results or {})
        self.added: list = []
        self.flushed: list = []

    def get(self, model, pk):
        for obj in self.added:
            if getattr(obj, "id", None) == pk:
                return obj
        model_name = getattr(model, "__name__", str(model))
        return self.get_results.get(f"{model_name}:{pk}")

    def scalar(self, _stmt):
        if not self.scalar_script:
            raise AssertionError("scalar() вызван без запланированного результата")
        return self.scalar_script.pop(0)

    def scalars(self, _stmt):
        if not self.scalars_script:
            raise AssertionError("scalars() вызван без запланированного результата")
        return _ScalarsResult(self.scalars_script.pop(0))

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed.append(list(self.added))


def _run_begin(fake_session):
    return patch(
        "app.admin_player_restrictions.SessionLocal",
        SimpleNamespace(begin=lambda: _Ctx(fake_session)),
    )


def _body_json(response) -> dict:
    return json.loads(response.body.decode())


def _request() -> SimpleNamespace:
    return SimpleNamespace(
        client=SimpleNamespace(host="203.0.113.7"),
        headers={},
        state=SimpleNamespace(),
    )


def _admin(**overrides) -> SimpleNamespace:
    base = {
        "id": "admin-1",
        "username": "operator",
        "is_super_admin": False,
        "permissions": [],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _player(**overrides) -> SimpleNamespace:
    base = {
        "id": "player-1",
        "display_name": "Иван Петров",
        "status": "active",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _restriction(**overrides) -> SimpleNamespace:
    base = {
        "id": "player-restriction-1",
        "player_id": "player-1",
        "restriction_type": "suspended",
        "status": "active",
        "reason": "Нарушение правил",
        "evidence": None,
        "admin_id": "admin-1",
        "starts_at": None,
        "expires_at": None,
        "approval_request_id": None,
        "revoked_by_admin_id": None,
        "revoked_at": None,
        "revocation_reason": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _audit_create(**overrides) -> SimpleNamespace:
    base = {
        "id": "admin-audit-1",
        "entity_type": "player_restriction",
        "entity_id": "player-restriction-1",
        "action": ACTION_TYPE_RESTRICTION_CREATE,
        "request_id": "req-1",
        "outcome": "success",
        "created_at": datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _audit_revoke(**overrides) -> SimpleNamespace:
    base = {
        "id": "admin-audit-rv-1",
        "entity_type": "player_restriction",
        "entity_id": "player-restriction-1",
        "action": ACTION_TYPE_RESTRICTION_REVOKE,
        "request_id": "req-revoke-1",
        "outcome": "success",
        "created_at": datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _approval(**overrides) -> SimpleNamespace:
    base = {
        "id": "approval-1",
        "status": "approved",
        "requested_by_admin_id": "admin-1",
        "required_permission_code": PLAYERS_RESTRICT_PERMISSION,
        "action_type": ACTION_TYPE_RESTRICTION_CREATE,
        "target_entity_type": "player_restriction",
        "target_entity_id": None,
        "payload_snapshot": {
            "playerId": "player-1",
            "restrictionType": "suspended",
            "reason": "Нарушение правил",
            "startsAt": None,
            "expiresAt": None,
            "evidence": None,
        },
        "reason": "Нарушение правил",
        "request_id": "req-1",
        "expires_at": None,
        "request_ip_address": "203.0.113.7",
        "approved_by_admin_id": "admin-2",
        "approved_at": datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        "approval_comment": None,
        "rejected_by_admin_id": None,
        "rejected_at": None,
        "rejection_comment": None,
        "cancelled_by_admin_id": None,
        "cancelled_at": None,
        "cancellation_reason": None,
        "executed_by_admin_id": None,
        "executed_at": None,
        "execution_result": {},
        "execution_error": None,
        "created_at": datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc),
        "updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class RestrictionPayloadValidationTests(unittest.TestCase):
    """Pydantic-границы payload и 422-ошибки до обращения к БД."""

    def test_payload_requires_reason_and_request_id(self) -> None:
        with self.assertRaises(ValidationError):
            RestrictionPayload(restriction_type="suspended", request_id="req-1")
        with self.assertRaises(ValidationError):
            RestrictionPayload(restriction_type="suspended", reason="Нарушение")
        with self.assertRaises(ValidationError):
            RestrictionPayload(reason="Нарушение", request_id="req-1")

    def test_unknown_restriction_type_422(self) -> None:
        session = FakeSession(get_results={"GamePlayer:player-1": _player()})
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                create_player_restriction(
                    "player-1",
                    RestrictionPayload(
                        restriction_type="pinned", reason="X", request_id="req-1"
                    ),
                    _request(),
                    _admin(is_super_admin=True),
                )
        self.assertEqual(caught.exception.status_code, 422)

    def test_expires_at_naive_422(self) -> None:
        session = FakeSession(get_results={"GamePlayer:player-1": _player()})
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                create_player_restriction(
                    "player-1",
                    RestrictionPayload(
                        restriction_type="suspended",
                        reason="X",
                        request_id="req-1",
                        expires_at=datetime(2026, 10, 8, 12, 0),
                    ),
                    _request(),
                    _admin(is_super_admin=True),
                )
        self.assertEqual(caught.exception.status_code, 422)


class CreateRestrictionDirectTests(unittest.TestCase):
    """Прямое исполнение создания ограничения (write-through статуса)."""

    def _create(
        self,
        session,
        *,
        restriction_type="suspended",
        request_id="req-1",
        payload_extra=None,
        permission=DIRECT_EXECUTION_MODE,
        admin=None,
        audit_ctx=None,
    ):
        kwargs = {
            "restriction_type": restriction_type,
            "reason": "Нарушение правил",
            "request_id": request_id,
        }
        if payload_extra:
            kwargs.update(payload_extra)
        payload = RestrictionPayload(**kwargs)
        with (
            _run_begin(session),
            patch(
                "app.admin_player_restrictions.get_permission_execution_mode",
                return_value=permission,
            ),
            patch("app.admin_player_restrictions.write_admin_audit") as audit,
        ):
            try:
                result = create_player_restriction(
                    "player-1", payload, _request(), admin or _admin()
                )
            except HTTPException as exc:
                return exc
        if audit_ctx is not None:
            audit_ctx.append(audit)
        return result

    def test_create_suspended_syncs_player_status_and_uses_players_block(self) -> None:
        new_restriction = _restriction()
        session = FakeSession(
            scalar_script=[None],  # replay: нет исторической записи
            scalars_script=[
                [],  # нет активного дубля типа
                [new_restriction],  # после add: ограничение видно recompute
            ],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._create(session, audit_ctx=audit_ctx)

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["playerStatus"], "suspended")
        self.assertIs(result["playerStatusChanged"], True)
        self.assertEqual(result["restriction"]["restrictionType"], "suspended")
        self.assertEqual(result["restriction"]["status"], "active")

        added = session.added[0]
        self.assertEqual(added.player_id, "player-1")
        self.assertEqual(added.admin_id, "admin-1")

        audit = audit_ctx[0]
        self.assertEqual(audit.call_args.kwargs["action"], "player.restriction_create")
        self.assertEqual(audit.call_args.kwargs["entity_type"], "player_restriction")
        self.assertEqual(
            audit.call_args.kwargs["permission_code"], PLAYERS_BLOCK_PERMISSION
        )
        self.assertEqual(audit.call_args.kwargs["request_id"], "req-1")
        self.assertIs(audit.call_args.kwargs["metadata"]["playerStatusChanged"], True)

    def test_create_chat_restricted_keeps_active_and_uses_players_restrict(self) -> None:
        new_restriction = _restriction(restriction_type="chat_restricted")
        session = FakeSession(
            scalar_script=[None],
            scalars_script=[[], [new_restriction]],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._create(
            session, restriction_type="chat_restricted", audit_ctx=audit_ctx
        )

        self.assertEqual(result["playerStatus"], "active")
        self.assertIs(result["playerStatusChanged"], False)
        self.assertEqual(
            audit_ctx[0].call_args.kwargs["permission_code"],
            PLAYERS_RESTRICT_PERMISSION,
        )

    def test_create_player_not_found_404(self) -> None:
        session = FakeSession(get_results={})
        exc = self._create(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 404)

    def test_create_missing_permission_403(self) -> None:
        session = FakeSession(get_results={"GamePlayer:player-1": _player()})
        exc = self._create(session, permission=None)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 403)

    def test_create_duplicate_active_type_409(self) -> None:
        existing = _restriction()
        session = FakeSession(
            scalar_script=[None],
            scalars_script=[[existing]],  # активный дубль suspended
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._create(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_create_idempotent_replay_200(self) -> None:
        created = _restriction(restriction_type="suspended")
        session = FakeSession(
            scalar_script=[_audit_create()],
            scalars_script=[],
            get_results={
                "GamePlayer:player-1": _player(),
                "PlayerRestriction:player-restriction-1": created,
            },
        )
        result = self._create(session)
        self.assertIs(result["idempotent"], True)
        self.assertEqual(result["restriction"]["id"], "player-restriction-1")


class CreateRestrictionApprovalTests(unittest.TestCase):
    """Approval-ветка создания ограничения -> 201 заявка."""

    def test_create_approval_mode_creates_request_201(self) -> None:
        session = FakeSession(
            scalar_script=[
                None,  # replay: нет исторической записи
                None,  # existing AdminApprovalRequest: нет
            ],
            scalars_script=[[]],  # нет активного дубля типа
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_restrictions.get_permission_execution_mode",
                return_value=APPROVAL_EXECUTION_MODE,
            ),
            patch("app.admin_player_restrictions.write_admin_audit") as audit,
        ):
            response = create_player_restriction(
                "player-1",
                RestrictionPayload(
                    restriction_type="blocked", reason="Нарушение", request_id="req-1"
                ),
                _request(),
                _admin(),
            )

        self.assertEqual(response.status_code, 201)
        body = response.body.decode()
        self.assertIn("approval", body)
        # Заявка несёт permission от типа ограничения (blocked -> players.block).
        approval = _body_json(response)["approval"]
        self.assertEqual(approval["requiredPermissionCode"], PLAYERS_BLOCK_PERMISSION)
        self.assertEqual(approval["actionType"], "player.restriction_create")
        self.assertEqual(
            approval["payloadSnapshot"]["restrictionType"], "blocked"
        )
        created_audit = [c for c in audit.call_args_list]
        actions = {c.kwargs["action"] for c in created_audit}
        self.assertIn("admin_approval_request.created", actions)


class ExecuteRestrictionCreateTests(unittest.TestCase):
    """Dedicated executor создания ограничения (только супер-админ)."""

    def test_execute_create_approval_success(self) -> None:
        new_restriction = _restriction()
        approval = _approval()  # status=approved, action=restriction_create
        session = FakeSession(
            scalar_script=[
                approval,
                None,  # replay: решений по request_id нет
            ],
            scalars_script=[
                [],  # нет активного дубля
                [new_restriction],  # после apply: recompute видит ограничение
            ],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session),
            patch("app.admin_player_restrictions.write_admin_audit"),
        ):
            result = execute_player_restriction_create(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        self.assertIs(result["approval"]["status"], "executed")
        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["restriction"]["restrictionType"], "suspended")
        self.assertEqual(result["restriction"]["status"], "active")
        self.assertEqual(result["playerStatus"], "suspended")
        # Применялась via_approval ветка (аудит расширен суффиксом).
        self.assertEqual(approval.status, "executed")

    def test_execute_create_wrong_action_422(self) -> None:
        approval = _approval(action_type=ACTION_TYPE_RESTRICTION_REVOKE)
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                execute_player_restriction_create(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 422)


class RevokeRestrictionTests(unittest.TestCase):
    """Снятие ограничения: direct, 409, replay и approval-ветка."""

    def _revoke(
        self,
        session,
        *,
        request_id="req-revoke-1",
        permission=DIRECT_EXECUTION_MODE,
        audit_ctx=None,
    ):
        payload = RestrictionRevokePayload(
            reason="Снятие ограничения", request_id=request_id
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_restrictions.get_permission_execution_mode",
                return_value=permission,
            ),
            patch("app.admin_player_restrictions.write_admin_audit") as audit,
        ):
            try:
                result = revoke_player_restriction(
                    "player-1",
                    "player-restriction-1",
                    payload,
                    _request(),
                    _admin(),
                )
            except HTTPException as exc:
                return exc
        if audit_ctx is not None:
            audit_ctx.append(audit)
        return result

    def test_revoke_direct_restores_player_status(self) -> None:
        restriction = _restriction()
        session = FakeSession(
            scalar_script=[restriction],
            scalars_script=[[]],  # блокирующих ограничений не осталось
            get_results={"GamePlayer:player-1": _player(status="suspended")},
        )
        audit_ctx: list = []
        result = self._revoke(session, audit_ctx=audit_ctx)

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["restriction"]["status"], "revoked")
        self.assertEqual(result["playerStatus"], "active")
        self.assertIs(result["playerStatusChanged"], True)
        self.assertEqual(restriction.revocation_reason, "Снятие ограничения")
        self.assertEqual(restriction.revoked_by_admin_id, "admin-1")

        audit = audit_ctx[0]
        self.assertEqual(audit.call_args.kwargs["action"], "player.restriction_revoke")
        self.assertEqual(
            audit.call_args.kwargs["permission_code"], PLAYERS_BLOCK_PERMISSION
        )

    def test_revoke_inactive_other_request_409(self) -> None:
        restriction = _restriction(status="revoked")
        session = FakeSession(
            scalar_script=[restriction, None],  # replay audit: нет
            get_results={"GamePlayer:player-1": _player(status="active")},
        )
        exc = self._revoke(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_revoke_idempotent_replay_200(self) -> None:
        restriction = _restriction(status="revoked", revoked_by_admin_id="admin-1")
        session = FakeSession(
            scalar_script=[restriction, _audit_revoke()],
            get_results={"GamePlayer:player-1": _player(status="active")},
        )
        result = self._revoke(session)
        self.assertIs(result["idempotent"], True)
        self.assertEqual(result["restriction"]["status"], "revoked")

    def test_revoke_approval_mode_creates_request_201(self) -> None:
        restriction = _restriction()
        session = FakeSession(
            scalar_script=[restriction, None],  # existing AdminApprovalRequest: нет
            get_results={"GamePlayer:player-1": _player(status="suspended")},
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_restrictions.get_permission_execution_mode",
                return_value=APPROVAL_EXECUTION_MODE,
            ),
            patch("app.admin_player_restrictions.write_admin_audit") as audit,
        ):
            response = revoke_player_restriction(
                "player-1",
                "player-restriction-1",
                RestrictionRevokePayload(reason="Снятие", request_id="req-revoke-1"),
                _request(),
                _admin(),
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            _body_json(response)["approval"]["actionType"],
            "player.restriction_revoke",
        )
        actions = {c.kwargs["action"] for c in audit.call_args_list}
        self.assertIn("admin_approval_request.created", actions)


class ExecuteRestrictionRevokeTests(unittest.TestCase):
    """Dedicated executor снятия ограничения (только супер-админ)."""

    def test_execute_revoke_inactive_to_execution_failed(self) -> None:
        approval = _approval(
            action_type=ACTION_TYPE_RESTRICTION_REVOKE,
            target_entity_id="player-restriction-1",
            payload_snapshot={
                "playerId": "player-1",
                "restrictionId": "player-restriction-1",
                "restrictionType": "suspended",
                "reason": "Снятие",
            },
            request_id="req-revoke-1",
        )
        restriction = _restriction(status="revoked")
        session = FakeSession(
            scalar_script=[
                approval,
                restriction,
                None,  # replay audit по request_id: нет -> execution_failed
            ],
            get_results={"GamePlayer:player-1": _player(status="active")},
        )
        with (
            _run_begin(session),
            patch("app.admin_player_restrictions.write_admin_audit"),
        ):
            response = execute_player_restriction_revoke(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        self.assertEqual(response.status_code, 409)
        body = _body_json(response)
        self.assertEqual(body["error"], "restriction_already_inactive")
        self.assertEqual(body["idempotent"], False)
        self.assertEqual(approval.status, "execution_failed")


class RestrictionEngineIntegrationTests(unittest.TestCase):
    """Real SQLite (alembic): кэш GamePlayer.status, lazy expiry, lazy recovery.

    End-to-end через настоящий движок ограничений: никакие тесты не мокают
    recompute_player_status — write-through и lazy-рикавери проверяются на
    реальной схеме.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-restriction-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "restrictions.sqlite3"
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

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _fixture(self) -> tuple[str, str]:
        from app.models import AdminUser, GamePlayer

        suffix = uuid.uuid4().hex
        player_id = f"player-{suffix}"
        admin_id = f"admin-{suffix}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="Test player",
                    auth_provider="demo",
                    status="active",
                )
            )
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"restriction-admin-{suffix}",
                    password_hash="not-a-real-hash",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                )
            )
        return player_id, admin_id

    def _add_restriction(
        self,
        player_id: str,
        admin_id: str,
        restriction_type: str,
        *,
        expires_at: datetime | None = None,
        status: str = "active",
    ) -> str:
        from app.models import PlayerRestriction

        restriction_id = f"player-restriction-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                PlayerRestriction(
                    id=restriction_id,
                    player_id=player_id,
                    restriction_type=restriction_type,
                    status=status,
                    reason="Integration fixture",
                    admin_id=admin_id,
                    starts_at=None,
                    expires_at=expires_at,
                )
            )
        return restriction_id

    def _set_player_status(self, player_id: str, status: str) -> None:
        from app.models import GamePlayer

        with self.SessionLocal.begin() as session:
            player = session.get(GamePlayer, player_id)
            player.status = status

    def test_recompute_blocked_precedence_and_transitions(self) -> None:
        from app.models import GamePlayer, PlayerRestriction

        player_id, admin_id = self._fixture()
        self._add_restriction(player_id, admin_id, "suspended")
        blocked_id = self._add_restriction(player_id, admin_id, "blocked")

        with self.SessionLocal.begin() as session:
            player = session.get(GamePlayer, player_id)
            self.assertEqual(recompute_player_status(session, player)[0], "blocked")

        with self.SessionLocal() as session:
            self.assertEqual(session.get(GamePlayer, player_id).status, "blocked")

        # Снятие blocked: suspension остаётся -> suspended.
        with self.SessionLocal.begin() as session:
            restriction = session.get(PlayerRestriction, blocked_id)
            restriction.status = "revoked"
            restriction.revoked_at = datetime.now(timezone.utc)
            restriction.revoked_by_admin_id = admin_id
            session.flush()
            player = session.get(GamePlayer, player_id)
            self.assertEqual(recompute_player_status(session, player)[0], "suspended")

        with self.SessionLocal() as session:
            self.assertEqual(session.get(GamePlayer, player_id).status, "suspended")

    def test_lazy_expiry_of_due_restriction_unblocks_player(self) -> None:
        from app.models import GamePlayer, PlayerRestriction

        player_id, admin_id = self._fixture()
        expired_id = self._add_restriction(
            player_id,
            admin_id,
            "suspended",
            expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        self._set_player_status(player_id, "suspended")  # устаревший кэш

        with self.SessionLocal.begin() as session:
            player = session.get(GamePlayer, player_id)
            status, changed = recompute_player_status(session, player)

        self.assertEqual(status, "active")
        self.assertIs(changed, True)
        with self.SessionLocal() as session:
            self.assertEqual(session.get(GamePlayer, player_id).status, "active")
            self.assertEqual(session.get(PlayerRestriction, expired_id).status, "expired")

    def test_mission_engine_lazy_recovery_restores_entry(self) -> None:
        from app.mission_engine import MissionEngineError, _ensure_player
        from app.models import GamePlayer

        player_id, admin_id = self._fixture()
        # Кэш устарел (гонка/ручная правка), активных ограничений нет —
        # вход восстанавливается lazy-рикавери.
        self._set_player_status(player_id, "blocked")

        with self.SessionLocal.begin() as session:
            player = _ensure_player(session, player_id)

        self.assertEqual(player.status, "active")
        with self.SessionLocal() as session:
            self.assertEqual(session.get(GamePlayer, player_id).status, "active")

        # Активный blocked по-прежнему запрещает вход.
        self._add_restriction(player_id, admin_id, "blocked")
        self._set_player_status(player_id, "blocked")
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as caught:
                _ensure_player(session, player_id)
        self.assertEqual(caught.exception.status_code, 403)

    def test_auth_gate_lazy_recovery_restores_entry(self) -> None:
        from app.config import settings
        from app.main import SESSION_COOKIE_NAME, get_current_player_id
        from app.models import GamePlayer
        from app.telegram_auth import create_session_token

        player_id, _admin_id = self._fixture()
        self._set_player_status(player_id, "suspended")

        token = create_session_token(
            player_id=player_id,
            session_secret=settings.game_session_secret,
            lifetime_seconds=3600,
        )
        request = SimpleNamespace(cookies={SESSION_COOKIE_NAME: token})

        import app.main as main_module

        with patch.object(main_module, "SessionLocal", self.SessionLocal):
            resolved = get_current_player_id(request)

        self.assertEqual(resolved, player_id)
        with self.SessionLocal() as session:
            self.assertEqual(session.get(GamePlayer, player_id).status, "active")