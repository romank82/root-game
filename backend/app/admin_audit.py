from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AdminAuditLog, AdminUser


REDACTED_VALUE = "[REDACTED]"
MAX_USER_AGENT_LENGTH = 512
VALID_OUTCOMES = {"success", "failure", "denied"}

# Do not use a broad "hash" rule: harmless business fields such as contentHash
# must remain usable in audit data. password_hash is covered by "password".
SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "token",
    "cookie",
    "secret",
    "private_key",
    "privatekey",
    "api_key",
    "apikey",
    "bot_token",
    "bottoken",
    "init_data",
    "initdata",
    "validation",
    "accepted_answer",
    "acceptedanswer",
)

# No exception messages, tracebacks, request data, headers, or arbitrary keys.
ALLOWED_ERROR_CONTEXT_KEYS = {"code", "category", "retryable"}


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _normalized_key(value: object) -> str:
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _is_sensitive_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return any(fragment in normalized for fragment in SENSITIVE_KEY_FRAGMENTS)


def sanitize_audit_data(value: Any) -> Any:
    """Recursively redact sensitive values before audit storage."""
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, nested_value in value.items():
            key_as_string = str(key)
            sanitized[key_as_string] = (
                REDACTED_VALUE
                if _is_sensitive_key(key_as_string)
                else sanitize_audit_data(nested_value)
            )
        return sanitized

    if isinstance(value, list):
        return [sanitize_audit_data(item) for item in value]

    if isinstance(value, tuple):
        return [sanitize_audit_data(item) for item in value]

    return value


def _sanitize_error_context(
    error_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Store only a narrow, safe, typed error context."""
    if not error_context:
        return {}

    result: dict[str, Any] = {}

    for key in ALLOWED_ERROR_CONTEXT_KEYS:
        if key not in error_context:
            continue

        value = error_context[key]

        if key == "retryable":
            if isinstance(value, bool):
                result[key] = value
            continue

        if isinstance(value, str):
            normalized = value.strip()
            if normalized:
                result[key] = normalized[:128]

    return result


def _request_context(request: Request | None) -> tuple[str, str | None, str | None]:
    """Read server-generated HTTP context, or generate a CLI-only context."""
    if request is None:
        return f"cli:{uuid4().hex}", None, None

    context = getattr(request.state, "audit_context", None)
    if isinstance(context, Mapping):
        correlation_id = context.get("correlation_id")
        ip_address = context.get("ip_address")
        user_agent = context.get("user_agent")

        if isinstance(correlation_id, str) and correlation_id:
            return (
                correlation_id[:64],
                ip_address if isinstance(ip_address, str) else None,
                user_agent[:MAX_USER_AGENT_LENGTH]
                if isinstance(user_agent, str) and user_agent
                else None,
            )

    # Fallback for direct tests that do not install the HTTP middleware.
    return (
        uuid4().hex,
        request.client.host if request.client else None,
        (request.headers.get("user-agent") or "")[:MAX_USER_AGENT_LENGTH] or None,
    )


def build_admin_approval_audit_snapshot(approval: Any) -> dict[str, Any]:
    """
    Return a strictly allowlisted approval projection safe for immutable audit.

    The builder accepts either an ORM approval object or the API serialization
    produced before/after a state transition. Arbitrary payloads, free-text
    fields and raw execution details are deliberately excluded.
    """

    def value(attribute_name: str, serialized_key: str) -> Any:
        if isinstance(approval, Mapping):
            return approval.get(serialized_key)
        return getattr(approval, attribute_name, None)

    def timestamp(attribute_name: str, serialized_key: str) -> str | None:
        current = value(attribute_name, serialized_key)
        if current is None:
            return None
        if isinstance(current, str):
            return current
        return current.isoformat()

    def provided(attribute_name: str, serialized_key: str) -> bool:
        return bool(value(attribute_name, serialized_key))

    return {
        "id": value("id", "id"),
        "status": value("status", "status"),
        "requestedByAdminId": value(
            "requested_by_admin_id",
            "requestedByAdminId",
        ),
        "requiredPermissionCode": value(
            "required_permission_code",
            "requiredPermissionCode",
        ),
        "actionType": value("action_type", "actionType"),
        "targetEntityType": value("target_entity_type", "targetEntityType"),
        "targetEntityId": value("target_entity_id", "targetEntityId"),
        "requestId": value("request_id", "requestId"),
        "expiresAt": timestamp("expires_at", "expiresAt"),
        "approvedByAdminId": value("approved_by_admin_id", "approvedByAdminId"),
        "approvedAt": timestamp("approved_at", "approvedAt"),
        "rejectedByAdminId": value("rejected_by_admin_id", "rejectedByAdminId"),
        "rejectedAt": timestamp("rejected_at", "rejectedAt"),
        "cancelledByAdminId": value(
            "cancelled_by_admin_id",
            "cancelledByAdminId",
        ),
        "cancelledAt": timestamp("cancelled_at", "cancelledAt"),
        "executedByAdminId": value("executed_by_admin_id", "executedByAdminId"),
        "executedAt": timestamp("executed_at", "executedAt"),
        "payloadSnapshotProvided": provided(
            "payload_snapshot",
            "payloadSnapshot",
        ),
        "reasonProvided": provided("reason", "reason"),
        "approvalCommentProvided": provided(
            "approval_comment",
            "approvalComment",
        ),
        "rejectionCommentProvided": provided(
            "rejection_comment",
            "rejectionComment",
        ),
        "cancellationReasonProvided": provided(
            "cancellation_reason",
            "cancellationReason",
        ),
        "executionResultProvided": provided(
            "execution_result",
            "executionResult",
        ),
        "executionErrorProvided": provided(
            "execution_error",
            "executionError",
        ),
        "createdAt": timestamp("created_at", "createdAt"),
        "updatedAt": timestamp("updated_at", "updatedAt"),
    }


def build_admin_permission_audit_snapshot(permission: Any) -> dict[str, Any]:
    """
    Return a strictly allowlisted permission-grant projection for audit.

    Free-text grant reasons remain domain data and are intentionally excluded
    from immutable audit history.
    """

    def value(attribute_name: str, serialized_key: str) -> Any:
        if isinstance(permission, Mapping):
            return permission.get(serialized_key)
        return getattr(permission, attribute_name, None)

    def timestamp(attribute_name: str, serialized_key: str) -> str | None:
        current = value(attribute_name, serialized_key)
        if current is None:
            return None
        if isinstance(current, str):
            return current
        return current.isoformat()

    return {
        "permissionCode": value("permission_code", "permissionCode"),
        "executionMode": value("execution_mode", "executionMode"),
        "isActive": value("is_active", "isActive"),
        "grantedByAdminId": value(
            "granted_by_admin_id",
            "grantedByAdminId",
        ),
        "grantedAt": timestamp("granted_at", "grantedAt"),
        "revokedByAdminId": value(
            "revoked_by_admin_id",
            "revokedByAdminId",
        ),
        "revokedAt": timestamp("revoked_at", "revokedAt"),
        "reasonProvided": bool(value("reason", "reason")),
    }


def write_admin_audit(
    session: Session,
    *,
    actor: AdminUser | None,
    action: str,
    entity_type: str,
    entity_id: str | None,
    request: Request | None,
    permission_code: str | None = None,
    approval_request_id: str | None = None,
    request_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    outcome: str = "success",
    error_context: Mapping[str, Any] | None = None,
) -> AdminAuditLog:
    """Append one sanitized immutable administrative audit event."""
    if outcome not in VALID_OUTCOMES:
        raise ValueError(f"Unsupported audit outcome: {outcome}")

    correlation_id, ip_address, user_agent = _request_context(request)

    admin_username_snapshot = actor.username if actor is not None else None

    audit = AdminAuditLog(
        id=_new_id("admin-audit"),
        admin_user_id=actor.id if actor is not None else None,
        admin_username_snapshot=(
            admin_username_snapshot[:64] if admin_username_snapshot else None
        ),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        permission_code=permission_code,
        approval_request_id=approval_request_id,
        request_id=request_id,
        correlation_id=correlation_id[:64],
        reason=None,
        before_json=sanitize_audit_data(before or {}),
        after_json=sanitize_audit_data(after or {}),
        outcome=outcome,
        error_context_json=_sanitize_error_context(error_context),
        metadata_json=sanitize_audit_data(metadata or {}),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(audit)
    return audit
