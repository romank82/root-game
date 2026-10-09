"""Командные миссии (шаг 7.1.a): чтение активных командных сессий игрока.

Только SELECT, ничего не мутирует. Входная точка для HTTP-слоя —
list_my_team_sessions_entrypoint(player_id) -> {"sessions": [...]}.

Модуль повторяет паттерн teams_service.py / mission_engine.py: чистые
функции без FastAPI, короткие read-only сессии через SessionLocal(),
entrypoint-обёртка для HTTP-слоя. Импорт SessionLocal и моделей — ленивый,
внутри функций, чтобы избежать циклов импорта и лишних зависимостей при
импорте модуля.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

# Активные командные сессии — в этих статусах игрок задействован в миссии.
ACTIVE_SESSION_STATUSES = frozenset({"collecting", "ready_to_start", "active"})

# Активные участники сессии (членство ещё действует, не left/removed/settled).
ACTIVE_MEMBER_STATUSES = frozenset({"joined", "ready"})


def _list_my_team_sessions(session: Session, player_id: str) -> list[dict]:
    """Активные TeamSession игрока (только SELECT, сортировка createdAt DESC)."""
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember
    from app.models import Mission

    # Мои членства в командных сессиях.
    memberships = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.player_id == player_id,
        )
    ).all()

    # Игрок не участвует ни в одной сессии.
    if not memberships:
        return []

    session_ids = [membership.team_session_id for membership in memberships]

    # Только активные сессии, новые сверху.
    team_sessions = session.scalars(
        select(TeamSession)
        .where(
            TeamSession.id.in_(session_ids),
            TeamSession.status.in_(ACTIVE_SESSION_STATUSES),
        )
        .order_by(TeamSession.created_at.desc())
    ).all()

    if not team_sessions:
        return []

    # Заголовки миссий (без content/validation_config и прочих закрытых данных).
    missions = {
        mission.id: mission
        for mission in session.scalars(
            select(Mission).where(
                Mission.id.in_({ts.mission_id for ts in team_sessions})
            )
        ).all()
    }

    # Все участники этих сессий — для memberCount.
    members_by_session: dict[str, list[TeamSessionMember]] = {}
    for member in session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id.in_(session_ids),
        )
    ).all():
        members_by_session.setdefault(member.team_session_id, []).append(member)

    my_membership = {
        membership.team_session_id: membership for membership in memberships
    }

    result = []
    for team_session in team_sessions:
        mission = missions.get(team_session.mission_id)
        membership = my_membership.get(team_session.id)
        active_count = sum(
            1
            for member in members_by_session.get(team_session.id, [])
            if member.status in ACTIVE_MEMBER_STATUSES
        )
        result.append(
            {
                "id": team_session.id,
                "mission_id": team_session.mission_id,
                "missionTitle": mission.title if mission is not None else None,
                "status": team_session.status,
                "started_at": (
                    team_session.started_at.isoformat()
                    if team_session.started_at
                    else None
                ),
                "createdAt": (
                    team_session.created_at.isoformat()
                    if team_session.created_at
                    else None
                ),
                "memberCount": active_count,
                "myStatus": membership.status if membership is not None else None,
                "myReadyAt": (
                    membership.ready_at.isoformat()
                    if membership is not None and membership.ready_at
                    else None
                ),
            }
        )
    return result


def list_my_team_sessions_entrypoint(player_id: str) -> dict:
    """Точка вызова из HTTP-слоя: {"sessions": [...]} активных сессий игрока."""
    from app.db import SessionLocal

    with SessionLocal() as session:
        sessions = _list_my_team_sessions(session, player_id)
    return {"sessions": sessions}
