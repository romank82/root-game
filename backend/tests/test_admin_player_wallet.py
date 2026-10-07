"""Unit-тесты ручных операций ROOT-кошелька (шаг 5.4).

Unit-style: fake-объекты (SimpleNamespace) + FakeSession вместо TestClient
и БД. Endpoint-функции вызываются напрямую с явным admin/request;
SessionLocal, get_permission_execution_mode и write_admin_audit замоканы.
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
from app.admin_player_wallet import (
    ACTION_TYPE_CREDIT,
    ADMIN_CREDIT_REFERENCE_TYPE,
    ADMIN_DEBIT_REFERENCE_TYPE,
    DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD,
    MANUAL_ADJUSTMENT_THRESHOLD_KEY,
    MAX_REASON_LEDGER,
    PLAYERS_MANAGE_PERMISSION,
    WalletAdjustmentPayload,
    _read_threshold,
    create_player_wallet_adjustment,
    execute_player_wallet_adjustment,
)
from app.models import AdminApprovalRequest, WalletTransaction


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


def _wallet(**overrides) -> SimpleNamespace:
    base = {
        "id": "wallet-1",
        "player_id": "player-1",
        "currency": "ROOT",
        "available_balance": 1500,
        "locked_balance": 0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _existing_tx(**overrides) -> SimpleNamespace:
    base = {
        "id": "tx-1",
        "wallet_id": "wallet-1",
        "amount": 100,
        "balance_after": 1600,
        "transaction_type": "credit",
        "reason": "Компенсация",
        "reference_type": ADMIN_CREDIT_REFERENCE_TYPE,
        "reference_id": "req-1",
        "metadata_json": {"fullReason": "Компенсация", "requestId": "req-1"},
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
        "action_type": ACTION_TYPE_CREDIT,
        "target_entity_type": "player",
        "target_entity_id": "player-1",
        "payload_snapshot": {
            "direction": "credit",
            "amount": 100,
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
        "app.admin_player_wallet.SessionLocal",
        SimpleNamespace(begin=lambda: _Ctx(fake_session)),
    )


def _fake_serialize_approval(approval):
    return {"id": approval.id, "status": getattr(approval, "status", None)}


class WalletAdjustmentPayloadValidationTests(unittest.TestCase):
    """Pydantic-границы payload (422 на уровне валидации)."""

    def test_amount_zero_or_negative_422(self) -> None:
        with self.assertRaises(ValidationError):
            WalletAdjustmentPayload(
                direction="credit", amount=0, reason="r", request_id="req-1"
            )
        with self.assertRaises(ValidationError):
            WalletAdjustmentPayload(
                direction="credit", amount=-5, reason="r", request_id="req-1"
            )

    def test_invalid_direction_422(self) -> None:
        with self.assertRaises(ValidationError):
            WalletAdjustmentPayload(
                direction="transfer", amount=100, reason="r", request_id="req-1"
            )

    def test_reason_required_and_max_length(self) -> None:
        with self.assertRaises(ValidationError):
            WalletAdjustmentPayload(direction="credit", amount=100, request_id="req-1")
        with self.assertRaises(ValidationError):
            WalletAdjustmentPayload(
                direction="credit",
                amount=100,
                reason="x" * 4_001,
                request_id="req-1",
            )


class DirectExecutionTests(unittest.TestCase):
    """Прямое исполнение ниже порога: ledger + аудит, идемпотентность."""

    def _direct(
        self, session, *, direction="credit", amount=100, reason="Компенсация", request_id="req-1"
    ) -> dict | HTTPException:
        with (
            _run_begin(session),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch("app.admin_player_wallet.write_admin_audit") as audit,
        ):
            try:
                result = create_player_wallet_adjustment(
                    "player-1",
                    WalletAdjustmentPayload(
                        direction=direction,
                        amount=amount,
                        reason=reason,
                        request_id=request_id,
                    ),
                    _request(),
                    _admin(),
                )
            except HTTPException as exc:
                return exc
        self._audit = audit
        return result

    def test_direct_credit_creates_transaction_and_audit(self) -> None:
        session = FakeSession(
            scalar_script=[None, _wallet(), None],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._direct(session)

        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["transaction"]["transactionType"], "credit")
        self.assertEqual(result["transaction"]["referenceType"], ADMIN_CREDIT_REFERENCE_TYPE)
        self.assertEqual(result["transaction"]["referenceId"], "req-1")
        self.assertEqual(result["transaction"]["balanceAfter"], 1600)
        self.assertEqual(result["wallet"]["availableBalance"], 1600)

        transactions = [o for o in session.added if isinstance(o, WalletTransaction)]
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].reason, "Компенсация")
        self.assertEqual(transactions[0].reference_type, ADMIN_CREDIT_REFERENCE_TYPE)
        self.assertEqual(transactions[0].reference_id, "req-1")
        self.assertEqual(self._audit.call_args.kwargs["action"], "player.wallet_credit")

    def test_direct_debit_within_balance(self) -> None:
        session = FakeSession(
            scalar_script=[None, _wallet(), None],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._direct(session, direction="debit", amount=300)

        self.assertEqual(result["transaction"]["transactionType"], "debit")
        self.assertEqual(result["transaction"]["referenceType"], ADMIN_DEBIT_REFERENCE_TYPE)
        self.assertEqual(result["transaction"]["balanceAfter"], 1200)
        self.assertEqual(result["wallet"]["availableBalance"], 1200)
        self.assertEqual(self._audit.call_args.kwargs["action"], "player.wallet_debit")

    def test_direct_debit_insufficient_balance_409(self) -> None:
        # 900 < порог -> прямой путь; на кошельке 500 -> недостаточно.
        session = FakeSession(
            scalar_script=[None, _wallet(available_balance=500), None],
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._direct(session, direction="debit", amount=900)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)

    def test_debit_no_wallet_409(self) -> None:
        session = FakeSession(
            scalar_script=[None, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        exc = self._direct(session, direction="debit", amount=50)
        self.assertIsInstance(exc, HTTPException)
        self.assertEqual(exc.status_code, 409)


    def test_credit_creates_wallet_when_missing(self) -> None:
        session = FakeSession(
            scalar_script=[None, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._direct(session, amount=500)

        self.assertEqual(result["wallet"]["availableBalance"], 500)
        self.assertEqual(result["transaction"]["balanceAfter"], 500)
        created_wallets = [o for o in session.added if type(o).__name__ == "Wallet"]
        transactions = [o for o in session.added if isinstance(o, WalletTransaction)]
        self.assertEqual(len(created_wallets), 1)
        self.assertEqual(transactions[0].wallet_id, created_wallets[0].id)

    def test_idempotent_direct_credit_same_request_id(self) -> None:
        session = FakeSession(
            scalar_script=[None, _wallet(), _existing_tx()],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch("app.admin_player_wallet.write_admin_audit") as audit,
        ):
            result = create_player_wallet_adjustment(
                "player-1",
                WalletAdjustmentPayload(
                    direction="credit", amount=100, reason="Компенсация", request_id="req-1"
                ),
                _request(),
                _admin(),
            )

        self.assertIs(result["idempotent"], True)
        self.assertEqual(result["transaction"]["id"], "tx-1")
        self.assertEqual(session.added, [])  # новая проводка не создаётся
        audit.assert_not_called()  # и аудит не дублируется

        # Тот же request_id, но другое содержимое -> 409.
        session_conflict = FakeSession(
            scalar_script=[None, _wallet(), _existing_tx(amount=999)],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session_conflict),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                create_player_wallet_adjustment(
                    "player-1",
                    WalletAdjustmentPayload(
                        direction="credit", amount=100, reason="Компенсация", request_id="req-1"
                    ),
                    _request(),
                    _admin(),
                )
        self.assertEqual(caught.exception.status_code, 409)

    def test_long_reason_truncated_in_ledger_and_full_in_metadata(self) -> None:
        long_reason = "Длинная причина. " * 40  # 720 символов
        # Эндпоинт нормализует reason (.strip()), сверяемся со stripped-версией.
        expected_reason = long_reason.strip()
        session = FakeSession(
            scalar_script=[None, _wallet(), None],
            get_results={"GamePlayer:player-1": _player()},
        )
        result = self._direct(session, reason=long_reason)

        transactions = [o for o in session.added if isinstance(o, WalletTransaction)]
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].reason, expected_reason[:MAX_REASON_LEDGER])
        self.assertEqual(transactions[0].metadata_json["fullReason"], expected_reason)
        self.assertEqual(result["transaction"]["reason"], expected_reason[:MAX_REASON_LEDGER])
        self.assertEqual(result["transaction"]["metadata"]["fullReason"], expected_reason)


class ThresholdTests(unittest.TestCase):
    """A.2: чтение порога и fallback на каталог/дефолт."""

    def test_threshold_reads_active_setting(self) -> None:
        setting = SimpleNamespace(
            key=MANUAL_ADJUSTMENT_THRESHOLD_KEY, status="active", value_json=2500
        )
        session = FakeSession(scalar_script=[setting])
        self.assertEqual(_read_threshold(session), 2500)

    def test_threshold_falls_back_when_missing_or_inactive(self) -> None:
        # Нет записи в БД, каталог отвечает default -> берём из каталога.
        session = FakeSession(scalar_script=[None])
        with patch("app.admin_player_wallet.get_definition") as get_def:
            get_def.return_value = SimpleNamespace(default_value=1000)
            self.assertEqual(_read_threshold(session), DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD)
        get_def.assert_called_once_with(MANUAL_ADJUSTMENT_THRESHOLD_KEY)

        # Запись неактивна -> каталог.
        inactive = SimpleNamespace(
            key=MANUAL_ADJUSTMENT_THRESHOLD_KEY, status="archived", value_json=2500
        )
        session2 = FakeSession(scalar_script=[inactive])
        with patch("app.admin_player_wallet.get_definition") as get_def:
            get_def.return_value = SimpleNamespace(default_value=1000)
            self.assertEqual(_read_threshold(session2), DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD)

        # Ни записи, ни каталога -> модульная константа.
        session3 = FakeSession(scalar_script=[None])
        with patch("app.admin_player_wallet.get_definition") as get_def:
            get_def.return_value = None
            self.assertEqual(_read_threshold(session3), DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD)


class ApprovalFlowTests(unittest.TestCase):
    """Approval-путь: создание заявки, идемпотентность."""

    def _create_response(self, session, *, direction="credit", amount=100, reason="Компенсация"):
        with (
            _run_begin(session),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=APPROVAL_EXECUTION_MODE,
            ),
            patch(
                "app.admin_player_wallet._serialize_approval",
                side_effect=_fake_serialize_approval,
            ),
            patch("app.admin_player_wallet.write_admin_audit") as audit,
        ):
            response = create_player_wallet_adjustment(
                "player-1",
                WalletAdjustmentPayload(
                    direction=direction,
                    amount=amount,
                    reason=reason,
                    request_id="req-1",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=1),
                ),
                _request(),
                _admin(),
            )
        return response, audit

    def test_approval_mode_grant_creates_request_201(self) -> None:
        session = FakeSession(
            scalar_script=[None, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        response, audit = self._create_response(session)

        self.assertEqual(response.status_code, 201)
        self.assertIs(json.loads(response.body)["idempotent"], False)

        approvals = [o for o in session.added if isinstance(o, AdminApprovalRequest)]
        self.assertEqual(len(approvals), 1)
        self.assertEqual(approvals[0].action_type, ACTION_TYPE_CREDIT)
        self.assertEqual(approvals[0].required_permission_code, PLAYERS_MANAGE_PERMISSION)
        self.assertEqual(approvals[0].request_id, "req-1")
        self.assertEqual(approvals[0].status, "pending")
        self.assertEqual(approvals[0].payload_snapshot["direction"], "credit")
        self.assertEqual(approvals[0].payload_snapshot["amount"], 100)
        self.assertEqual(approvals[0].payload_snapshot["playerId"], "player-1")
        self.assertEqual(audit.call_args.kwargs["action"], "admin_approval_request.created")

    def test_amount_at_or_above_threshold_creates_request(self) -> None:
        # Сумма == порогу (1000) при direct-grant обычного админа -> 201 (approval).
        session = FakeSession(
            scalar_script=[None, None],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch(
                "app.admin_player_wallet._serialize_approval",
                side_effect=_fake_serialize_approval,
            ),
            patch("app.admin_player_wallet.write_admin_audit"),
        ):
            response = create_player_wallet_adjustment(
                "player-1",
                WalletAdjustmentPayload(
                    direction="credit",
                    amount=DEFAULT_MANUAL_ADJUSTMENT_THRESHOLD,
                    reason="Большая компенсация",
                    request_id="req-big",
                ),
                _request(),
                _admin(),
            )
        self.assertEqual(response.status_code, 201)

        # Сумма ниже порога при direct-grant -> прямое исполнение (dict, 200).
        session_direct = FakeSession(
            scalar_script=[None, _wallet(), None],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session_direct),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=DIRECT_EXECUTION_MODE,
            ),
            patch("app.admin_player_wallet.write_admin_audit"),
        ):
            result = create_player_wallet_adjustment(
                "player-1",
                WalletAdjustmentPayload(
                    direction="credit",
                    amount=999,
                    reason="Малая компенсация",
                    request_id="req-small",
                ),
                _request(),
                _admin(),
            )
        self.assertIs(result["idempotent"], False)
        self.assertEqual(result["wallet"]["availableBalance"], 2499)


    def test_approval_request_idempotency_same_request_id(self) -> None:
        existing = _approval()
        session = FakeSession(
            scalar_script=[None, existing],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=APPROVAL_EXECUTION_MODE,
            ),
            patch(
                "app.admin_player_wallet._serialize_approval",
                side_effect=_fake_serialize_approval,
            ),
            patch("app.admin_player_wallet.write_admin_audit"),
        ):
            response = create_player_wallet_adjustment(
                "player-1",
                WalletAdjustmentPayload(
                    direction="credit", amount=100, reason="Компенсация", request_id="req-1"
                ),
                _request(),
                _admin(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertIs(json.loads(response.body)["idempotent"], True)

        # Тот же request_id, но другая сумма -> 409.
        conflict = _approval(
            payload_snapshot={
                "direction": "credit",
                "amount": 200,
                "reason": "Другая",
                "playerId": "player-1",
                "thresholdChecked": True,
            },
            reason="Другая",
        )
        session_conflict = FakeSession(
            scalar_script=[None, conflict],
            get_results={"GamePlayer:player-1": _player()},
        )
        with (
            _run_begin(session_conflict),
            patch(
                "app.admin_player_wallet.get_permission_execution_mode",
                return_value=APPROVAL_EXECUTION_MODE,
            ),
        ):
            with self.assertRaises(HTTPException) as caught:
                create_player_wallet_adjustment(
                    "player-1",
                    WalletAdjustmentPayload(
                        direction="credit", amount=100, reason="Компенсация", request_id="req-1"
                    ),
                    _request(),
                    _admin(),
                )
        self.assertEqual(caught.exception.status_code, 409)


class ExecuteApprovalTests(unittest.TestCase):
    """Dedicated executor: только super-admin, только wallet action_type."""

    def test_execute_approval_by_super_admin_creates_transaction(self) -> None:
        approval = _approval()
        session = FakeSession(
            scalar_script=[approval, _wallet(), None],
            get_results={
                "GamePlayer:player-1": _player(),
                # result_wallet достаётся session.get(Wallet, tx.wallet_id).
                "Wallet:wallet-1": _wallet(),
            },
        )
        with _run_begin(session), patch("app.admin_player_wallet.write_admin_audit") as audit:
            result = execute_player_wallet_adjustment(
                "approval-1", _request(), _admin(is_super_admin=True)
            )

        self.assertIs(result["idempotent"], False)
        self.assertEqual(approval.status, "executed")
        self.assertEqual(approval.execution_result["status"], "executed")
        self.assertEqual(approval.executed_by_admin_id, "admin-1")
        self.assertIsNotNone(approval.executed_at)

        transactions = [o for o in session.added if isinstance(o, WalletTransaction)]
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].reference_id, "req-1")
        self.assertEqual(transactions[0].reference_type, ADMIN_CREDIT_REFERENCE_TYPE)

        actions = [call.kwargs["action"] for call in audit.call_args_list]
        self.assertIn("player.wallet_credit.via_approval", actions)
        self.assertIn("admin_approval_request.executed", actions)

    def test_execute_wrong_action_type_422(self) -> None:
        approval = _approval(action_type="system_setting.change")
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session):
            with self.assertRaises(HTTPException) as caught:
                execute_player_wallet_adjustment(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 422)

    def test_execute_repeat_is_idempotent(self) -> None:
        # Повторное исполнение уже EXECUTED -> idempotent без новых проводок.
        approval = _approval(status="executed")
        session = FakeSession(
            scalar_script=[approval],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session), patch("app.admin_player_wallet.write_admin_audit") as audit:
            result = execute_player_wallet_adjustment(
                "approval-1", _request(), _admin(is_super_admin=True)
            )
        self.assertIs(result["idempotent"], True)
        self.assertEqual(session.added, [])
        audit.assert_not_called()

        # Не-approved (pending) -> 409.
        pending = _approval(status="pending")
        session_pending = FakeSession(
            scalar_script=[pending],
            get_results={"GamePlayer:player-1": _player()},
        )
        with _run_begin(session_pending):
            with self.assertRaises(HTTPException) as caught:
                execute_player_wallet_adjustment(
                    "approval-1", _request(), _admin(is_super_admin=True)
                )
        self.assertEqual(caught.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()