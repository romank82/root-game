"""Командный сервис (шаг 6.4).

Создание команды, вступление, выход, исключение, передача лидерства и
расформирование. Постоянная команда — это сущность Team (шаги 6.1-6.2),
а НЕ TeamSession (временная runtime-сборка под командную миссию этапа 3).
Правило 5.3 (выход при активной командной миссии) стыкует два мира через
team_session_members + team_sessions.status.

Модуль повторяет паттерн fallback_shop.py / mission_engine.py:
чистые функции без FastAPI, атомарные короткие транзакции через
SessionLocal.begin(), entrypoint-обёртки для HTTP-слоя. Идемпотентность —
через unique-индексы team_members (uq_team_members_team_player,
uq_team_members_active_player) и статусы записей; request_id для
player-операций в проекте не используется.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.datetime_utils import ensure_utc
from app.geo_team_runtime_models import TeamSession, TeamSessionMember
from app.models import (
    GamePlayer,
    SystemSetting,
    Team,
    TeamInvitation,
    TeamJoinRequest,
    TeamMember,
    TeamMembershipHistory,
)
from app.player_restrictions_engine import recompute_player_status
from app.system_settings_catalog import get_definition

TEAM_STATUS_ACTIVE = "active"
TEAM_STATUS_DISBANDED = "disbanded"
MEMBER_STATUS_ACTIVE = "active"
MEMBER_STATUS_LEFT = "left"
ROLE_LEADER = "leader"
ROLE_MEMBER = "member"
VALID_JOIN_POLICIES = frozenset({"open", "by_request", "invite_only"})
NAME_MIN = 1
NAME_MAX = 128
DESC_MAX = 10_000
EMBLEM_MAX = 2048

# Правило 5.3 (configurable policy, безопасный дефолт из roadmap §5.3):
# эти статусы team_session блокируют leave/disband — участник в них
# задействован в активной командной миссии.
SESSION_BLOCKING_STATUSES = frozenset({"collecting", "ready_to_start", "active"})

# ---- Статусы приглашений и заявок (шаг 6.5) -------------------------------
INVITATION_STATUS_PENDING = "pending"
INVITATION_STATUS_ACCEPTED = "accepted"
INVITATION_STATUS_REJECTED = "rejected"
INVITATION_STATUS_EXPIRED = "expired"
INVITATION_STATUS_CANCELLED = "cancelled"

JOIN_REQUEST_STATUS_PENDING = "pending"
JOIN_REQUEST_STATUS_ACCEPTED = "accepted"
JOIN_REQUEST_STATUS_REJECTED = "rejected"
JOIN_REQUEST_STATUS_CANCELLED = "cancelled"

INVITE_MESSAGE_MAX = 2000
JOIN_REQUEST_MESSAGE_MAX = 2000

# Дефолт TTL приглашения (часы). CMS-first: значение переопределяется
# системной настройкой "invite.ttl_hours" — см. _invitation_ttl_hours.
DEFAULT_INVITATION_TTL_HOURS = 72

# Маркер "значение не передано" для update_team: позволяет отличить отказ
# от изменения от намеренного null (в V1 null через API не проходит).
_UNSET = object()


def _mission_error(status_code: int, detail: str) -> "MissionEngineError":
    """Ожидаемая ошибка игрового API (ленивый импорт, как в fallback_shop)."""
    from app.mission_engine import MissionEngineError

    return MissionEngineError(status_code, detail)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _read_setting(session: Session, key: str):
    """Значение активной настройки либо default из каталога (CMS-first).

    Резерв для будущих шагов (6.5/6.7): дефолты лимитов команд живут
    в system_settings, а не в коде.
    """
    row = session.get(SystemSetting, key)
    if row is not None:
        return row.value_json

    definition = get_definition(key)
    return definition.default_value if definition is not None else None


# ---- Валидация профиля команды -------------------------------------------
def _validate_name(name: str) -> None:
    if not isinstance(name, str) or not (NAME_MIN <= len(name) <= NAME_MAX):
        raise _mission_error(
            400,
            f"Название команды должно быть от {NAME_MIN} до {NAME_MAX} символов.",
        )


def _validate_team_profile(
    name: str,
    description: str | None,
    emblem_url: str | None,
    join_policy: str,
    max_members: int | None,
) -> None:
    _validate_name(name)
    if description is not None and len(description) > DESC_MAX:
        raise _mission_error(
            400,
            f"Описание команды не может быть длиннее {DESC_MAX} символов.",
        )
    if emblem_url is not None and len(emblem_url) > EMBLEM_MAX:
        raise _mission_error(
            400,
            f"Ссылка на эмблему не может быть длиннее {EMBLEM_MAX} символов.",
        )
    if join_policy not in VALID_JOIN_POLICIES:
        raise _mission_error(400, f"Недопустимый режим вступления: {join_policy}")
    if max_members is not None and (
        not isinstance(max_members, int)
        or isinstance(max_members, bool)
        or max_members < 1
    ):
        raise _mission_error(
            400,
            "Лимит участников должен быть положительным целым числом.",
        )


# ---- Общие хелперы -------------------------------------------------------
def _ensure_player(session: Session, player_id: str) -> GamePlayer:
    """Игрок существует и активен; lazy-рикавери статуса (шаг 5.7).

    Дублирует mission_engine._ensure_player: HTTP-гейт get_current_player_id
    уже отсекает неактивных игроков, но сервис защищается и за пределами
    HTTP (прямые вызовы, тесты, будущие кросс-сервисные операции).
    """
    player = session.get(GamePlayer, player_id)

    if player is None:
        raise _mission_error(404, "Игрок не найден.")

    if player.status != "active":
        # PlayerRestriction — источник истины, GamePlayer.status — кэш.
        recompute_player_status(session, player)
        if player.status != "active":
            raise _mission_error(403, "Игровой профиль неактивен.")

    return player


def _get_active_team(session: Session, team_id: str) -> Team:
    team = session.get(Team, team_id)
    if team is None or team.status != TEAM_STATUS_ACTIVE:
        raise _mission_error(404, "Команда не найдена.")
    return team


def _require_active_team_membership(
    session: Session,
    player_id: str,
    team_id: str | None = None,
) -> tuple[Team, TeamMember]:
    """Активная команда игрока + его активное членство.

    team_id фильтрует по конкретной команде: если игрок состоит в другой
    команде (или ни в одной) — 404 «Команда не найдена».
    """
    row = session.execute(
        select(Team, TeamMember)
        .join(TeamMember, TeamMember.team_id == Team.id)
        .where(
            TeamMember.player_id == player_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
            Team.status == TEAM_STATUS_ACTIVE,
        )
    ).first()

    if row is None or (team_id is not None and row[0].id != team_id):
        raise _mission_error(404, "Команда не найдена.")

    return row[0], row[1]


def _ensure_leader(team: Team, player_id: str) -> None:
    if team.leader_id != player_id:
        raise _mission_error(403, "Только лидер команды может выполнить это действие.")


def _has_active_team_session(session: Session, player_id: str) -> bool:
    """Правило 5.3: участвует ли игрок в активной командной миссии."""
    row = session.scalar(
        select(TeamSessionMember.id)
        .join(TeamSession, TeamSession.id == TeamSessionMember.team_session_id)
        .where(
            TeamSessionMember.player_id == player_id,
            TeamSession.status.in_(SESSION_BLOCKING_STATUSES),
        )
        .limit(1)
    )
    return row is not None


def _record_history(
    session: Session,
    *,
    team_id: str,
    player_id: str,
    event_type: str,
    actor_player_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Одна immutable-запись истории состава (шаг 6.2)."""
    session.add(
        TeamMembershipHistory(
            id=_new_id("team-history"),
            team_id=team_id,
            player_id=player_id,
            event_type=event_type,
            actor_player_id=actor_player_id,
            metadata_json=metadata if metadata is not None else {},
        )
    )


def _serialize_team(session: Session, team: Team) -> dict:
    """Только публичные данные для клиента: команда + leader + active-состав."""
    members = session.scalars(
        select(TeamMember)
        .where(
            TeamMember.team_id == team.id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
        .order_by(TeamMember.joined_at)
    ).all()
    leader = session.get(GamePlayer, team.leader_id)

    return {
        "id": team.id,
        "name": team.name,
        "description": team.description,
        "emblemUrl": team.emblem_url,
        "status": team.status,
        "joinPolicy": team.join_policy,
        "maxMembers": team.max_members,
        "memberCount": len(members),
        "leader": {
            "id": team.leader_id,
            "displayName": leader.display_name if leader is not None else None,
        },
        "members": [
            {
                "id": member.player_id,
                "role": member.role,
                "joinedAt": member.joined_at.isoformat() if member.joined_at else None,
            }
            for member in members
        ],
    }


# ---- Создание команды ----------------------------------------------------
def _create_team(
    session: Session,
    player_id: str,
    *,
    name: str,
    description: str | None = None,
    emblem_url: str | None = None,
    join_policy: str = "by_request",
    max_members: int | None = None,
) -> dict:
    _ensure_player(session, player_id)
    _validate_team_profile(name, description, emblem_url, join_policy, max_members)

    existing = session.scalar(
        select(TeamMember).where(
            TeamMember.player_id == player_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    if existing is not None:
        raise _mission_error(409, "Игрок уже состоит в активной команде.")

    team = Team(
        id=_new_id("team"),
        name=name,
        description=description,
        emblem_url=emblem_url,
        leader_id=player_id,
        status=TEAM_STATUS_ACTIVE,
        join_policy=join_policy,
        max_members=max_members,
    )
    session.add(team)
    session.flush()

    session.add(
        TeamMember(
            id=_new_id("team-member"),
            team_id=team.id,
            player_id=player_id,
            role=ROLE_LEADER,
            status=MEMBER_STATUS_ACTIVE,
            joined_at=_utcnow(),
        )
    )
    _record_history(
        session,
        team_id=team.id,
        player_id=player_id,
        event_type="joined",
        actor_player_id=player_id,
    )
    session.flush()

    return _serialize_team(session, team)


def create_team_entrypoint(
    player_id: str,
    *,
    name: str,
    description: str | None = None,
    emblem_url: str | None = None,
    join_policy: str = "by_request",
    max_members: int | None = None,
) -> dict:
    """Точка вызова из HTTP-слоя: создать команду в одной транзакции."""
    with SessionLocal.begin() as session:
        return _create_team(
            session,
            player_id,
            name=name,
            description=description,
            emblem_url=emblem_url,
            join_policy=join_policy,
            max_members=max_members,
        )


# ---- Чтение -------------------------------------------------------------
def get_my_team(player_id: str) -> dict | None:
    """Активная команда игрока либо None (не состоит ни в одной)."""
    with SessionLocal() as session:
        row = session.execute(
            select(Team, TeamMember)
            .join(TeamMember, TeamMember.team_id == Team.id)
            .where(
                TeamMember.player_id == player_id,
                TeamMember.status == MEMBER_STATUS_ACTIVE,
                Team.status == TEAM_STATUS_ACTIVE,
            )
        ).first()
        if row is None:
            return None
        return _serialize_team(session, row[0])


def get_team(team_id: str, requester_id: str) -> dict:
    """Публичная карточка команды; расформированные команды недоступны."""
    with SessionLocal() as session:
        team = _get_active_team(session, team_id)
        return _serialize_team(session, team)


# ---- Обновление профиля команды ------------------------------------------
def _update_team(
    session: Session,
    player_id: str,
    team_id: str,
    *,
    name=_UNSET,
    description=_UNSET,
    emblem_url=_UNSET,
    join_policy=_UNSET,
    max_members=_UNSET,
) -> dict:
    team, _membership = _require_active_team_membership(session, player_id, team_id)
    _ensure_leader(team, player_id)

    if name is not _UNSET:
        _validate_name(name)
        team.name = name
    if description is not _UNSET:
        if description is not None and len(description) > DESC_MAX:
            raise _mission_error(
                400,
                f"Описание команды не может быть длиннее {DESC_MAX} символов.",
            )
        team.description = description
    if emblem_url is not _UNSET:
        if emblem_url is not None and len(emblem_url) > EMBLEM_MAX:
            raise _mission_error(
                400,
                f"Ссылка на эмблему не может быть длиннее {EMBLEM_MAX} символов.",
            )
        team.emblem_url = emblem_url
    if join_policy is not _UNSET:
        if join_policy not in VALID_JOIN_POLICIES:
            raise _mission_error(400, f"Недопустимый режим вступления: {join_policy}")
        team.join_policy = join_policy
    if max_members is not _UNSET:
        if max_members is not None and (
            not isinstance(max_members, int)
            or isinstance(max_members, bool)
            or max_members < 1
        ):
            raise _mission_error(
                400,
                "Лимит участников должен быть положительным целым числом.",
            )
        team.max_members = max_members

    session.flush()
    return _serialize_team(session, team)


def update_team_entrypoint(player_id: str, team_id: str, **changes) -> dict:
    """Точка вызова из HTTP-слоя: PATCH профиля команды (только лидер)."""
    with SessionLocal.begin() as session:
        return _update_team(session, player_id, team_id, **changes)


# ---- Вступление ----------------------------------------------------------
def _join_team(session: Session, player_id: str, team_id: str) -> dict:
    _ensure_player(session, player_id)

    existing = session.scalar(
        select(TeamMember).where(
            TeamMember.player_id == player_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    if existing is not None:
        raise _mission_error(409, "Игрок уже состоит в активной команде.")

    team = _get_active_team(session, team_id)

    if team.join_policy == "by_request":
        raise _mission_error(
            409,
            "Вступление по заявке. "
            f"Используйте POST /api/v1/engine/teams/{team_id}/join-requests.",
        )
    if team.join_policy == "invite_only":
        raise _mission_error(
            409,
            "Режим «только по приглашению»: "
            "приглашение должен отправить лидер команды.",
        )

    active_count = session.scalar(
        select(func.count())
        .select_from(TeamMember)
        .where(
            TeamMember.team_id == team.id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    if team.max_members is not None and active_count >= team.max_members:
        raise _mission_error(409, "Команда заполнена.")

    previous = session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.player_id == player_id,
        )
    )
    if previous is None:
        session.add(
            TeamMember(
                id=_new_id("team-member"),
                team_id=team.id,
                player_id=player_id,
                role=ROLE_MEMBER,
                status=MEMBER_STATUS_ACTIVE,
                joined_at=_utcnow(),
            )
        )
    else:
        # Реактивация прежнего членства: uq_team_members_team_player запрещает
        # второй INSERT по паре (team_id, player_id) — игрок не может быть
        # «второй раз новым» в одной команде.
        previous.status = MEMBER_STATUS_ACTIVE
        previous.left_at = None
        previous.joined_at = _utcnow()
        if previous.role != ROLE_LEADER:
            previous.role = ROLE_MEMBER

    _record_history(
        session,
        team_id=team.id,
        player_id=player_id,
        event_type="joined",
        actor_player_id=player_id,
    )
    session.flush()

    return _serialize_team(session, team)


def join_team_entrypoint(player_id: str, team_id: str) -> dict:
    """Точка вызова из HTTP-слоя: вступить в команду с открытым набором."""
    with SessionLocal.begin() as session:
        return _join_team(session, player_id, team_id)


# ---- Выход ---------------------------------------------------------------
def _leave_team(session: Session, player_id: str, team_id: str) -> None:
    _ensure_player(session, player_id)
    team, membership = _require_active_team_membership(session, player_id, team_id)

    if _has_active_team_session(session, player_id):
        raise _mission_error(
            409,
            "Нельзя выйти из команды во время активной командной миссии.",
        )

    if membership.role == ROLE_LEADER:
        raise _mission_error(
            409,
            "Лидер не может выйти: передайте лидерство или расформируйте команду.",
        )

    membership.status = MEMBER_STATUS_LEFT
    membership.left_at = _utcnow()
    _record_history(
        session,
        team_id=team.id,
        player_id=player_id,
        event_type="left",
        actor_player_id=player_id,
    )
    session.flush()


def leave_team_entrypoint(player_id: str, team_id: str) -> None:
    """Точка вызова из HTTP-слоя: выйти из команды."""
    with SessionLocal.begin() as session:
        _leave_team(session, player_id, team_id)


# ---- Исключение ----------------------------------------------------------
def _kick_member(
    session: Session,
    leader_id: str,
    team_id: str,
    target_player_id: str,
) -> None:
    team, _membership = _require_active_team_membership(
        session, leader_id, team_id
    )
    _ensure_leader(team, leader_id)

    if target_player_id == leader_id:
        raise _mission_error(409, "Нельзя исключить себя.")

    target = session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.player_id == target_player_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    if target is None:
        raise _mission_error(404, "Участник не найден.")

    target.status = MEMBER_STATUS_LEFT
    target.left_at = _utcnow()
    _record_history(
        session,
        team_id=team.id,
        player_id=target_player_id,
        event_type="kicked",
        actor_player_id=leader_id,
        metadata={"reason": None},
    )
    session.flush()


def kick_member_entrypoint(
    leader_id: str,
    team_id: str,
    target_player_id: str,
) -> None:
    """Точка вызова из HTTP-слоя: исключить участника (только лидер)."""
    with SessionLocal.begin() as session:
        _kick_member(session, leader_id, team_id, target_player_id)


# ---- Передача лидерства --------------------------------------------------
def _transfer_leadership(
    session: Session,
    leader_id: str,
    team_id: str,
    new_leader_id: str,
) -> None:
    team, _membership = _require_active_team_membership(
        session, leader_id, team_id
    )
    _ensure_leader(team, leader_id)

    if new_leader_id == leader_id:
        raise _mission_error(409, "Новый лидер уже является лидером команды.")

    new_leader = session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.player_id == new_leader_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    if new_leader is None:
        raise _mission_error(409, "Новый лидер должен быть активным участником команды.")

    old_leader = session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.player_id == leader_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    old_leader.role = ROLE_MEMBER
    new_leader.role = ROLE_LEADER
    team.leader_id = new_leader_id

    _record_history(
        session,
        team_id=team.id,
        player_id=leader_id,
        event_type="leadership_transferred",
        actor_player_id=leader_id,
        metadata={"newLeaderId": new_leader_id},
    )
    session.flush()


def transfer_leadership_entrypoint(
    leader_id: str,
    team_id: str,
    new_leader_id: str,
) -> None:
    """Точка вызова из HTTP-слоя: передача лидерства (атомарно)."""
    with SessionLocal.begin() as session:
        _transfer_leadership(session, leader_id, team_id, new_leader_id)


# ---- Расформирование -----------------------------------------------------
def _disband_team(session: Session, leader_id: str, team_id: str) -> None:
    team, _membership = _require_active_team_membership(
        session, leader_id, team_id
    )
    _ensure_leader(team, leader_id)

    # Правило 5.3 для всех участников: команду нельзя распустить, пока любой
    # участник задействован в активной командной миссии.
    active_member_ids = select(TeamMember.player_id).where(
        TeamMember.team_id == team.id,
        TeamMember.status == MEMBER_STATUS_ACTIVE,
    )
    blocker = session.scalar(
        select(TeamSessionMember.id)
        .join(TeamSession, TeamSession.id == TeamSessionMember.team_session_id)
        .where(
            TeamSessionMember.player_id.in_(active_member_ids),
            TeamSession.status.in_(SESSION_BLOCKING_STATUSES),
        )
        .limit(1)
    )
    if blocker is not None:
        raise _mission_error(
            409,
            "Нельзя расформировать команду, пока участник "
            "в активной командной миссии.",
        )

    members = session.scalars(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    ).all()

    team.status = TEAM_STATUS_DISBANDED
    for member in members:
        member.status = MEMBER_STATUS_LEFT
        member.left_at = _utcnow()
        _record_history(
            session,
            team_id=team.id,
            player_id=member.player_id,
            event_type="disbanded",
            actor_player_id=leader_id,
        )
    session.flush()


def disband_team_entrypoint(leader_id: str, team_id: str) -> None:
    """Точка вызова из HTTP-слоя: расформировать команду (только лидер)."""
    with SessionLocal.begin() as session:
        _disband_team(session, leader_id, team_id)


# ============================================================================
# Приглашения и заявки (шаг 6.5)
# ----------------------------------------------------------------------------
# Приглашения инициирует лидер (invite -> accept/reject/cancel); заявки —
# игрок (create -> approve/reject лидером или cancel автором). Статус-машины
# соответствуют CheckConstraint'ам моделей (6.2). Partial-unique индексы
# uq_team_invitations_pending / uq_team_join_requests_pending страхуют "одна
# pending на пару" на уровне БД, сервис дополнительно даёт чистые 409.
# ============================================================================


def _invitation_ttl_hours(session: Session) -> int:
    """TTL приглашения в часах: system setting "invite.ttl_hours" (CMS-first)
    либо безопасный дефолт DEFAULT_INVITATION_TTL_HOURS."""
    value = _read_setting(session, "invite.ttl_hours")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > 0
    ):
        return int(value)
    return DEFAULT_INVITATION_TTL_HOURS


def _ensure_not_in_active_team(session: Session, player_id: str) -> None:
    """Guard: игрок не состоит в активной команде (любой)."""
    existing = session.scalar(
        select(TeamMember).where(
            TeamMember.player_id == player_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    if existing is not None:
        raise _mission_error(409, "Игрок уже состоит в активной команде.")


def _team_is_full(session: Session, team: Team) -> bool:
    """Team.max_members задан и достигнут числом активных участников."""
    active_count = session.scalar(
        select(func.count())
        .select_from(TeamMember)
        .where(
            TeamMember.team_id == team.id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    return team.max_members is not None and active_count >= team.max_members


def _activate_membership(
    session: Session,
    *,
    team_id: str,
    player_id: str,
) -> None:
    """Реактивация прежней записи TeamMember либо INSERT нового членства.

    Тот же паттерн, что в _join_team (6.4): uq_team_members_team_player
    запрещает дубликаты, поэтому бывший участник возвращается без новых строк.
    """
    previous = session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.player_id == player_id,
        )
    )
    if previous is None:
        session.add(
            TeamMember(
                id=_new_id("team-member"),
                team_id=team_id,
                player_id=player_id,
                role=ROLE_MEMBER,
                status=MEMBER_STATUS_ACTIVE,
                joined_at=_utcnow(),
            )
        )
    else:
        previous.status = MEMBER_STATUS_ACTIVE
        previous.left_at = None
        previous.joined_at = _utcnow()
        if previous.role != ROLE_LEADER:
            previous.role = ROLE_MEMBER


def _lazy_expire(session: Session, invitation: TeamInvitation) -> None:
    """Ленивое протухание pending-приглашения, если срок уже прошёл.

    Вызывается перед проверкой статуса в accept/reject/cancel/list.
    """
    expires_at = getattr(invitation, "expires_at", None)
    if (
        invitation.status == INVITATION_STATUS_PENDING
        and expires_at is not None
        and ensure_utc(expires_at) < _utcnow()
    ):
        invitation.status = INVITATION_STATUS_EXPIRED
        invitation.responded_at = _utcnow()
        session.flush()


def _ensure_pending(
    status: str,
    allowed_pending: str,
    error_message: str,
) -> None:
    """Guard: текущий статус должен быть pending, иначе 409."""
    if status != allowed_pending:
        raise _mission_error(409, error_message)


def _serialize_invitation(invitation: TeamInvitation) -> dict:
    return {
        "id": invitation.id,
        "teamId": invitation.team_id,
        "invitedPlayerId": invitation.invited_player_id,
        "invitedByPlayerId": invitation.invited_by_player_id,
        "status": invitation.status,
        "message": invitation.message,
        "expiresAt": (
            invitation.expires_at.isoformat() if invitation.expires_at else None
        ),
        "respondedAt": (
            invitation.responded_at.isoformat() if invitation.responded_at else None
        ),
    }


def _serialize_join_request(request: TeamJoinRequest) -> dict:
    return {
        "id": request.id,
        "teamId": request.team_id,
        "playerId": request.player_id,
        "status": request.status,
        "message": request.message,
        "respondedByPlayerId": request.responded_by_player_id,
        "respondedAt": (
            request.responded_at.isoformat() if request.responded_at else None
        ),
    }


# ---- Приглашение (инициирует лидер) ---------------------------------------
def _invite_player(
    session: Session,
    leader_id: str,
    team_id: str,
    target_player_id: str,
    *,
    message: str | None = None,
    ttl_hours: int | None = None,
) -> dict:
    if message is not None and len(message) > INVITE_MESSAGE_MAX:
        raise _mission_error(
            400,
            f"Сообщение приглашения не может быть длиннее "
            f"{INVITE_MESSAGE_MAX} символов.",
        )

    team, _membership = _require_active_team_membership(session, leader_id, team_id)
    _ensure_leader(team, leader_id)

    if target_player_id == leader_id:
        raise _mission_error(409, "Нельзя пригласить самого себя.")

    _ensure_not_in_active_team(session, target_player_id)

    duplicate = session.scalar(
        select(TeamInvitation).where(
            TeamInvitation.team_id == team.id,
            TeamInvitation.invited_player_id == target_player_id,
            TeamInvitation.status == INVITATION_STATUS_PENDING,
        )
    )
    if duplicate is not None:
        raise _mission_error(
            409,
            "Этому игроку уже отправлено активное приглашение.",
        )

    if _team_is_full(session, team):
        raise _mission_error(409, "Команда заполнена.")

    if ttl_hours is None:
        ttl_hours = _invitation_ttl_hours(session)
    if (
        not isinstance(ttl_hours, int)
        or isinstance(ttl_hours, bool)
        or ttl_hours < 1
    ):
        raise _mission_error(
            400,
            "TTL приглашения должен быть положительным целым числом (часы).",
        )

    invitation = TeamInvitation(
        id=_new_id("invitation"),
        team_id=team.id,
        invited_player_id=target_player_id,
        invited_by_player_id=leader_id,
        status=INVITATION_STATUS_PENDING,
        message=message,
        expires_at=_utcnow() + timedelta(hours=ttl_hours),
    )
    session.add(invitation)
    session.flush()

    return _serialize_invitation(invitation)


def invite_player_entrypoint(
    leader_id: str,
    team_id: str,
    target_player_id: str,
    *,
    message: str | None = None,
    ttl_hours: int | None = None,
) -> dict:
    """Точка вызова из HTTP-слоя: пригласить игрока (только лидер)."""
    with SessionLocal.begin() as session:
        return _invite_player(
            session,
            leader_id,
            team_id,
            target_player_id,
            message=message,
            ttl_hours=ttl_hours,
        )


# ---- Список и ответ на приглашения ----------------------------------------
def get_my_invitations(player_id: str) -> list[dict]:
    """Все pending-приглашения игрока (просроченные исключаются).

    begin() вместо простого SessionLocal(): ленивый _lazy_expire — это
    write, поэтому транзакция должна завершаться commit (а не rollback).
    """
    with SessionLocal.begin() as session:
        invitations = session.scalars(
            select(TeamInvitation)
            .where(
                TeamInvitation.invited_player_id == player_id,
                TeamInvitation.status == INVITATION_STATUS_PENDING,
            )
            .order_by(TeamInvitation.created_at.desc())
        ).all()

        result: list[dict] = []
        for invitation in invitations:
            _lazy_expire(session, invitation)
            if invitation.status == INVITATION_STATUS_PENDING:
                result.append(_serialize_invitation(invitation))
        return result


def _accept_invitation(
    session: Session,
    player_id: str,
    invitation_id: str,
) -> dict:
    _ensure_player(session, player_id)

    # SELECT ... FOR UPDATE в PostgreSQL; в SQLite — обычный SELECT
    # (транзакция уже сериализует запись).
    invitation = session.get(TeamInvitation, invitation_id)
    if invitation is None or invitation.invited_player_id != player_id:
        raise _mission_error(404, "Приглашение не найдено.")

    _lazy_expire(session, invitation)
    _ensure_pending(
        invitation.status,
        INVITATION_STATUS_PENDING,
        "Приглашение уже обработано или просрочено.",
    )

    _ensure_not_in_active_team(session, player_id)
    team = _get_active_team(session, invitation.team_id)
    if _team_is_full(session, team):
        raise _mission_error(409, "Команда заполнена.")

    _activate_membership(session, team_id=team.id, player_id=player_id)
    invitation.status = INVITATION_STATUS_ACCEPTED
    invitation.responded_at = _utcnow()
    _record_history(
        session,
        team_id=team.id,
        player_id=player_id,
        event_type="joined",
        actor_player_id=player_id,
        metadata={"via": "invitation", "invitationId": invitation.id},
    )
    session.flush()

    return _serialize_team(session, team)


def accept_invitation_entrypoint(player_id: str, invitation_id: str) -> dict:
    """Точка вызова из HTTP-слоя: принять приглашение."""
    with SessionLocal.begin() as session:
        return _accept_invitation(session, player_id, invitation_id)


def _reject_invitation(
    session: Session,
    player_id: str,
    invitation_id: str,
) -> None:
    invitation = session.get(TeamInvitation, invitation_id)
    if invitation is None or invitation.invited_player_id != player_id:
        raise _mission_error(404, "Приглашение не найдено.")

    _lazy_expire(session, invitation)
    _ensure_pending(
        invitation.status,
        INVITATION_STATUS_PENDING,
        "Приглашение уже обработано или просрочено.",
    )

    invitation.status = INVITATION_STATUS_REJECTED
    invitation.responded_at = _utcnow()
    session.flush()


def reject_invitation_entrypoint(player_id: str, invitation_id: str) -> None:
    """Точка вызова из HTTP-слоя: отклонить приглашение."""
    with SessionLocal.begin() as session:
        _reject_invitation(session, player_id, invitation_id)


def _cancel_invitation(
    session: Session,
    leader_id: str,
    team_id: str,
    invitation_id: str,
) -> None:
    team, _membership = _require_active_team_membership(session, leader_id, team_id)
    _ensure_leader(team, leader_id)

    invitation = session.get(TeamInvitation, invitation_id)
    if invitation is None or invitation.team_id != team.id:
        raise _mission_error(404, "Приглашение не найдено.")

    _lazy_expire(session, invitation)
    _ensure_pending(
        invitation.status,
        INVITATION_STATUS_PENDING,
        "Приглашение уже обработано или просрочено.",
    )

    invitation.status = INVITATION_STATUS_CANCELLED
    invitation.responded_at = _utcnow()
    session.flush()


def cancel_invitation_entrypoint(
    leader_id: str,
    team_id: str,
    invitation_id: str,
) -> None:
    """Точка вызова из HTTP-слоя: отозвать приглашение (только лидер)."""
    with SessionLocal.begin() as session:
        _cancel_invitation(session, leader_id, team_id, invitation_id)


# ---- Заявка на вступление (инициирует игрок) ------------------------------
def _create_join_request(
    session: Session,
    player_id: str,
    team_id: str,
    *,
    message: str | None = None,
) -> dict:
    _ensure_player(session, player_id)
    if message is not None and len(message) > JOIN_REQUEST_MESSAGE_MAX:
        raise _mission_error(
            400,
            f"Сообщение заявки не может быть длиннее "
            f"{JOIN_REQUEST_MESSAGE_MAX} символов.",
        )

    _ensure_not_in_active_team(session, player_id)
    team = _get_active_team(session, team_id)

    if team.join_policy == "open":
        raise _mission_error(
            409,
            "Режим открытого набора: вступайте напрямую через "
            f"POST /api/v1/engine/teams/{team_id}/join.",
        )
    if team.join_policy == "invite_only":
        raise _mission_error(
            409,
            "Режим «только по приглашению»: "
            "приглашение должен отправить лидер команды.",
        )

    duplicate = session.scalar(
        select(TeamJoinRequest).where(
            TeamJoinRequest.team_id == team.id,
            TeamJoinRequest.player_id == player_id,
            TeamJoinRequest.status == JOIN_REQUEST_STATUS_PENDING,
        )
    )
    if duplicate is not None:
        raise _mission_error(
            409,
            "Заявка в эту команду уже отправлена и ожидает решения.",
        )

    request = TeamJoinRequest(
        id=_new_id("join-request"),
        team_id=team.id,
        player_id=player_id,
        status=JOIN_REQUEST_STATUS_PENDING,
        message=message,
    )
    session.add(request)
    session.flush()

    return _serialize_join_request(request)


def create_join_request_entrypoint(
    player_id: str,
    team_id: str,
    *,
    message: str | None = None,
) -> dict:
    """Точка вызова из HTTP-слоя: подать заявку на вступление."""
    with SessionLocal.begin() as session:
        return _create_join_request(session, player_id, team_id, message=message)


def get_my_join_requests(player_id: str) -> list[dict]:
    """Все pending-заявки игрока (по всем командам)."""
    with SessionLocal() as session:
        requests = session.scalars(
            select(TeamJoinRequest)
            .where(
                TeamJoinRequest.player_id == player_id,
                TeamJoinRequest.status == JOIN_REQUEST_STATUS_PENDING,
            )
            .order_by(TeamJoinRequest.created_at.desc())
        ).all()
        return [_serialize_join_request(request) for request in requests]


def _cancel_join_request(
    session: Session,
    player_id: str,
    request_id: str,
) -> None:
    request = session.get(TeamJoinRequest, request_id)
    if request is None or request.player_id != player_id:
        raise _mission_error(404, "Заявка не найдена.")

    _ensure_pending(
        request.status,
        JOIN_REQUEST_STATUS_PENDING,
        "Заявка уже обработана.",
    )

    request.status = JOIN_REQUEST_STATUS_CANCELLED
    request.responded_at = _utcnow()
    session.flush()


def cancel_join_request_entrypoint(player_id: str, request_id: str) -> None:
    """Точка вызова из HTTP-слоя: отозвать свою заявку."""
    with SessionLocal.begin() as session:
        _cancel_join_request(session, player_id, request_id)


def get_team_join_requests(
    leader_id: str,
    team_id: str,
    *,
    status: str = "pending",
) -> list[dict]:
    """Заявки команды (видит только лидер; по умолчанию — pending)."""
    with SessionLocal() as session:
        team, _membership = _require_active_team_membership(
            session, leader_id, team_id
        )
        _ensure_leader(team, leader_id)
        requests = session.scalars(
            select(TeamJoinRequest)
            .where(
                TeamJoinRequest.team_id == team.id,
                TeamJoinRequest.status == status,
            )
            .order_by(TeamJoinRequest.created_at.desc())
        ).all()
        return [_serialize_join_request(request) for request in requests]


def _approve_join_request(
    session: Session,
    leader_id: str,
    team_id: str,
    request_id: str,
) -> dict:
    team, _membership = _require_active_team_membership(session, leader_id, team_id)
    _ensure_leader(team, leader_id)

    request = session.get(TeamJoinRequest, request_id)
    if request is None or request.team_id != team.id:
        raise _mission_error(404, "Заявка не найдена.")

    _ensure_pending(
        request.status,
        JOIN_REQUEST_STATUS_PENDING,
        "Заявка уже обработана.",
    )

    _ensure_not_in_active_team(session, request.player_id)
    team = _get_active_team(session, team.id)
    if _team_is_full(session, team):
        raise _mission_error(409, "Команда заполнена.")

    _activate_membership(session, team_id=team.id, player_id=request.player_id)
    request.status = JOIN_REQUEST_STATUS_ACCEPTED
    request.responded_by_player_id = leader_id
    request.responded_at = _utcnow()
    _record_history(
        session,
        team_id=team.id,
        player_id=request.player_id,
        event_type="joined",
        actor_player_id=leader_id,
        metadata={"via": "join_request", "requestId": request.id},
    )
    session.flush()

    return _serialize_team(session, team)


def approve_join_request_entrypoint(
    leader_id: str,
    team_id: str,
    request_id: str,
) -> dict:
    """Точка вызова из HTTP-слоя: одобрить заявку (только лидер)."""
    with SessionLocal.begin() as session:
        return _approve_join_request(session, leader_id, team_id, request_id)


def _reject_join_request(
    session: Session,
    leader_id: str,
    team_id: str,
    request_id: str,
) -> None:
    team, _membership = _require_active_team_membership(session, leader_id, team_id)
    _ensure_leader(team, leader_id)

    request = session.get(TeamJoinRequest, request_id)
    if request is None or request.team_id != team.id:
        raise _mission_error(404, "Заявка не найдена.")

    _ensure_pending(
        request.status,
        JOIN_REQUEST_STATUS_PENDING,
        "Заявка уже обработана.",
    )

    request.status = JOIN_REQUEST_STATUS_REJECTED
    request.responded_by_player_id = leader_id
    request.responded_at = _utcnow()
    session.flush()


def reject_join_request_entrypoint(
    leader_id: str,
    team_id: str,
    request_id: str,
) -> None:
    """Точка вызова из HTTP-слоя: отклонить заявку (только лидер)."""
    with SessionLocal.begin() as session:
        _reject_join_request(session, leader_id, team_id, request_id)