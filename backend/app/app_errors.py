"""Запись ошибок приложения (13.4)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.mission_engine import _new_id
from app.models import AppError


def record_app_error(
    session: Session,
    correlation_id: str,
    severity: str,
    error_type: str,
    message: str,
    safe_context: dict | None = None,
) -> AppError:
    """Создать AppError (flush, без commit; session извне).

    message обрезается до 512 символов (String(512)); safe_context —
    БЕЗ секретов (redact выполняет вызывающий — middleware, 13.4-b).
    """
    error = AppError(
        id=_new_id("app-error"),
        correlation_id=correlation_id,
        severity=severity,
        error_type=error_type,
        message=message[:512],
        safe_context=safe_context,
    )
    session.add(error)
    session.flush()
    return error
