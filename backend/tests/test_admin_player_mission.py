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
    ACTION_TYPE_ATTEMPTS_ADJUST,
    ACTION_TYPE_CANCEL,
    ACTION_TYPE_FORCE_COMPLETE,
    FORCE_COMPLETE_THRESHOLD_KEY,
    PLAYERS_MANAGE_PERMISSION,
    MissionAttemptsAdjustPayload,
    MissionCancelPayload,
    MissionForceCompletePayload,
    create_player_mission_attempts_adjustment,
    create_player_mission_cancel,
    create_player_mission_force_complete,
    execute_player_mission_attempts_adjustment,
    execute_player_mission_cancel,
    execute_player_mission_force_complete,
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

    def first(self):
        return self._rows[0] if self._rows else None


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


def _reward(**overrides) -> SimpleNamespace:
    base = {
        "id": "reward-1",
        "mission_id": "mission-1",
        "reward_type": "currency",
        "amount": 100,
        "item_id": None,
        "story_node_id": None,
        "reward_value": {"currency": "ROOT"},
        "sort_order": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _wallet(**overrides) -> SimpleNamespace:
    base = {
        "id": "wallet-1",
        "player_id": "player-1",
        "currency": "ROOT",
        "available_balance": 1000,
        "locked_balance": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _threshold_setting(**overrides) -> SimpleNamespace:
    base = {
        "key": FORCE_COMPLETE_THRESHOLD_KEY,
        "status": "active",
        "value_json": 5000,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _audit_force_complete(**overrides) -> SimpleNamespace:
    base = {
        "id": "admin-audit-fc-1",
        "entity_type": "player_mission",
        "entity_id": "player-mission-1",
        "action": ACTION_TYPE_FORCE_COMPLETE,
        "request_id": "req-1",
        "outcome": "success",
        "metadata_json": {
            "awardedRoot": 0,
            "awardedItems": [],
            "awardedStoryNodeIds": [],
            "rewardSkipped": False,
            "entryConsumed": False,
        },
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _audit_attempts_adjust(**overrides) -> SimpleNamespace:
    base = {
        "id": "admin-audit-aa-1",
        "entity_type": "player_mission",
        "entity_id": "player-mission-1",
        "action": ACTION_TYPE_ATTEMPTS_ADJUST,
        "request_id": "req-attempts-1",
        "outcome": "success",
        "metadata_json": {"oldValue": 3, "newValue": 7},
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
            scalar_script=[pm],
            scalars_script=[[ent]],
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

    def test_invalidate_all_entitlements_for_mission(self) -> None:
        # Sprint 8.16: у миссии может быть несколько ключей-наград -> по одному
        # fallback-entitlement'у на каждый. Отмена с invalidate обязана выключить
        # ВСЕ записи (player, mission), а не только первую.
        ent_red = _entitlement(id="entitlement-red", item_id="item-red")
        ent_blue = _entitlement(id="entitlement-blue", item_id="item-blue")
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm],
            scalars_script=[[ent_red, ent_blue]],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._cancel(
            session,
            payload_extra={"invalidate_fallback_entitlement": True},
            audit_ctx=audit_ctx,
        )

        self.assertIs(result["entitlementInvalidated"], True)
        self.assertEqual(ent_red.status, "disabled")
        self.assertEqual(ent_blue.status, "disabled")
        # В магазине не осталось ни одного доступного оффера этой миссии.
        self.assertEqual(
            [e for e in (ent_red, ent_blue) if e.status == "available"], []
        )
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


class MissionForceCompletePayloadValidationTests(unittest.TestCase):
    """Pydantic-границы payload force-complete (422 на уровне валидации)."""

    def test_force_complete_reason_and_request_id_required(self) -> None:
        with self.assertRaises(ValidationError):
            MissionForceCompletePayload(request_id="req-1")
        with self.assertRaises(ValidationError):
            MissionForceCompletePayload(reason="Завершение")

    def test_force_complete_reason_max_length(self) -> None:
        with self.assertRaises(ValidationError):
            MissionForceCompletePayload(reason="x" * 4_001, request_id="req-1")

    def test_force_complete_request_id_max_length(self) -> None:
        with self.assertRaises(ValidationError):
            MissionForceCompletePayload(reason="Завершение", request_id="x" * 65)

    def test_force_complete_expires_at_naive_or_past_422(self) -> None:
        scripts = [
            datetime(2026, 10, 6, 12, 0),  # naive
            datetime.now(timezone.utc) - timedelta(days=1),  # past, tz-aware
        ]
        for expires_at in scripts:
            session = FakeSession(get_results={"GamePlayer:player-1": _player()})
            with _run_begin(session):
                with self.assertRaises(HTTPException) as caught:
                    create_player_mission_force_complete(
                        "player-1",
                        "mission-1",
                        MissionForceCompletePayload(
                            reason="Завершение",
                            request_id="req-1",
                            expires_at=expires_at,
                        ),
                        _request(),
                        _admin(),
                    )
            self.assertEqual(caught.exception.status_code, 422)


class ForceCompleteDirectExecutionTests(unittest.TestCase):
    """Прямое исполнение: статус -> completed, аудит, награды, guards."""

    def _force_complete(
        self, session, *, payload_extra=None, request_id="req-1", audit_ctx=None, admin=None
    ):
        payload = MissionForceCompletePayload(reason="Завершение", request_id=request_id)
        if payload_extra:
            payload = MissionForceCompletePayload(
                reason="Завершение", request_id=request_id, **payload_extra
            )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_mission.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch("app.admin_player_mission.write_admin_audit") as audit,
        ):
            try:
                result = create_player_mission_force_complete(
                    "player-1", "mission-1", payload, _request(), admin or _admin()
                )
            except HTTPException as exc:
                return exc
        if audit_ctx is not None:
            audit_ctx.append(audit)
        return result

    def test_force_complete_in_progress_sets_completed(self) -> None:
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm, None, _wallet()],
            scalars_script=[[], []],
            get_results={
                "GamePlayer:player-1": _player(),
                "Mission:mission-1": _mission(),
            },
        )
        audit_ctx: list = []
        result = self._force_complete(session, audit_ctx=audit_ctx)

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["playerMission"]["status"], "completed")
        self.assertIs(result["entryConsumed"], True)
        self.assertIs(result["rewardSkipped"], False)
        self.assertEqual(result["rewardOutcome"]["awardedRoot"], 0)
        self.assertEqual(pm.status, "completed")
        self.assertIsNotNone(pm.completed_at)

        audit = audit_ctx[0]
        self.assertEqual(audit.call_args.kwargs["action"], "player.mission_force_complete")
        self.assertEqual(audit.call_args.kwargs["entity_type"], "player_mission")
        self.assertEqual(audit.call_args.kwargs["entity_id"], "player-mission-1")
        self.assertEqual(audit.call_args.kwargs["request_id"], "req-1")
        self.assertEqual(audit.call_args.kwargs["before"]["status"], "in_progress")
        self.assertEqual(audit.call_args.kwargs["after"]["status"], "completed")
        self.assertIs(audit.call_args.kwargs["metadata"]["entryConsumed"], True)
        self.assertIs(audit.call_args.kwargs["metadata"]["rewardSkipped"], False)
        self.assertEqual(audit.call_args.kwargs["metadata"]["awardedRoot"], 0)

    def test_force_complete_available_sets_completed_and_starts(self) -> None:
        pm = _player_mission(status="available", attempt_count=0, started_at=None)
        session = FakeSession(
            scalar_script=[pm, None, _wallet()],
            scalars_script=[[], []],
            get_results={
                "GamePlayer:player-1": _player(),
                "Mission:mission-1": _mission(),
            },
        )
        audit_ctx: list = []
        result = self._force_complete(session, audit_ctx=audit_ctx)

        self.assertEqual(result["playerMission"]["status"], "completed")
        self.assertIs(result["entryConsumed"], False)
        # available-миссия ещё не начиналась: started_at выставляется.
        self.assertIsNotNone(getattr(pm, "started_at", None))
        audit = audit_ctx[0]
        self.assertIs(audit.call_args.kwargs["metadata"]["entryConsumed"], False)


    def test_force_complete_locked_sets_completed(self) -> None:
        pm = _player_mission(status="locked", attempt_count=0, started_at=None)
        session = FakeSession(
            scalar_script=[pm, None, _wallet()],
            scalars_script=[[], []],
            get_results={
                "GamePlayer:player-1": _player(),
                "Mission:mission-1": _mission(),
            },
        )
        result = self._force_complete(session)
        self.assertEqual(result["playerMission"]["status"], "completed")
        self.assertIs(result["entryConsumed"], False)

    def test_force_complete_award_rewards_false_marks_reward_skipped(self) -> None:
        pm = _player_mission()
        reward = _reward()
        session = FakeSession(
            scalar_script=[pm, None, reward],
            scalars_script=[[reward]],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._force_complete(
            session, payload_extra={"award_rewards": False}, audit_ctx=audit_ctx
        )

        self.assertIs(result["rewardSkipped"], True)
        self.assertEqual(result["rewardOutcome"]["awardedRoot"], 0)
        self.assertEqual(pm.status, "completed")
        audit = audit_ctx[0]
        self.assertIs(audit.call_args.kwargs["metadata"]["rewardSkipped"], True)

    def test_force_complete_award_rewards_false_no_rewards_no_skip(self) -> None:
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm, None, None],
            scalars_script=[[]],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._force_complete(session, payload_extra={"award_rewards": False})
        self.assertIs(result["rewardSkipped"], False)

    def test_force_complete_award_rewards_awards_root(self) -> None:
        pm = _player_mission()
        reward = _reward(amount=100)
        wallet = _wallet(available_balance=1000)
        session = FakeSession(
            scalar_script=[pm, None, wallet, None],
            scalars_script=[[reward], [reward]],
            get_results={
                "GamePlayer:player-1": _player(),
                "Mission:mission-1": _mission(slug="find-artifact"),
            },
        )
        audit_ctx: list = []
        result = self._force_complete(session, audit_ctx=audit_ctx)

        self.assertEqual(result["rewardOutcome"]["awardedRoot"], 100)
        self.assertEqual(wallet.available_balance, 1100)
        txs = [o for o in session.added if isinstance(o, WalletTransaction)]
        self.assertEqual(len(txs), 1)
        self.assertEqual(txs[0].reference_type, "mission_reward")
        self.assertEqual(txs[0].reference_id, "mission-1")
        audit = audit_ctx[0]
        self.assertEqual(audit.call_args.kwargs["metadata"]["awardedRoot"], 100)


    def test_force_complete_completed_same_request_id_idempotent(self) -> None:
        pm = _player_mission(
            status="completed",
            completed_at=datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc),
        )
        audit_log = _audit_force_complete()
        session = FakeSession(
            scalar_script=[pm, audit_log],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._force_complete(session, audit_ctx=audit_ctx)

        self.assertIs(result["idempotent"], True)
        self.assertEqual(result["playerMission"]["status"], "completed")
        self.assertIs(result["rewardSkipped"], False)
        self.assertIs(result["entryConsumed"], False)
        self.assertEqual(result["rewardOutcome"]["awardedRoot"], 0)
        audit_ctx[0].assert_not_called()

    def test_force_complete_completed_other_request_id_409(self) -> None:
        pm = _player_mission(status="completed")
        session = FakeSession(
            scalar_script=[pm, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._force_complete(session, request_id="req-other")
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_force_complete_cancelled_409(self) -> None:
        pm = _player_mission(status="cancelled")
        session = FakeSession(
            scalar_script=[pm, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._force_complete(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_force_complete_super_admin_direct_above_threshold(self) -> None:
        # super-admin не создаёт заявку даже при магнитуде >= порога.
        pm = _player_mission()
        reward = _reward(amount=5000)
        wallet = _wallet(available_balance=1000)
        session = FakeSession(
            scalar_script=[pm, _threshold_setting(), wallet, None],
            scalars_script=[[reward], [reward]],
            get_results={
                "GamePlayer:player-1": _player(),
                "Mission:mission-1": _mission(slug="find-artifact"),
            },
        )
        audit_ctx: list = []
        result = self._force_complete(
            session, admin=_admin(is_super_admin=True), audit_ctx=audit_ctx
        )

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["playerMission"]["status"], "completed")
        self.assertEqual(result["rewardOutcome"]["awardedRoot"], 5000)
        self.assertEqual(wallet.available_balance, 6000)
        self.assertEqual(
            len([o for o in session.added if isinstance(o, AdminApprovalRequest)]), 0
        )


class ForceCompleteApprovalFlowTests(unittest.TestCase):
    """Approval-путь: approval-грант, порог-магнитуда, idempotency заявки."""

    def _force_complete_approval(self, session, payload=None, admin=None):
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
            response = create_player_mission_force_complete(
                "player-1",
                "mission-1",
                payload
                or MissionForceCompletePayload(
                    reason="Завершение", request_id="req-1"
                ),
                _request(),
                admin or _admin(),
            )
        return response, audit

    def test_force_complete_approval_mode_creates_request(self) -> None:
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm, None, None],
            scalars_script=[[]],
            get_results={"GamePlayer:player-1": _player()},
        )
        response, audit = self._force_complete_approval(session)

        self.assertEqual(response.status_code, 201)
        self.assertIs(json.loads(response.body)["idempotent"], False)

        approvals = [o for o in session.added if isinstance(o, AdminApprovalRequest)]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].action_type, ACTION_TYPE_FORCE_COMPLETE)
        self.assertEqual(
            approvals[0].required_permission_code, PLAYERS_MANAGE_PERMISSION
        )
        self.assertEqual(approvals[0].request_id, "req-1")
        self.assertEqual(approvals[0].status, "pending")
        self.assertEqual(approvals[0].target_entity_type, "player_mission")
        self.assertEqual(approvals[0].target_entity_id, "player-mission-1")
        self.assertEqual(approvals[0].payload_snapshot["missionId"], "mission-1")
        self.assertIs(approvals[0].payload_snapshot["awardRewards"], True)
        self.assertEqual(
            audit.call_args.kwargs["action"], "admin_approval_request.created"
        )
        # Миссия не менялась: заявка — единственный побочный эффект.
        self.assertEqual(pm.status, "in_progress")


    def test_force_complete_magnitude_at_or_above_threshold_creates_request(self) -> None:
        # direct-grant, но магнитуда 5000 >= порога 5000 -> заявка.
        pm = _player_mission()
        reward = _reward(amount=5000)
        session = FakeSession(
            scalar_script=[pm, _threshold_setting(), None],
            scalars_script=[[reward]],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_mission.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch(
                "app.admin_player_mission._serialize_approval",
                side_effect=_fake_serialize_approval,
            ),
            patch("app.admin_player_mission.write_admin_audit") as audit,
        ):
            response = create_player_mission_force_complete(
                "player-1",
                "mission-1",
                MissionForceCompletePayload(reason="Завершение", request_id="req-1"),
                _request(),
                _admin(),
            )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(pm.status, "in_progress")
        approvals = [o for o in session.added if isinstance(o, AdminApprovalRequest)]
        self.assertEqual(len(approvals), 1)

    def test_force_complete_request_idempotent_replay(self) -> None:
        pm = _player_mission()
        existing = _approval(
            action_type=ACTION_TYPE_FORCE_COMPLETE,
            payload_snapshot={
                "playerId": "player-1",
                "missionId": "mission-1",
                "reason": "Завершение",
                "awardRewards": True,
            },
            reason="Завершение",
        )
        session = FakeSession(
            scalar_script=[pm, None, existing],
            scalars_script=[[]],
            get_results={"GamePlayer:player-1": _player()},
        )
        response, audit = self._force_complete_approval(session)

        self.assertEqual(response.status_code, 200)
        self.assertIs(json.loads(response.body)["idempotent"], True)
        self.assertEqual(
            len([o for o in session.added if isinstance(o, AdminApprovalRequest)]), 0
        )
        audit.assert_not_called()

    def test_force_complete_request_conflict_409(self) -> None:
        pm = _player_mission()
        existing = _approval(
            action_type=ACTION_TYPE_FORCE_COMPLETE,
            payload_snapshot={
                "playerId": "player-1",
                "missionId": "mission-1",
                "reason": "Другая причина",
                "awardRewards": True,
            },
            reason="Другая причина",
        )
        session = FakeSession(
            scalar_script=[pm, None, existing],
            scalars_script=[[]],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session), patch(
            "app.admin_player_mission.get_permission_execution_mode",
            return_value=APPROVAL_EXECUTION_MODE,
        ):
            with self.assertRaises(HTTPException) as caught:
                create_player_mission_force_complete(
                    "player-1",
                    "mission-1",
                    MissionForceCompletePayload(reason="Завершение", request_id="req-1"),
                    _request(),
                    _admin(),
                )
        self.assertEqual(caught.exception.status_code, 409)


class ForceCompleteExecuteApprovalTests(unittest.TestCase):
    """Dedicated executor: только super-admin, только player.mission_force_complete."""

    def test_force_complete_execute_approved_by_super_admin(self) -> None:
        approval = _approval(
            action_type=ACTION_TYPE_FORCE_COMPLETE,
            payload_snapshot={
                "playerId": "player-1",
                "missionId": "mission-1",
                "reason": "Завершение",
                "awardRewards": True,
            },
            reason="Завершение",
        )
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[approval, pm, _wallet()],
            scalars_script=[[]],
            get_results={
                "GamePlayer:player-1": _player(),
                "Mission:mission-1": _mission(slug="find-artifact"),
            },
        )
        with _run_begin(session), patch(
            "app.admin_player_mission.write_admin_audit"
        ) as audit:
            result = execute_player_mission_force_complete(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["playerMission"]["status"], "completed")
        self.assertIs(result["entryConsumed"], True)
        self.assertEqual(result["rewardOutcome"]["awardedRoot"], 0)
        self.assertEqual(pm.status, "completed")
        self.assertEqual(approval.status, "executed")
        self.assertEqual(approval.executed_by_admin_id, "admin-1")

        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertIn("player.mission_force_complete.via_approval", actions)
        self.assertIn("admin_approval_request.executed", actions)

    def test_force_complete_execute_wrong_action_422(self) -> None:
        approval = _approval(action_type=ACTION_TYPE_CANCEL)
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                execute_player_mission_force_complete(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 422)


class AttemptsAdjustDirectTests(unittest.TestCase):
    """5.6.c direct: абсолютная установка attempt_count, аудит, терминальные."""

    def _adjust(
        self, session, *, new_attempt_count=7, request_id="req-attempts-1",
        audit_ctx=None,
    ):
        payload = MissionAttemptsAdjustPayload(
            new_attempt_count=new_attempt_count,
            reason="Корректировка попыток",
            request_id=request_id,
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_mission.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch("app.admin_player_mission.write_admin_audit") as audit,
        ):
            try:
                result = create_player_mission_attempts_adjustment(
                    "player-1", "mission-1", payload, _request(), _admin()
                )
            except HTTPException as exc:
                return exc
        if audit_ctx is not None:
            audit_ctx.append(audit)
        return result

    def test_attempts_adjust_direct_changes_count_and_audits(self) -> None:
        pm = _player_mission(attempt_count=3)
        session = FakeSession(
            scalar_script=[pm],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._adjust(session, audit_ctx=audit_ctx)

        self.assertIs(result["idempotent"], False)
        self.assertIs(result["changed"], True)
        self.assertEqual(result["playerMission"]["attemptCount"], 7)
        self.assertEqual(pm.attempt_count, 7)

        audit = audit_ctx[0]
        self.assertEqual(
            audit.call_args.kwargs["action"], "player.mission_attempts_adjust"
        )
        self.assertEqual(audit.call_args.kwargs["entity_type"], "player_mission")
        self.assertEqual(audit.call_args.kwargs["entity_id"], "player-mission-1")
        self.assertEqual(audit.call_args.kwargs["request_id"], "req-attempts-1")
        self.assertEqual(audit.call_args.kwargs["before"], {"attemptCount": 3})
        self.assertEqual(audit.call_args.kwargs["after"], {"attemptCount": 7})
        self.assertEqual(audit.call_args.kwargs["metadata"]["oldValue"], 3)
        self.assertEqual(audit.call_args.kwargs["metadata"]["newValue"], 7)
        self.assertIs(audit.call_args.kwargs["metadata"]["changed"], True)

    def test_attempts_adjust_direct_new_equals_old_changed_false(self) -> None:
        pm = _player_mission(attempt_count=7)
        session = FakeSession(
            scalar_script=[pm],
            get_results={"GamePlayer:player-1": _player()},
        )
        audit_ctx: list = []
        result = self._adjust(session, new_attempt_count=7, audit_ctx=audit_ctx)

        self.assertIs(result["changed"], False)
        self.assertEqual(pm.attempt_count, 7)
        audit = audit_ctx[0]
        self.assertIs(audit.call_args.kwargs["metadata"]["changed"], False)
        self.assertEqual(audit.call_args.kwargs["before"], {"attemptCount": 7})
        self.assertEqual(audit.call_args.kwargs["after"], {"attemptCount": 7})

    def test_attempts_adjust_direct_terminal_409_without_replay(self) -> None:
        pm = _player_mission(status="completed", attempt_count=3)
        session = FakeSession(
            scalar_script=[pm, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._adjust(session)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_attempts_adjust_direct_terminal_replay_idempotent_200(self) -> None:
        pm = _player_mission(status="completed", attempt_count=7)
        audit = _audit_attempts_adjust(
            metadata_json={"oldValue": 3, "newValue": 7}
        )
        session = FakeSession(
            scalar_script=[pm, audit],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._adjust(session)
        self.assertIs(result["idempotent"], True)
        self.assertEqual(result["playerMission"]["attemptCount"], 7)
        self.assertIs(result["changed"], True)
        # Состояние не перезаписывается: status/started_at не трогаем.
        self.assertEqual(pm.status, "completed")

    def test_attempts_adjust_payload_bounds(self) -> None:
        MissionAttemptsAdjustPayload(
            new_attempt_count=0, reason="обнуление", request_id="req-1"
        )
        MissionAttemptsAdjustPayload(
            new_attempt_count=1000, reason="кап", request_id="req-1"
        )
        for bad in (-1, 1001):
            with self.assertRaises(ValidationError):
                MissionAttemptsAdjustPayload(
                    new_attempt_count=bad, reason="вне границ", request_id="req-1"
                )
        with self.assertRaises(ValidationError):
            MissionAttemptsAdjustPayload(reason="нет счётчика", request_id="req-1")


class AttemptsAdjustApprovalRequestTests(unittest.TestCase):
    """5.6.c approval-грант: заявка 201 + идемпотентный replay 200."""

    def _adjust_approval(self, session, request_id="req-attempts-1"):
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
            response = create_player_mission_attempts_adjustment(
                "player-1",
                "mission-1",
                MissionAttemptsAdjustPayload(
                    new_attempt_count=7,
                    reason="Корректировка",
                    request_id=request_id,
                ),
                _request(),
                _admin(),
            )
        return response, audit

    def test_attempts_adjust_approval_mode_creates_request_201(self) -> None:
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        response, audit = self._adjust_approval(session)

        self.assertEqual(response.status_code, 201)
        self.assertIs(json.loads(response.body)["idempotent"], False)

        approvals = [o for o in session.added if isinstance(o, AdminApprovalRequest)]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].action_type, ACTION_TYPE_ATTEMPTS_ADJUST)
        self.assertEqual(
            approvals[0].required_permission_code, PLAYERS_MANAGE_PERMISSION
        )
        self.assertEqual(approvals[0].request_id, "req-attempts-1")
        self.assertEqual(approvals[0].status, "pending")
        self.assertEqual(approvals[0].target_entity_type, "player_mission")
        self.assertEqual(approvals[0].target_entity_id, "player-mission-1")
        self.assertEqual(approvals[0].payload_snapshot["newAttemptCount"], 7)
        self.assertEqual(approvals[0].payload_snapshot["playerId"], "player-1")
        self.assertEqual(approvals[0].payload_snapshot["missionId"], "mission-1")
        self.assertEqual(
            audit.call_args.kwargs["action"], "admin_approval_request.created"
        )

    def test_attempts_adjust_approval_mode_reuses_request_200(self) -> None:
        existing = _approval(
            action_type=ACTION_TYPE_ATTEMPTS_ADJUST,
            payload_snapshot={
                "playerId": "player-1",
                "missionId": "mission-1",
                "newAttemptCount": 7,
                "reason": "Корректировка",
            },
            reason="Корректировка",
        )
        pm = _player_mission()
        session = FakeSession(
            scalar_script=[pm, existing],
            get_results={"GamePlayer:player-1": _player()},
        )
        response, audit = self._adjust_approval(session)

        self.assertEqual(response.status_code, 200)
        self.assertIs(json.loads(response.body)["idempotent"], True)
        self.assertEqual(
            len([o for o in session.added if isinstance(o, AdminApprovalRequest)]), 0
        )
        audit.assert_not_called()


class AttemptsAdjustExecuteApprovalTests(unittest.TestCase):
    """5.6.c executor: только super-admin, только attempts_adjust-заявки."""

    def _approval_for_execute(self, **overrides):
        return _approval(
            action_type=ACTION_TYPE_ATTEMPTS_ADJUST,
            payload_snapshot={
                "playerId": "player-1",
                "missionId": "mission-1",
                "newAttemptCount": 7,
                "reason": "Корректировка",
            },
            reason="Корректировка",
            request_id="req-attempts-1",
            **overrides,
        )

    def test_attempts_adjust_execute_happy_path_applies_and_audits(self) -> None:
        approval = self._approval_for_execute()
        pm = _player_mission(attempt_count=3)
        session = FakeSession(
            scalar_script=[approval, pm],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session), patch(
            "app.admin_player_mission.write_admin_audit"
        ) as audit:
            result = execute_player_mission_attempts_adjustment(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        self.assertIs(result["idempotent"], False)
        self.assertIs(result["changed"], True)
        self.assertEqual(result["playerMission"]["attemptCount"], 7)
        self.assertEqual(pm.attempt_count, 7)
        self.assertEqual(approval.status, "executed")
        self.assertEqual(approval.executed_by_admin_id, "admin-1")
        self.assertIsNotNone(approval.executed_at)
        self.assertEqual(approval.execution_result["attemptCount"], 7)

        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertIn(ACTION_TYPE_ATTEMPTS_ADJUST + ".via_approval", actions)
        self.assertIn("admin_approval_request.executed", actions)

    def test_attempts_adjust_execute_wrong_action_422(self) -> None:
        approval = _approval(action_type=ACTION_TYPE_CANCEL)
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                execute_player_mission_attempts_adjustment(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 422)

    def test_attempts_adjust_execute_pending_409(self) -> None:
        approval = self._approval_for_execute(status="pending")
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                execute_player_mission_attempts_adjustment(
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
                [pm],       # pre-read PlayerMission в _submit_mission_once (перед sync)
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