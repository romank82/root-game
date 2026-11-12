"""Sprint 8.9.c: админ-раздел «Гео-аудит» (флаги anticheat.flag).

Источник списка — PlayerEvent (event_type="anticheat.flag", player_id
индексирован); review-состояние — PlayerMission.progress["anticheat"];
история — AdminAuditLog (immutable). См. roadmap 8.9.

Права: geo_audit.read (чтение) / geo_audit.manage (review).

Безопасность: сырые координаты не отдаются и не пишутся — только
производные числа (speedKmh/accuracyMeters/...) и ids. Review меняет только
progress["anticheat"]; AdminAuditLog остаётся неизменяемым (append-only),
свободный текст reason в аудит не дублируется (только reasonProvided),
сам текст — в PlayerEvent("anticheat.review").
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminAuditLog, AdminUser, PlayerEvent, PlayerMission

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/admin/geo-audit",
    tags=["admin-geo-audit"],
)

GEO_AUDIT_READ_PERMISSION = "geo_audit.read"
GEO_AUDIT_MANAGE_PERMISSION = "geo_audit.manage"

EVENT_TYPE_ANTICHEAT_FLAG = "anticheat.flag"
EVENT_TYPE_ANTICHEAT_REVIEW = "anticheat.review"
ACTION_ANTICHEAT_REVIEW = "anticheat.review"
ENTITY_TYPE_PLAYER_MISSION = "player_mission"
FLAG_STATUS_REVIEW = "review"

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
PERIOD_DAYS = {"day": 1, "week": 7, "month": 30, "all": None}
VALID_SIGNALS = ("velocity", "accuracy")
MAX_REASON_LENGTH = 512


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _period_start(period: str) -> datetime | None:
    """Начало периода (naive UTC, как в admin_monitoring) или 422."""
    if period not in PERIOD_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period должен быть day|week|month|all.",
        )
    days = PERIOD_DAYS[period]
    if days is None:
        return None
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)


def _flag_payload(event: PlayerEvent) -> dict[str, Any]:
    payload = event.payload_json
    return payload if isinstance(payload, dict) else {}


def _flag_signals(event: PlayerEvent) -> list[dict[str, Any]]:
    signals = _flag_payload(event).get("signals")
    if not isinstance(signals, list):
        return []
    return [signal for signal in signals if isinstance(signal, dict)]


def _event_has_signal(event: PlayerEvent, signal: str) -> bool:
    return any(item.get("signal") == signal for item in _flag_signals(event))


def _serialize_flag(
    event: PlayerEvent,
    review_status: str | None,
) -> dict[str, Any]:
    payload = _flag_payload(event)
    return {
        "id": event.id,
        "playerId": event.player_id,
        "missionId": payload.get("missionId"),
        "zoneId": payload.get("zoneId"),
        "mode": payload.get("mode"),
        "signals": _flag_signals(event),
        "reviewStatus": review_status,
        "correlationId": event.correlation_id,
        "createdAt": event.created_at.isoformat() if event.created_at else None,
    }


def _anticheat_status(player_mission: PlayerMission | None) -> str | None:
    if player_mission is None:
        return None
    anticheat = (player_mission.progress or {}).get("anticheat")
    if not isinstance(anticheat, dict):
        return None
    value = anticheat.get("status")
    return value if isinstance(value, str) else None


def _review_status_map(
    session: Any,
    events: list[PlayerEvent],
) -> dict[tuple[str, str], str | None]:
    """(player_id, mission_id) -> status из progress["anticheat"]."""
    player_ids = {event.player_id for event in events}
    mission_ids = {
        payload["missionId"]
        for payload in (_flag_payload(event) for event in events)
        if isinstance(payload.get("missionId"), str)
    }
    if not player_ids or not mission_ids:
        return {}

    rows = session.scalars(
        select(PlayerMission).where(
            PlayerMission.player_id.in_(player_ids),
            PlayerMission.mission_id.in_(mission_ids),
        )
    ).all()
    return {(row.player_id, row.mission_id): _anticheat_status(row) for row in rows}


def _find_player_mission(
    session: Any,
    player_id: str,
    mission_id: str,
) -> PlayerMission | None:
    return session.scalar(
        select(PlayerMission).where(
            PlayerMission.player_id == player_id,
            PlayerMission.mission_id == mission_id,
        )
    )


def _latest_flag_event(
    session: Any,
    player_id: str,
    mission_id: str,
) -> PlayerEvent | None:
    events = session.scalars(
        select(PlayerEvent)
        .where(
            PlayerEvent.player_id == player_id,
            PlayerEvent.event_type == EVENT_TYPE_ANTICHEAT_FLAG,
        )
        .order_by(PlayerEvent.created_at.desc())
    ).all()
    for event in events:
        if _flag_payload(event).get("missionId") == mission_id:
            return event
    return None


def _latest_review_audit(
    session: Any,
    player_mission_id: str,
) -> AdminAuditLog | None:
    return session.scalar(
        select(AdminAuditLog)
        .where(
            AdminAuditLog.action == ACTION_ANTICHEAT_REVIEW,
            AdminAuditLog.entity_type == ENTITY_TYPE_PLAYER_MISSION,
            AdminAuditLog.entity_id == player_mission_id,
        )
        .order_by(AdminAuditLog.created_at.desc())
        .limit(1)
    )


@router.get("/flags")
def list_geo_audit_flags(
    player_id: str | None = None,
    period: str = "week",
    signal: str | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(GEO_AUDIT_READ_PERMISSION)),
) -> dict[str, Any]:
    """Список флагов anticheat.flag с фильтрами и пагинацией (read-only).

    signal (velocity|accuracy) фильтруется в Python: сигналы лежат в
    payload_json.signals (JSON), а не отдельной колонкой. При заданном signal
    total считается по отфильтрованному набору (в пределах period/player_id).
    """
    if signal is not None and signal not in VALID_SIGNALS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="signal должен быть velocity или accuracy.",
        )

    safe_limit = max(1, min(limit, MAX_LIMIT))
    safe_offset = max(0, offset)

    conditions: list[Any] = [PlayerEvent.event_type == EVENT_TYPE_ANTICHEAT_FLAG]
    if player_id:
        conditions.append(PlayerEvent.player_id == player_id)
    cutoff = _period_start(period)
    if cutoff is not None:
        conditions.append(PlayerEvent.created_at >= cutoff)

    with SessionLocal() as session:  # read-only, не begin()
        if signal is None:
            total = (
                session.scalar(
                    select(func.count())
                    .select_from(PlayerEvent)
                    .where(*conditions)
                )
                or 0
            )
            rows = list(
                session.scalars(
                    select(PlayerEvent)
                    .where(*conditions)
                    .order_by(PlayerEvent.created_at.desc())
                    .offset(safe_offset)
                    .limit(safe_limit)
                ).all()
            )
        else:
            matching = [
                event
                for event in session.scalars(
                    select(PlayerEvent)
                    .where(*conditions)
                    .order_by(PlayerEvent.created_at.desc())
                ).all()
                if _event_has_signal(event, signal)
            ]
            total = len(matching)
            rows = matching[safe_offset : safe_offset + safe_limit]

        status_by_pair = _review_status_map(session, rows)
        flags = [
            _serialize_flag(
                event,
                status_by_pair.get(
                    (event.player_id, _flag_payload(event).get("missionId"))
                ),
            )
            for event in rows
        ]

    return {
        "flags": flags,
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


@router.get("/flags/{player_id}/{mission_id}")
def get_geo_audit_flag_detail(
    player_id: str,
    mission_id: str,
    _admin: AdminUser = Depends(require_permission(GEO_AUDIT_READ_PERMISSION)),
) -> dict[str, Any]:
    """Детали флага: последний flag, progress["anticheat"], review-аудит."""
    with SessionLocal() as session:  # read-only, не begin()
        player_mission = _find_player_mission(session, player_id, mission_id)
        event = _latest_flag_event(session, player_id, mission_id)
        if player_mission is None and event is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Флаг не найден.",
            )

        review_audit = (
            _latest_review_audit(session, player_mission.id)
            if player_mission is not None
            else None
        )
        anticheat = (
            (player_mission.progress or {}).get("anticheat")
            if player_mission is not None
            else None
        )

        return {
            "playerId": player_id,
            "missionId": mission_id,
            "flag": (
                _serialize_flag(event, _anticheat_status(player_mission))
                if event is not None
                else None
            ),
            "anticheat": anticheat if isinstance(anticheat, dict) else None,
            "lastReview": (
                {
                    "action": review_audit.action,
                    "outcome": review_audit.outcome,
                    "adminId": review_audit.admin_user_id,
                    "adminUsername": review_audit.admin_username_snapshot,
                    "createdAt": (
                        review_audit.created_at.isoformat()
                        if review_audit.created_at
                        else None
                    ),
                }
                if review_audit is not None
                else None
            ),
        }


class ReviewFlagPayload(BaseModel):
    """Решение администратора по флагу античита."""

    decision: Literal["reviewed", "dismissed"]
    reason: str | None = None


@router.post("/flags/{player_id}/{mission_id}/review")
def review_geo_audit_flag(
    player_id: str,
    mission_id: str,
    payload: ReviewFlagPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(GEO_AUDIT_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Снять/подтвердить флаг: progress["anticheat"] + immutable audit + event.

    Guard: review возможен только из статуса review (повторный review -> 409).
    В before/after/metadata попадают только anticheat-проекция и ids — сырых
    координат там нет.
    """
    reason = (payload.reason or "").strip()[:MAX_REASON_LENGTH] or None

    with SessionLocal.begin() as session:
        player_mission = session.scalar(
            select(PlayerMission)
            .where(
                PlayerMission.player_id == player_id,
                PlayerMission.mission_id == mission_id,
            )
            .with_for_update()
        )
        if player_mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Прогресс миссии не найден.",
            )

        progress = dict(player_mission.progress or {})
        anticheat = progress.get("anticheat")
        if (
            not isinstance(anticheat, dict)
            or anticheat.get("status") != FLAG_STATUS_REVIEW
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Флаг не в статусе review.",
            )

        before = {"anticheat": anticheat}
        progress["anticheat"] = {
            **anticheat,
            "status": payload.decision,
            "reviewedByAdminId": admin.id,
            "reviewedAt": _utcnow().isoformat(),
        }
        player_mission.progress = progress
        session.flush()

        flag_event = _latest_flag_event(session, player_id, mission_id)
        zone_id = _flag_payload(flag_event).get("zoneId") if flag_event else None

        write_admin_audit(
            session,
            actor=admin,
            action=ACTION_ANTICHEAT_REVIEW,
            entity_type=ENTITY_TYPE_PLAYER_MISSION,
            entity_id=player_mission.id,
            request=request,
            permission_code=GEO_AUDIT_MANAGE_PERMISSION,
            before=before,
            after={"anticheat": progress["anticheat"]},
            # Свободный текст reason в audit не дублируется (security-and-audit).
            metadata={
                "playerId": player_id,
                "missionId": mission_id,
                "zoneId": zone_id,
                "decision": payload.decision,
                "reasonProvided": reason is not None,
            },
        )

        # История игрока: append-only событие с решением администратора.
        try:
            from app.player_events import record_player_event

            with session.begin_nested():
                record_player_event(
                    session,
                    player_id,
                    EVENT_TYPE_ANTICHEAT_REVIEW,
                    payload={
                        "missionId": mission_id,
                        "zoneId": zone_id,
                        "decision": payload.decision,
                        "reason": reason,
                        "adminId": admin.id,
                    },
                    correlation_id=None,
                )
        except Exception as error:  # noqa: BLE001 — событие не важнее review
            logger.warning("player_event anticheat.review failed: %s", error)

    return {
        "playerId": player_id,
        "missionId": mission_id,
        "status": payload.decision,
    }

