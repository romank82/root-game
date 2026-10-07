"""Unit-тесты ручных операций инвентаря (шаг 5.5).

Unit-style: fake-объекты (SimpleNamespace) + FakeSession вместо TestClient
и БД. Endpoint-функции вызываются напрямую с явным admin/request;
SessionLocal, get_permission_execution_mode и write_admin_audit замоканы.
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.admin_access import APPROVAL_EXECUTION_MODE, DIRECT_EXECUTION_MODE
from app.admin_player_inventory import (
    ACTION_TYPE_GRANT,
    ADMIN_GRANT_REFERENCE_TYPE,
    ADMIN_REVOKE_REFERENCE_TYPE,
    PLAYERS_MANAGE_PERMISSION,
    InventoryItemAdjustmentPayload,
    create_player_inventory_item_adjustment,
    execute_player_inventory_item_adjustment,
)
from app.models import AdminApprovalRequest, InventoryEvent


class _Ctx:
    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Минимальная фейк-сессия: очередь скалярных результатов + запись add/flush."""

    def __init__(self, scalar_script=None, get_results=None):
        self.scalar_script = list(scalar_script or [])
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

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flushed.append(list(self.added))


def _request() -> SimpleNamespace:
    # state обязателен: write_admin_audit читает request.state.audit_context
    # и без него фолбэчится на client.host + headers.
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


def _item(**overrides) -> SimpleNamespace:
    base = {
        "id": "item-key-1",
        "slug": "key-a01",
        "code": "key-a01",
        "title": "Ключ A01",
        "description": None,
        "symbol": None,
        "category": "key",
        "rarity": "common",
        "is_unique": True,
        "content": {},
        "status": "published",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _player_item(**overrides) -> SimpleNamespace:
    base = {
        "id": "player-item-1",
        "player_id": "player-1",
        "item_id": "item-key-1",
        "quantity": 2,
        "obtained_from_type": "mission",
        "obtained_from_id": "mission-puzzle-a-01",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _existing_event(**overrides) -> SimpleNamespace:
    base = {
        "id": "inventory-event-1",
        "player_item_id": "player-item-1",
        "mission_run_id": None,
        "event_type": "credited",
        "quantity_delta": 1,
        "reference_type": ADMIN_GRANT_REFERENCE_TYPE,
        "reference_id": "req-1",
        "metadata_json": {
            "requestId": "req-1",
            "playerId": "player-1",
            "itemId": "item-key-1",
            "direction": "grant",
            "amountAtomic": 1,
            "fullReason": "Компенсация",
            "initiatedByType": "admin",
        },
        "created_at": datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _approval(**overrides) -> SimpleNamespace:
    base = {
        "id": "approval-1",
        "status": "approved",
        "requested_by_admin_id": "admin-1",
        "required_permission_code": PLAYERS_MANAGE_PERMISSION,
        "action_type": ACTION_TYPE_GRANT,
        "target_entity_type": "player",
        "target_entity_id": "player-1",
        "payload_snapshot": {
            "direction": "grant",
            "itemId": "item-key-1",
            "quantity": 1,
            "reason": "Компенсация",
            "playerId": "player-1",
            "thresholdChecked": True,
        },
        "reason": "Компенсация",
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
        "app.admin_player_inventory.SessionLocal",
        SimpleNamespace(begin=lambda: _Ctx(fake_session)),
    )


def _fake_serialize_approval(approval):
    return {
        "id": approval.id,
        "status": getattr(approval, "status", None),
        "requestId": getattr(approval, "request_id", None),
    }


def _direct(
    session,
    *,
    direction="grant",
    quantity=1,
    reason="Компенсация",
    request_id="req-1",
) -> tuple[dict | HTTPException, object]:
    """Вызвать create-эндпоинт в direct-режиме; вернуть (res|exc, audit)."""
    with (
        _run_begin(session),
        patch(
            "app.admin_player_inventory.get_permission_execution_mode",
            return_value=DIRECT_EXECUTION_MODE,
        ),
        patch("app.admin_player_inventory.write_admin_audit") as audit,
    ):
        try:
            result = create_player_inventory_item_adjustment(
                "player-1",
                InventoryItemAdjustmentPayload(
                    direction=direction,
                    item_id="item-key-1",
                    quantity=quantity,
                    reason=reason,
                    request_id=request_id,
                ),
                _request(),
                _admin(),
            )
            return result, audit
        except HTTPException as exc:
            return exc, audit


class PayloadValidationTests(unittest.TestCase):
    """Pydantic-границы payload (422 на уровне валидации)."""

    def test_payload_rejects_zero_quantity_and_invalid_direction(self) -> None:
        with self.assertRaises(ValidationError):
            InventoryItemAdjustmentPayload(
                direction="grant", item_id="i", quantity=0, reason="r", request_id="req-1"
            )
        with self.assertRaises(ValidationError):
            InventoryItemAdjustmentPayload(
                direction="grant", item_id="i", quantity=-5, reason="r", request_id="req-1"
            )
        with self.assertRaises(ValidationError):
            InventoryItemAdjustmentPayload(
                direction="transfer", item_id="i", quantity=1, reason="r", request_id="req-1"
            )

    def test_payload_rejects_reason_over_max_and_blank_request_id(self) -> None:
        with self.assertRaises(ValidationError):
            InventoryItemAdjustmentPayload(
                direction="grant", item_id="i", quantity=1, reason="x" * 4_001,
                request_id="req-1",
            )
        with self.assertRaises(ValidationError):
            InventoryItemAdjustmentPayload(
                direction="grant", item_id="i", quantity=1, reason="",
                request_id="req-1",
            )
        with self.assertRaises(ValidationError):
            InventoryItemAdjustmentPayload(
                direction="grant", item_id="i", quantity=1, reason="r", request_id=""
            )
        # request_id уходит в inventory_events.reference_id (VARCHAR 64 в БД).
        with self.assertRaises(ValidationError):
            InventoryItemAdjustmentPayload(
                direction="grant", item_id="i", quantity=1, reason="r", request_id="x" * 65
            )


class DirectExecutionTests(unittest.TestCase):
    """Прямое исполнение ниже порога: ledger (InventoryEvent) + аудит."""

    def test_grant_published_item_creates_player_item_and_credited_event(self) -> None:
        session = FakeSession(
            scalar_script=[None, None, None],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        result, audit = _direct(session)

        self.assertNotIsInstance(result, HTTPException)
        self.assertEqual(result["inventoryEvent"]["eventType"], "credited")
        self.assertEqual(result["inventoryEvent"]["quantityDelta"], 1)
        self.assertEqual(result["inventoryEvent"]["referenceType"], ADMIN_GRANT_REFERENCE_TYPE)
        self.assertEqual(result["inventoryEvent"]["referenceId"], "req-1")
        self.assertEqual(result["playerItem"]["quantity"], 1)
        self.assertIs(result["idempotent"], False)

        player_items = [o for o in session.added if type(o).__name__ == "PlayerItem"]
        self.assertEqual(len(player_items), 1)
        self.assertEqual(player_items[0].player_id, "player-1")
        self.assertEqual(player_items[0].item_id, "item-key-1")
        self.assertEqual(player_items[0].quantity, 1)
        # Обязательный маркер ручной выдачи: admin_manual + request_id.
        self.assertEqual(player_items[0].obtained_from_type, "admin_manual")
        self.assertEqual(player_items[0].obtained_from_id, "req-1")

        events = [o for o in session.added if isinstance(o, InventoryEvent)]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].reference_type, ADMIN_GRANT_REFERENCE_TYPE)
        self.assertEqual(events[0].reference_id, "req-1")

        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertIn("player.inventory_grant", actions)

    def test_grant_existing_player_item_increments_quantity(self) -> None:
        player_item = _player_item()  # quantity=2
        session = FakeSession(
            scalar_script=[None, player_item, None, player_item],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        result, _ = _direct(session)

        self.assertEqual(result["playerItem"]["quantity"], 3)
        self.assertEqual(player_item.quantity, 3)
        # Существующая строка не пересоздаётся, добавляется только событие.
        player_items = [o for o in session.added if type(o).__name__ == "PlayerItem"]
        self.assertEqual(player_items, [])
        events = [o for o in session.added if isinstance(o, InventoryEvent)]
        self.assertEqual(len(events), 1)

    def test_grant_draft_or_archived_item_returns_409(self) -> None:
        for status_val in ("draft", "archived"):
            session = FakeSession(
                scalar_script=[None, None],
                get_results={
                    "GamePlayer:player-1": _player(),
                    "Item:item-key-1": _item(status=status_val),
                },
            )
            result, _ = _direct(session)
            self.assertIsInstance(result, HTTPException)
            self.assertEqual(result.status_code, 409)
            self.assertEqual(session.added, [])

    def test_grant_missing_item_returns_409(self) -> None:
        session = FakeSession(
            scalar_script=[None, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        result, _ = _direct(session)
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(session.added, [])

    def test_revoke_creates_consumed_event_and_decrements_quantity(self) -> None:
        player_item = _player_item(quantity=3)
        session = FakeSession(
            scalar_script=[None, player_item, None, player_item],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        result, audit = _direct(session, direction="revoke")

        self.assertEqual(result["inventoryEvent"]["eventType"], "consumed")
        self.assertEqual(result["inventoryEvent"]["quantityDelta"], -1)
        self.assertEqual(result["inventoryEvent"]["referenceType"], ADMIN_REVOKE_REFERENCE_TYPE)
        self.assertEqual(result["playerItem"]["quantity"], 2)
        self.assertEqual(player_item.quantity, 2)

        events = [o for o in session.added if isinstance(o, InventoryEvent)]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "consumed")
        self.assertEqual(events[0].quantity_delta, -1)

        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertIn("player.inventory_revoke", actions)

    def test_revoke_without_player_item_returns_409(self) -> None:
        session = FakeSession(
            scalar_script=[None, None, None],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        result, _ = _direct(session, direction="revoke")
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(session.added, [])

    def test_revoke_insufficient_quantity_returns_409(self) -> None:
        player_item = _player_item(quantity=1)
        session = FakeSession(
            scalar_script=[None, player_item, None, player_item],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        result, _ = _direct(session, direction="revoke", quantity=2)
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(session.added, [])


class IdempotencyTests(unittest.TestCase):
    """Повторы request_id: безопасный replay или 409."""

    def test_idempotent_grant_replay_same_request_id(self) -> None:
        player_item = _player_item()
        existing = _existing_event()
        session = FakeSession(
            scalar_script=[None, player_item, existing],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        result, _ = _direct(session, quantity=1)

        self.assertIs(result["idempotent"], True)
        self.assertEqual(result["inventoryEvent"]["id"], "inventory-event-1")
        self.assertEqual(result["playerItem"]["quantity"], 2)
        # Никаких новых проводак и предметов.
        self.assertEqual(session.added, [])

    def test_idempotent_conflict_different_content_returns_409(self) -> None:
        player_item = _player_item()
        existing = _existing_event(
            quantity_delta=5,
            metadata_json={
                "direction": "grant",
                "amountAtomic": 5,
                "requestId": "req-1",
            },
        )
        session = FakeSession(
            scalar_script=[None, player_item, existing],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        result, _ = _direct(session)
        self.assertIsInstance(result, HTTPException)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(session.added, [])


class ApprovalFlowTests(unittest.TestCase):
    """Порог approval: quantity >= gameplay.manual_item_adjustment_approval_threshold."""

    def test_approval_threshold_creates_request_201(self) -> None:
        # quantity == порог (5) у не-super-admin -> создаётся approval-заявка.
        session = FakeSession(
            scalar_script=[None, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_inventory.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch(
                "app.admin_player_inventory._serialize_approval",
                side_effect=_fake_serialize_approval,
            ),
            patch("app.admin_player_inventory.write_admin_audit"),
        ):
            response = create_player_inventory_item_adjustment(
                "player-1",
                InventoryItemAdjustmentPayload(
                    direction="grant",
                    item_id="item-key-1",
                    quantity=5,
                    reason="Компенсация",
                    request_id="req-1",
                ),
                _request(),
                _admin(),
            )

        self.assertEqual(response.status_code, 201)
        body = json.loads(response.body)
        self.assertEqual(body["approval"]["requestId"], "req-1")
        self.assertIs(body["idempotent"], False)

        created_approvals = [o for o in session.added if isinstance(o, AdminApprovalRequest)]
        self.assertEqual(len(created_approvals), 1)
        self.assertEqual(created_approvals[0].action_type, ACTION_TYPE_GRANT)
        self.assertEqual(created_approvals[0].payload_snapshot["itemId"], "item-key-1")
        self.assertEqual(created_approvals[0].payload_snapshot["quantity"], 5)
        # Никаких инвентарных проводок при approval-пути.
        self.assertEqual(
            [o for o in session.added if isinstance(o, InventoryEvent)], []
        )


class ExecuteApprovalTests(unittest.TestCase):
    """Dedicated executor: только super-admin, только inventory action_type."""

    def test_execute_approval_by_super_admin(self) -> None:
        approval = _approval()
        session = FakeSession(
            scalar_script=[approval, None, None],
            get_results={
                "GamePlayer:player-1": _player(),
                "Item:item-key-1": _item(),
            },
        )
        with _run_begin(session), patch(
            "app.admin_player_inventory.write_admin_audit"
        ) as audit:
            result = execute_player_inventory_item_adjustment(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["inventoryEvent"]["eventType"], "credited")
        self.assertEqual(result["inventoryEvent"]["quantityDelta"], 1)
        self.assertEqual(result["inventoryEvent"]["referenceType"], ADMIN_GRANT_REFERENCE_TYPE)
        self.assertEqual(result["inventoryEvent"]["referenceId"], "req-1")
        self.assertEqual(result["playerItem"]["quantity"], 1)

        self.assertEqual(approval.status, "executed")
        self.assertEqual(approval.execution_result["status"], "executed")
        self.assertEqual(approval.executed_by_admin_id, "admin-1")
        self.assertIsNotNone(approval.executed_at)

        player_items = [o for o in session.added if type(o).__name__ == "PlayerItem"]
        self.assertEqual(len(player_items), 1)
        self.assertEqual(player_items[0].obtained_from_type, "admin_manual")
        self.assertEqual(player_items[0].obtained_from_id, "req-1")

        events = [o for o in session.added if isinstance(o, InventoryEvent)]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].reference_id, "req-1")

        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertIn("player.inventory_grant.via_approval", actions)
        self.assertIn("admin_approval_request.executed", actions)

    def test_execute_rejects_wrong_action_type_422_and_pending_409(self) -> None:
        wrong = _approval(action_type="player.wallet_credit")
        session_wrong = FakeSession(scalar_script=[wrong])
        with _run_begin(session_wrong):
            with self.assertRaises(HTTPException) as caught:
                execute_player_inventory_item_adjustment(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 422)

        pending = _approval(status="pending")
        session_pending = FakeSession(scalar_script=[pending])
        with _run_begin(session_pending):
            with self.assertRaises(HTTPException) as caught_pending:
                execute_player_inventory_item_adjustment(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught_pending.exception.status_code, 409)

    def test_execute_invalid_snapshot_returns_409_execution_failed(self) -> None:
        # payload_snapshot без itemId — невалидный snapshot.
        approval = _approval(
            payload_snapshot={
                "direction": "grant",
                "quantity": 1,
                "reason": "Компенсация",
                "playerId": "player-1",
                "thresholdChecked": True,
            }
        )
        session = FakeSession(scalar_script=[approval])
        with _run_begin(session), patch(
            "app.admin_player_inventory.write_admin_audit"
        ) as audit:
            response = execute_player_inventory_item_adjustment(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        # Ответ — JSONResponse с 409 (а не успешный 200-dict).
        self.assertEqual(response.status_code, 409)
        body = json.loads(response.body)
        self.assertEqual(body["error"], "invalid_payload_snapshot")
        self.assertIs(body["idempotent"], False)
        self.assertEqual(body["approval"]["status"], "execution_failed")

        # Полный consumed-статус с execution_error как строкой.
        self.assertEqual(approval.status, "execution_failed")
        self.assertEqual(approval.execution_error, "invalid_payload_snapshot")
        self.assertEqual(approval.execution_result["status"], "failed")

        # Аудит содержит стабильный errorCode.
        failed_audits = [
            call.kwargs["action"]
            for call in audit.call_args_list
            if call.kwargs.get("action") == "admin_approval_request.execution_failed"
        ]
        self.assertEqual(len(failed_audits), 1)