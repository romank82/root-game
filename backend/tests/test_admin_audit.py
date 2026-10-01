import inspect
import unittest
from types import SimpleNamespace

from app.admin_audit import (
    REDACTED_VALUE,
    _sanitize_error_context,
    build_admin_approval_audit_snapshot,
    build_admin_permission_audit_snapshot,
    sanitize_audit_data,
    write_admin_audit,
)


class AdminAuditSanitizationTests(unittest.TestCase):
    def test_nested_sensitive_values_are_redacted(self):
        value = {
            "safe": {"items": [{"password": "not-for-audit"}]},
            "telegramInitData": "not-for-audit",
            "contentHash": "allowed-business-value",
        }

        result = sanitize_audit_data(value)

        self.assertEqual(result["safe"]["items"][0]["password"], REDACTED_VALUE)
        self.assertEqual(result["telegramInitData"], REDACTED_VALUE)
        self.assertEqual(result["contentHash"], "allowed-business-value")

    def test_error_context_is_strictly_allowlisted(self):
        result = _sanitize_error_context(
            {
                "code": "setting_validation_failed",
                "category": "validation",
                "retryable": False,
                "message": "must not be stored",
                "token": "must not be stored",
            }
        )

        self.assertEqual(
            result,
            {
                "code": "setting_validation_failed",
                "category": "validation",
                "retryable": False,
            },
        )


class AdminAuditHelperBoundaryTests(unittest.TestCase):
    def test_helper_does_not_accept_raw_reason_or_username_override(self):
        parameters = inspect.signature(write_admin_audit).parameters

        self.assertNotIn("reason", parameters)
        self.assertNotIn("admin_username_snapshot", parameters)


class AdminPermissionAuditProjectionTests(unittest.TestCase):
    def test_projection_excludes_free_text_reason(self):
        serialized = {
            "permissionCode": "admins.manage",
            "executionMode": "direct",
            "isActive": True,
            "reason": "must-not-enter-audit",
        }

        result = build_admin_permission_audit_snapshot(serialized)

        self.assertEqual(result["permissionCode"], "admins.manage")
        self.assertEqual(result["executionMode"], "direct")
        self.assertTrue(result["isActive"])
        self.assertTrue(result["reasonProvided"])
        self.assertNotIn("reason", result)


class AdminApprovalAuditProjectionTests(unittest.TestCase):
    def test_projection_accepts_serialized_snapshot_without_sensitive_fields(self):
        serialized = {
            "id": "admin-approval-test",
            "status": "cancelled",
            "requestedByAdminId": "admin-requester",
            "payloadSnapshot": {"neutralKey": "must-not-enter-audit"},
            "reason": "must-not-enter-audit",
            "cancellationReason": "must-not-enter-audit",
            "executionResult": {"raw": "must-not-enter-audit"},
        }

        result = build_admin_approval_audit_snapshot(serialized)

        self.assertEqual(result["id"], "admin-approval-test")
        self.assertEqual(result["status"], "cancelled")
        self.assertTrue(result["payloadSnapshotProvided"])
        self.assertTrue(result["reasonProvided"])
        self.assertTrue(result["cancellationReasonProvided"])
        self.assertTrue(result["executionResultProvided"])
        self.assertNotIn("payloadSnapshot", result)
        self.assertNotIn("reason", result)
        self.assertNotIn("cancellationReason", result)
        self.assertNotIn("executionResult", result)

    def test_projection_excludes_untrusted_payload_and_free_text(self):
        approval = SimpleNamespace(
            id="admin-approval-test",
            status="approved",
            requested_by_admin_id="admin-requester",
            required_permission_code="system_settings.manage",
            action_type="system_setting.change",
            target_entity_type="system_setting",
            target_entity_id="economy.transfer_max_amount",
            request_id="request-test-123",
            expires_at=None,
            approved_by_admin_id="admin-reviewer",
            approved_at=None,
            rejected_by_admin_id=None,
            rejected_at=None,
            cancelled_by_admin_id=None,
            cancelled_at=None,
            executed_by_admin_id=None,
            executed_at=None,
            payload_snapshot={"value": "must-not-enter-audit"},
            reason="must-not-enter-audit",
            approval_comment="must-not-enter-audit",
            rejection_comment=None,
            cancellation_reason=None,
            execution_result={"raw": "must-not-enter-audit"},
            execution_error="must-not-enter-audit",
            created_at=None,
            updated_at=None,
        )

        result = build_admin_approval_audit_snapshot(approval)

        self.assertNotIn("payloadSnapshot", result)
        self.assertNotIn("reason", result)
        self.assertNotIn("approvalComment", result)
        self.assertNotIn("executionResult", result)
        self.assertNotIn("executionError", result)
        self.assertTrue(result["payloadSnapshotProvided"])
        self.assertTrue(result["reasonProvided"])
        self.assertTrue(result["approvalCommentProvided"])
        self.assertTrue(result["executionResultProvided"])
        self.assertTrue(result["executionErrorProvided"])


if __name__ == "__main__":
    unittest.main()
