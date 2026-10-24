"""Запись логов действий игроков (13.3)."""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.mission_engine import _new_id
from app.models import PlayerEvent


def record_player_event(
    session: Session,
    player_id: str,
    event_type: str,
    payload: dict | None = None,
    correlation_id: str | None = None,
) -> PlayerEvent:
    """Создать запись PlayerEvent (flush, без commit; session извне)."""
    event = PlayerEvent(
        id=_new_id("player-event"),
        player_id=player_id,
        event_type=event_type,
        payload_json=payload,
        correlation_id=correlation_id,
    )
    session.add(event)
    session.flush()
    return event