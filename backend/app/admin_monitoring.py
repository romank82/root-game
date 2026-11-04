"""Read-only админ-эндпоинты раздела «Мониторинг» (13.5-a).

- GET /api/v1/admin/monitoring/errors  — список AppError (13.4): фильтры
  severity (error|critical) и period (day|week|month|all), пагинация
  limit/offset, сортировка created_at desc, id desc.
- GET /api/v1/admin/monitoring/events  — список PlayerEvent (13.3):
  фильтры event_type, player_id, period (day|week|month|all), пагинация
  limit/offset, сортировка created_at desc.

Ни один эндпоинт не мутирует БД (read-only): SessionLocal только читает,
без begin()/commit. Игровые данные (AppError, PlayerEvent) не удаляются
и не редактируются — только выборка для модерации/антифрода/аналитики.

Permission: players.read (PLAYERS_READ_PERMISSION) — без новой permission.
Обоснование: мониторинг событий/ошибок — read-only контекст работы с
игроками (та же целевая группа, что и list players), а отдельная
permission monitoring.read добавится позже, если появится требование
разделения ролей (например, отдельный «оператор мониторинга» без доступа
к карточкам игроков). Сейчас изменение каталога permission потребовало бы
миграции и расширения admin-UI — не оправдано для read-only раздела.

AppError имеет player_id (nullable, заполняется с M-2c): для /errors доступны
фильтры severity + period; error-groups группирует по error_type/endpoint/
status_code.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.admin_access import require_permission
from app.db import SessionLocal
from app.models import AdminUser, AppError, PlayerEvent

router = APIRouter(
    prefix="/api/v1/admin/monitoring",
    tags=["admin-monitoring"],
)

PLAYERS_READ_PERMISSION = "players.read"

DEFAULT_LIMIT = 50
MAX_LIMIT = 200

# period -> период в днях (created_at >= now - N days); "all" — без ограничения.
STATS_PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}
VALID_SEVERITIES = ("error", "critical")


def _serialize_app_error(err: AppError) -> dict[str, Any]:
    """AppError -> безопасный JSON (без секретов; safe_context уже redacted)."""
    return {
        "id": err.id,
        "correlationId": err.correlation_id,
        "severity": err.severity,
        "errorType": err.error_type,
        "message": err.message,
        "safeContext": err.safe_context,
        "endpoint": err.endpoint,
        "statusCode": err.status_code,
        "playerId": err.player_id,
        "stack": err.stack,
        "createdAt": err.created_at.isoformat() if err.created_at else None,
    }


def _serialize_player_event(ev: PlayerEvent) -> dict[str, Any]:
    """PlayerEvent -> безопасный JSON (payload уже redacted)."""
    return {
        "id": ev.id,
        "playerId": ev.player_id,
        "eventType": ev.event_type,
        "payloadJson": ev.payload_json,
        "correlationId": ev.correlation_id,
        "createdAt": ev.created_at.isoformat() if ev.created_at else None,
    }


def _period_start(period: str) -> datetime | None:
    """Начало периода (naive UTC, как сервер хранит в SQLite/PostgreSQL)."""
    if period == "all":
        return None
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now - timedelta(days=STATS_PERIOD_DAYS[period])


def _validate_period(period: str) -> None:
    if period not in STATS_PERIOD_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period должен быть 'day', 'week', 'month' или 'all'.",
        )


@router.get("/errors")
def list_admin_monitoring_errors(
    severity: str | None = None,
    period: str = "all",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    correlation_id: str | None = None,
    error_type: str | None = None,
    endpoint: str | None = None,
    status_code: int | None = None,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
) -> dict[str, Any]:
    """Список AppError (13.5-a): severity + period + correlation_id + error_type
    + endpoint + status_code + пагинация.

    Сортировка created_at desc, id desc (детерминированный порядок).
    """
    if severity is not None and severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="severity должен быть 'error' или 'critical'.",
        )
    _validate_period(period)

    safe_limit = max(1, min(limit, MAX_LIMIT))
    safe_offset = max(0, offset)

    filters = []
    if severity is not None:
        filters.append(AppError.severity == severity)
    if correlation_id:
        filters.append(AppError.correlation_id == correlation_id)
    if error_type:
        filters.append(AppError.error_type == error_type)
    if endpoint:
        filters.append(AppError.endpoint == endpoint)
    if status_code is not None:
        filters.append(AppError.status_code == status_code)
    period_start = _period_start(period)
    if period_start is not None:
        filters.append(AppError.created_at >= period_start)

    with SessionLocal() as session:  # read-only, не begin()
        total = (
            session.scalar(
                select(func.count())
                .select_from(AppError)
                .where(*filters)
            )
            or 0
        )
        rows = session.scalars(
            select(AppError)
            .where(*filters)
            .order_by(AppError.created_at.desc(), AppError.id.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()

    return {
        "errors": [_serialize_app_error(err) for err in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/error-groups")
def list_admin_monitoring_error_groups(
    severity: str | None = None,
    period: str = "all",
    min_count: int = 1,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
) -> dict[str, Any]:
    """Группы AppError (M-3): GROUP BY error_type/endpoint/status_code.

    count = COUNT(*), affectedPlayers = COUNT(DISTINCT player_id),
    firstSeen/lastSeen = MIN/MAX(created_at). HAVING COUNT(*) >= min_count.
    Сортировка count DESC + вторичные ключи (детерминированная пагинация).
    """
    if severity is not None and severity not in VALID_SEVERITIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="severity должен быть 'error' или 'critical'.",
        )
    _validate_period(period)

    safe_min_count = max(1, min_count)
    safe_limit = max(1, min(limit, MAX_LIMIT))
    safe_offset = max(0, offset)

    filters = []
    if severity is not None:
        filters.append(AppError.severity == severity)
    period_start = _period_start(period)
    if period_start is not None:
        filters.append(AppError.created_at >= period_start)

    group_count = func.count().label("count")
    affected = func.count(func.distinct(AppError.player_id)).label(
        "affected_players"
    )
    first_seen = func.min(AppError.created_at).label("first_seen")
    last_seen = func.max(AppError.created_at).label("last_seen")

    with SessionLocal() as session:  # read-only, не begin()
        # total = число групп (после HAVING).
        total_stmt = (
            select(
                AppError.error_type,
                AppError.endpoint,
                AppError.status_code,
            )
            .where(*filters)
            .group_by(
                AppError.error_type, AppError.endpoint, AppError.status_code
            )
            .having(func.count() >= safe_min_count)
            .subquery()
        )
        total = (
            session.scalar(select(func.count()).select_from(total_stmt)) or 0
        )

        rows = session.execute(
            select(
                AppError.error_type,
                AppError.endpoint,
                AppError.status_code,
                group_count,
                affected,
                first_seen,
                last_seen,
            )
            .where(*filters)
            .group_by(
                AppError.error_type, AppError.endpoint, AppError.status_code
            )
            .having(func.count() >= safe_min_count)
            .order_by(
                group_count.desc(),
                AppError.error_type,
                AppError.endpoint,
                AppError.status_code,
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()

    return {
        "groups": [
            {
                "errorType": row.error_type,
                "endpoint": row.endpoint,
                "statusCode": row.status_code,
                "count": row.count,
                "affectedPlayers": row.affected_players,
                "firstSeen": (
                    row.first_seen.isoformat() if row.first_seen else None
                ),
                "lastSeen": (
                    row.last_seen.isoformat() if row.last_seen else None
                ),
            }
            for row in rows
        ],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/events")
def list_admin_monitoring_events(
    event_type: str | None = None,
    player_id: str | None = None,
    period: str = "all",
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
) -> dict[str, Any]:
    """Список PlayerEvent (13.5-a): event_type/player_id + period + пагинация.

    Сортировка created_at desc.
    """
    _validate_period(period)

    safe_limit = max(1, min(limit, MAX_LIMIT))
    safe_offset = max(0, offset)

    filters = []
    if event_type is not None:
        filters.append(PlayerEvent.event_type == event_type)
    if player_id is not None:
        filters.append(PlayerEvent.player_id == player_id)
    period_start = _period_start(period)
    if period_start is not None:
        filters.append(PlayerEvent.created_at >= period_start)

    with SessionLocal() as session:  # read-only, не begin()
        total = (
            session.scalar(
                select(func.count())
                .select_from(PlayerEvent)
                .where(*filters)
            )
            or 0
        )
        rows = session.scalars(
            select(PlayerEvent)
            .where(*filters)
            .order_by(PlayerEvent.created_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()

    return {
        "events": [_serialize_player_event(ev) for ev in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }

