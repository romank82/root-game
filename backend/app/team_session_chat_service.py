"""MVP чата командной сессии (этап 6.6-a).

Чат существует ТОЛЬКО внутри TeamSession (постоянной команды в игре нет).
Доступ — только активным участникам сессии (TeamSessionMember.status in
joined/ready) и только пока сессия в статусе collecting/ready_to_start/active.
После финала (succeeded/failed/expired/cancelled_before_start) список и
отправка возвращают 409: история остаётся в БД, но чат закрыт.

Модерации нет (MVP): поле status ('visible'|'hidden') заложено под 6.7.b;
в список попадают только visible.

Пагинация — курсор по created_at (новые сверху): limit (default 50, max 200)
+ необязательный before (ISO-8601). id — uuid-подобный (не монотонный),
поэтому offset-пагинация здесь не используется.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.datetime_utils import ensure_utc
from app.geo_team_runtime_models import (
    TeamSession,
    TeamSessionMember,
    TeamSessionMessage,
)
from app.mission_engine import MissionEngineError
from app.team_missions_service import ACTIVE_MEMBER_STATUSES, ACTIVE_SESSION_STATUSES

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_TEXT_LENGTH = 1000

# Значения поля status сообщения: hidden — для будущей модерации (6.7.b).
MESSAGE_STATUS_VISIBLE = "visible"


def _mission_error(status_code: int, detail: str) -> MissionEngineError:
    return MissionEngineError(status_code, detail)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _require_active_session_member(
    session: Session,
    player_id: str,
    session_id: str,
) -> tuple[TeamSession, TeamSessionMember]:
    """Сессия + активное членство + сессия не завершена.

    404 — сессии нет / игрок не участник (не раскрываем существование сессии);
    409 — чат закрыт (сессия вне collecting/ready_to_start/active).
    """
    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")

    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is None or member.status not in ACTIVE_MEMBER_STATUSES:
        raise _mission_error(404, "Вы не участник этой сессии.")

    if team_session.status not in ACTIVE_SESSION_STATUSES:
        raise _mission_error(409, "Сессия завершена. Чат недоступен.")

    return team_session, member


def _parse_before(value: str | None) -> datetime | None:
    """ISO-8601 → aware UTC; None — без курсора; мусор → 422."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        raise _mission_error(422, "Некорректный параметр before (ожидается ISO-8601).")
    return ensure_utc(parsed)


def _serialize_message(
    message: TeamSessionMessage,
    display_name: str | None,
) -> dict:
    """Публичные поля сообщения.

    displayName — GamePlayer.display_name автора (nullable); клиент показывает
    его, а при отсутствии — playerId.
    """
    created_at = ensure_utc(message.created_at)
    return {
        "id": message.id,
        "playerId": message.player_id,
        "displayName": display_name,
        "text": message.text,
        "createdAt": created_at.isoformat() if created_at is not None else None,
    }


def list_messages_entrypoint(
    player_id: str,
    session_id: str,
    limit: int = DEFAULT_LIMIT,
    before: str | None = None,
) -> dict:
    """Последние visible-сообщения сессии (новые сверху) + hasMore."""
    from app.db import SessionLocal

    before_dt = _parse_before(before)
    safe_limit = max(1, min(int(limit), MAX_LIMIT))

    with SessionLocal.begin() as session:
        team_session, _member = _require_active_session_member(
            session, player_id, session_id
        )
        query = select(TeamSessionMessage).where(
            TeamSessionMessage.team_session_id == team_session.id,
            TeamSessionMessage.status == MESSAGE_STATUS_VISIBLE,
        )
        if before_dt is not None:
            query = query.where(TeamSessionMessage.created_at < before_dt)
        rows = session.scalars(
            query.order_by(
                TeamSessionMessage.created_at.desc(),
                TeamSessionMessage.id.desc(),
            ).limit(safe_limit + 1)
        ).all()
        # Сериализуем внутри транзакции: после commit объекты expired.
        has_more = len(rows) > safe_limit
        page = rows[:safe_limit]

        # displayName одним IN-запросом (без N+1 на 50 сообщений).
        from app.models import GamePlayer

        player_ids = {row.player_id for row in page}
        display_names: dict[str, str | None] = {}
        if player_ids:
            display_names = {
                player_id: display_name
                for player_id, display_name in session.execute(
                    select(GamePlayer.id, GamePlayer.display_name).where(
                        GamePlayer.id.in_(player_ids)
                    )
                ).all()
            }

        messages = [
            _serialize_message(row, display_names.get(row.player_id))
            for row in page
        ]

    return {"messages": messages, "hasMore": has_more, "limit": safe_limit}


def send_message_entrypoint(player_id: str, session_id: str, text: str) -> dict:
    """Отправить сообщение в чат сессии (только активный участник)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        team_session, _member = _require_active_session_member(
            session, player_id, session_id
        )

        clean = (text or "").strip()
        if not clean:
            raise _mission_error(422, "Сообщение не может быть пустым.")
        if len(clean) > MAX_TEXT_LENGTH:
            raise _mission_error(
                422, f"Сообщение слишком длинное (макс. {MAX_TEXT_LENGTH})."
            )

        now = _utcnow()
        message = TeamSessionMessage(
            id=_new_id("team-msg"),
            team_session_id=team_session.id,
            player_id=player_id,
            text=clean,
            status=MESSAGE_STATUS_VISIBLE,
            created_at=now,
            updated_at=now,
        )
        session.add(message)
        session.flush()

        from app.models import GamePlayer

        player = session.get(GamePlayer, player_id)
        return _serialize_message(
            message, player.display_name if player is not None else None
        )
