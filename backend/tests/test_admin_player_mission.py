"""Unit-тесты админ-отмены миссий игрока (шаг 5.6.a).

Unit-style: fake-объекты (SimpleNamespace) + FakeSession вместо TestClient
и БД. Endpoint-функции вызываются напрямую с явным admin/request;
SessionLocal, get_permission_execution_mode и write_admin_audit замоканы.
Guards движка миссий проверяются через fake-сессию напрямую
(_synchronize_player_missions / _submit_mission_once).
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.admin_access import APPROVAL_EXECUTION_MODE, DIRECT_EXECUTION_MODE
from app.admin_player_mission import (
    ACTION_TYPE_CANCEL,
    PLAYERS_MANAGE_PERMISSION,
    MissionCancelPayload,
    create_player_mission_cancel,
    execute_player_mission_cancel,
)
from app.mission_engine import (
    MissionEngineError,
    _submit_mission_once,
    _synchronize_player_missions,
)
from app.models import AdminApprovalRequest, InventoryEvent, WalletTransaction


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


def _player_mission(**overrides) -> SimpleNamespace:
    base = {
        "id": "player-mission-1",
        "player_id": "player-1",
        "mission_id": "mission-1",
        "status": "in_progress",
        "attempt_count": 1,
        "progress": {},
        "started_at": datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc),
        "completed_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _mission(**overrides) -> SimpleNamespace:
    base = {
        "id": "mission-1",
        "title": "Найди артефакт",
        "status": "published",
        "mission_type": "solo",
        "sort_order": 1,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _entitlement(**overrides) -> SimpleNamespace:
    base = {
        "id": "entitlement-1",
        "player_id": "player-1",
        "mission_id": "mission-1",
        "offer_id": "offer-1",
        "quota_limit": 3,
        "consumed_count": 0,
        "status": "available",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _audit_cancel(**overrides) -> SimpleNamespace:
    base = {
        "id": "admin-audit-1",
        "entity_type": "player_mission",
        "entity_id": "player-mission-1",
        "action": ACTION_TYPE_CANCEL,
        "request_id": "req-1",
        "outcome": "success",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _approval(**overrides) -> SimpleNamespace:
    base = {
        "id": "approval-1",
        "status": "approved",
        "requested_by_admin_id": "admin-1",
        "required_permission_code": PLAYERS_MANAGE_PERMISSION,
        "action_type": ACTION_TYPE_CANCEL,
        "target_entity_type": "player_mission",
        "target_entity_id": "player-mission-1",
        "payload_snapshot": {
            "playerId": "player-1",
            "missionId": "mission-1",
            "reason": "Отмена",
            "invalidateFallbackEntitlement": False,
        },
        "reason": "Отмена",
        "request_ip_address": "203.0.113.7",
        "request_id": "req-1",
        "expires_at": None,
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


def _run_begin(fake_session):
    return patch(
        "app.admin_player_mission.SessionLocal",
        SimpleNamespace(begin=lambda: _Ctx(fake_session)),
    )


def _run_engine_begin(fake_session):
    return patch(
        "app.mission_engine.SessionLocal",
        SimpleNamespace(begin=lambda: _Ctx(fake_session)),
    )


def _fake_serialize_approval(approval):
    return {"id": approval.id, "status": getattr(approval, "status", None)}

class MissionCancelPayloadValidationTests(unittest.TestCase):
    """Pydantic-границы payload (422 на уровне валидации)."""

    def test_reason_and_request_id_required(self) -> None:
        with self.assertRaises(ValidationError):
            MissionCancelPayload(request_id="req-1")
        with self.assertRaises(ValidationError):
            MissionCancelPayload(reason="Отмена")

    def test_reason_max_length(self) -> None:
        with self.assertRaises(ValidationError):
            MissionCancelPayload(reason="x" * 4_001, request_id="req-1")

    def test_request_id_max_length(self) -> None:
        with self.assertRaises(ValidationError):
            MissionCancelPayload(reason="Отмена", request_id="x" * 65)

    def test_whitespace_only_reason_422(self) -> None:
        # min_length=1 проходит pydantic; ловится _normalize_required -> 422.
        with _run_begin(FakeSession(get_results={"GamePlayer:player-1": _player()})):
            with self.assertRaises(HTTPException) as caught:
                create_player_mission_cancel(
                    "player-1",
                    "mission-1",
                    MissionCancelPayload(reason="   ", request_id="req-1"),
                    _request(),
                    _admin(),
                )
        self.assertEqual(caught.exception.status_code, 422)

    def test_expires_at_naive_or_past_422(self) -> None:
        scripts = [
            datetime(2026, 10, 6, 12, 0),  # naive
            datetime.now(timezone.utc) - timedelta(days=1),  # past, tz-aware
        ]
        for expires_at in scripts:
            session = FakeSession(get_results={"GamePlayer:player-1": _player()})
            with _run_begin(session):
                with self.assertRaises(HTTPException) as caught:
                    create_player_mission_cancel(
                        "player-1",
                        "mission-1",
                        MissionCancelPayload(
                            reason="Отмена", request_id="req-1", expires_at=expires_at
                        ),
                        _request(),
                        _admin(),
                    )
            self.assertEqual(caught.exception.status_code, 422)


class DirectExecutionTests(unittest.TestCase):
    """Прямое исполнение: статус -> cancelled, аудит, guards, entitlement."""

    def _cancel(
        self, session, *, payload_extra=None, request_id="req-1", audit_ctx=None
    ):
        payload = MissionCancelPayload(reason="Отмена", request_id=request_id)
        if payload_extra:
            payload = MissionCancelPayload(reason="Отмена", request_id=request_id, **payload_extra)
        with (
            _run_begin(session),
            patch(
                "app.admin_player_mission.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch("app.admin_player_mission.write_admin_audit") as audit,
        ):
            try:
                result = create_player_mission_cancel(
                    "player-1", "mission-1", payload, _request(), _admin()
                )
            except HTTPException as exc:
                return exc
        if audit_ctx is not None:
            audit_ctx.append(audit)
        return result

    def test_cancel_in_progress_sets_cancelled_status(self) -> None:
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._cancel(session, audit_ctx=audit_ctx)

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["playerMission"]["status"], "cancelled")
        self.assertEqual(result["playerMission"]["attemptCount"], 1)
        self.assertEqual(pm.status, "cancelled")

        audit = audit_ctx[0]
        self.assertEqual(audit.call_args.kwargs["action"], "player.mission_cancel")
        self.assertEqual(audit.call_args.kwargs["entity_type"], "player_mission")
        self.assertEqual(audit.call_args.kwargs["entity_id"], "player-mission-1")
        self.assertEqual(audit.call_args.kwargs["request_id"], "req-1")
        self.assertEqual(audit.call_args.kwargs["before"]["status"], "in_progress")
        self.assertEqual(audit.call_args.kwargs["after"]["status"], "cancelled")
        self.assertIs(
            audit.call_args.kwargs["metadata"]["entitlementInvalidated"], False
        )
        self.assertEqual(session.scalar_script, [])

    def test_cancel_available_sets_cancelled_status(self) -> None:
        pm = _player_mission(status="available", attempt_count=0, started_at=None)
        session = FakeSession(
            scalar_script=[pm],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._cancel(session)
        self.assertEqual(result["playerMission"]["status"], "cancelled")
        self.assertIsNone(result["playerMission"]["startedAt"])

    def test_cancel_completed_returns_409(self) -> None:
        pm = _player_mission(status="completed")
        session = FakeSession(
            scalar_script=[pm, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._cancel(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_cancel_player_mission_not_found_404(self) -> None:
        session = FakeSession(
            scalar_script=[None],
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._cancel(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 404)

    def test_cancel_unknown_player_404(self) -> None:
        session = FakeSession(scalar_script=[], get_results={})
        exc = self._cancel(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 404)

    def test_cancel_cancelled_same_request_id_idempotent(self) -> None:
        pm = _player_mission(status="cancelled")
        session = FakeSession(
            scalar_script=[pm, _audit_cancel()],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._cancel(session, request_id="req-1", audit_ctx=audit_ctx)

        self.assertIs(result["idempotent"], True)
        self.assertEqual(result["playerMission"]["status"], "cancelled")
        # Replay не переприменяет операцию: новых аудит-записей нет.
        self.assertEqual(audit_ctx[0].call_count, 0)

    def test_cancel_cancelled_different_request_id_409(self) -> None:
        pm = _player_mission(status="cancelled")
        session = FakeSession(
            scalar_script=[pm, None],  # audit с этим request_id нет
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._cancel(session, request_id="req-other")
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_cancel_does_not_refund_resources(self) -> None:
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm],
            get_results={"GamePlayer:player-1": _player()},
        )
        self._cancel(session)
        # Вложенные ресурсы не возвращаются: никаких проводок/инвентаря.
        self.assertEqual(
            [o for o in session.added if isinstance(o, (WalletTransaction, InventoryEvent))],
            [],
        )
        self.assertEqual(pm.status, "cancelled")

    def test_cancel_with_invalidate_entitlement_disables_entitlement(self) -> None:
        ent = _entitlement()
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm, ent],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._cancel(
            session,
            payload_extra={"invalidate_fallback_entitlement": True},
            audit_ctx=audit_ctx,
        )

        self.assertIs(result["entitlementInvalidated"], True)
        self.assertEqual(ent.status, "disabled")
        audit = audit_ctx[0]
        self.assertIs(
            audit.call_args.kwargs["metadata"]["entitlementInvalidated"], True
        )

    def test_cancel_without_invalidate_keeps_entitlement(self) -> None:
        ent = _entitlement()
        pm = _player_mission()
        # Второй элемент очереди — sentinel: entitlement НЕ должен запрашиваться.
        session = FakeSession(
            scalar_script=[pm, "ENTITLEMENT_MUST_NOT_BE_QUERIED"],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._cancel(session)

        self.assertIs(result["entitlementInvalidated"], False)
        self.assertEqual(ent.status, "available")
        # Очередь scalar исчерпана ровно одним вызовом (только PlayerMission).
        self.assertEqual(session.scalar_script, ["ENTITLEMENT_MUST_NOT_BE_QUERIED"])

class ApprovalFlowTests(unittest.TestCase):
    """Approval-грант: создание заявки (201) и её идемпотентность."""

    def _cancel_approval(self, session, request_id="req-1", expires_at=None):
        with (
            _run_begin(session),
            patch(
                "app.admin_player_mission.get_permission_execution_mode",
                return_value=APPROVAL_EXECUTION_MODE,
            ),
            patch(
                "app.admin_player_mission._serialize_approval",
                side_effect=_fake_serialize_approval,
            ),
            patch("app.admin_player_mission.write_admin_audit") as audit,
        ):
            response = create_player_mission_cancel(
                "player-1",
                "mission-1",
                MissionCancelPayload(
                    reason="Отмена",
                    request_id=request_id,
                    expires_at=(expires_at or (datetime.now(timezone.utc) + timedelta(days=1))),
                    invalidate_fallback_entitlement=True,
                ),
                _request(),
                _admin(),
            )
        return response, audit

    def test_cancel_approval_mode_creates_request(self) -> None:
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        response, audit = self._cancel_approval(session)

        self.assertEqual(response.status_code, 201)
        self.assertIs(json.loads(response.body)["idempotent"], False)

        approvals = [o for o in session.added if isinstance(o, AdminApprovalRequest)]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].action_type, ACTION_TYPE_CANCEL)
        self.assertEqual(approvals[0].required_permission_code, PLAYERS_MANAGE_PERMISSION)
        self.assertEqual(approvals[0].request_id, "req-1")
        self.assertEqual(approvals[0].status, "pending")
        self.assertEqual(approvals[0].target_entity_type, "player_mission")
        self.assertEqual(approvals[0].target_entity_id, "player-mission-1")
        self.assertEqual(approvals[0].payload_snapshot["missionId"], "mission-1")
        self.assertIs(
            approvals[0].payload_snapshot["invalidateFallbackEntitlement"], True
        )
        self.assertEqual(audit.call_args.kwargs["action"], "admin_approval_request.created")
        # Миссия не менялась: заявка — единственный побочный эффект.
        self.assertEqual(pm.status, "in_progress")

    def test_cancel_approval_idempotent_same_request_id(self) -> None:
        pm = _player_mission()
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        existing = _approval(
            expires_at=expires_at,
            payload_snapshot={
                "playerId": "player-1",
                "missionId": "mission-1",
                "reason": "Отмена",
                "invalidateFallbackEntitlement": True,
            },
        )
        session = FakeSession(
            scalar_script=[pm, existing],
            get_results={"GamePlayer:player-1": _player()},
        )
        response, audit = self._cancel_approval(
            session, request_id="req-1", expires_at=expires_at
        )

        self.assertEqual(response.status_code, 200)
        self.assertIs(json.loads(response.body)["idempotent"], True)
        self.assertEqual(
            len([o for o in session.added if isinstance(o, AdminApprovalRequest)]), 0
        )

class ExecuteApprovalTests(unittest.TestCase):
    """Dedicated executor: только super-admin, только player.mission_cancel."""

    def test_execute_approval_by_super_admin(self) -> None:
        approval = _approval()
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[approval, pm],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session), patch(
            "app.admin_player_mission.write_admin_audit"
        ) as audit:
            result = execute_player_mission_cancel(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["playerMission"]["status"], "cancelled")
        self.assertEqual(approval.status, "executed")
        self.assertEqual(approval.executed_by_admin_id, "admin-1")
        self.assertIsNotNone(approval.executed_at)
        self.assertEqual(approval.execution_result["playerMissionId"], "player-mission-1")

        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertIn("player.mission_cancel.via_approval", actions)
        self.assertIn("admin_approval_request.executed", actions)

    def test_execute_wrong_action_type_422(self) -> None:
        approval = _approval(action_type="system_setting.change")
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                execute_player_mission_cancel(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 422)

    def test_execute_repeat_is_idempotent(self) -> None:
        approval = _approval(status="executed")
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session), patch(
            "app.admin_player_mission.write_admin_audit"
        ) as audit:
            result = execute_player_mission_cancel(
                "approval-1", _request(), _admin(is_super_admin=True)
            )
        self.assertIs(result["idempotent"], True)
        audit.assert_not_called()

    def test_execute_pending_409(self) -> None:
        pending = _approval(status="pending")
        session = FakeSession(
            scalar_script=[pending],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                execute_player_mission_cancel(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 409)


class EngineGuardTests(unittest.TestCase):
    """Guards движка: синхронизация не реактивирует, сабмит отражает отмену."""

    def test_synchronize_player_missions_skips_cancelled(self) -> None:
        mission = _mission()
        pm = _player_mission(status="cancelled", attempt_count=3)
        session = FakeSession(
            scalars_script=[
                [mission],  # published Mission
                [],         # MissionRequirement
                [pm],       # PlayerMission rows
            ]
        )
        with _run_engine_begin(session):
            progress = _synchronize_player_missions(session, "player-1")

        self.assertEqual(progress["mission-1"].status, "cancelled")
        self.assertEqual(progress["mission-1"].attempt_count, 3)

    def test_submit_mission_after_cancel_returns_409(self) -> None:
        mission = _mission()
        pm = _player_mission(status="cancelled")
        session = FakeSession(
            scalar_script=[mission],  # Mission (published, solo)
            scalars_script=[
                [mission],  # published Mission inside synchronize
                [],         # MissionRequirement
                [pm],       # PlayerMission rows
            ],
            get_results={"GamePlayer:player-1": _player(status="active")},
        )
        with _run_engine_begin(session):
            with self.assertRaises(MissionEngineError) as caught:
                _submit_mission_once("player-1", "mission-1")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertIn("отменена", caught.exception.detail)
        # Сабмит не трогает отменённую миссию.
        self.assertEqual(pm.status, "cancelled")


if __name__ == "__main__":
    unittest.main()