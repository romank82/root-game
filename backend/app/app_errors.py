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
    endpoint: str | None = None,
    status_code: int | None = None,
    player_id: str | None = None,
    stack: str | None = None,
) -> AppError:
    """Создать AppError (flush, без commit; session извне).

    message обрезается до 512 символов (String(512)); stack — до 4000
    (Text, чтобы не раздувать журнал); safe_context — БЕЗ секретов
    (redact выполняет вызывающий — middleware, 13.4-b).
    """
    error = AppError(
        id=_new_id("app-error"),
        correlation_id=correlation_id,
        severity=severity,
        error_type=error_type,
        message=message[:512],
        safe_context=safe_context,
        endpoint=endpoint,
        status_code=status_code,
        player_id=player_id,
        stack=stack[:4000] if stack else None,
    )
    session.add(error)
    session.flush()
    return error
