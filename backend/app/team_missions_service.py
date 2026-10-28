"""Командные миссии (этап 7.1): командные сессии игрока.

7.1.a — list_my_team_sessions_entrypoint: чтение активных командных сессий
        игрока (только SELECT, сортировка createdAt DESC);
7.1.b — create_team_session_entrypoint: создание временной командной сессии
        любым игроком (без постоянной Team и без лидера). Все переменные
        игры (minMembers/maxMembers и др.) берутся из validation_config.
7.1.b-2 — join_team_session: присоединение игрока к сессии в состоянии
        сбора (создание MissionRun + TeamSessionMember, лимит состава из
        effective_config_snapshot).
7.1.c — mark_ready_entrypoint: подтверждение готовности участника со
        списанием entryFee и расходуемых ключей (ядро _apply_entry_debit,
        правила из validation_config.economy); когда готовы все активные
        участники — сессия переходит в ready_to_start, а при свежих
        гео-proof у всех — авто-старт в active (без лидера).

Модуль повторяет паттерн teams_service.py: чистые функции без FastAPI,
короткие транзакции через SessionLocal(), entrypoint-обёртки для HTTP-слоя,
ленивые импорты внутри функций. Ошибки — MissionEngineError (см. _mission_error).
"""

from __future__ import annotations

import math

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.country_policy import is_feature_restricted
from app.geo_country import resolve_country_or_none

# Активные командные сессии — в этих статусах игрок задействован в миссии.
ACTIVE_SESSION_STATUSES = frozenset({"collecting", "ready_to_start", "active"})

# Активные участники сессии (членство ещё действует, не left/removed/settled).
ACTIVE_MEMBER_STATUSES = frozenset({"joined", "ready"})

# Зеркала констант команд (без кросс-импорта teams_service).
TEAM_STATUS_ACTIVE = "active"
MEMBER_STATUS_ACTIVE = "active"

# Статус per-player MissionRun при создании командной сессии (7.1.b).
# Валиден по ck_mission_runs_status; тот же, что используют тесты 7.1.a
# в _make_session/_add_session_member.
MISSION_RUN_STATUS_ACTIVE = "active"

# ---- 7.1.d: гео-присутствие ---------------------------------------------
# Dev-режим сам выступает trusted verifier; для prod появится внешний verifier.
# Эти константы — единственное место смены провайдера при переходе на prod.
DEV_LOCATION_PROOF_PROVIDER = "dev_mock"
LOCATION_PROOF_STATUS_VERIFIED = "verified"
LOCATION_PROOF_STATUS_REJECTED = "rejected"
SUPPORTED_ZONE_TYPES = frozenset({"radius"})  # polygon/poi — позже


def _mission_error(status_code: int, detail: str) -> Exception:
    """Ожидаемая ошибка игрового API (ленивый импорт, как в teams_service)."""
    from app.mission_engine import MissionEngineError

    return MissionEngineError(status_code, detail)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _serialize_team_session(
    session: Session,
    team_session,
    player_id: str,
) -> dict:
    """Сериализация TeamSession для игрока. Используется в 7.1.a и 7.1.b.

    Только SELECT: заголовок миссии (без content/validation_config — закрытые
    данные), активные участники для memberCount и членство игрока.
    """
    from app.geo_team_runtime_models import TeamSessionMember
    from app.models import Mission

    mission = session.get(Mission, team_session.mission_id)

    members = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
        )
    ).all()
    my_membership = next(
        (member for member in members if member.player_id == player_id),
        None,
    )
    active_count = sum(
        1 for member in members if member.status in ACTIVE_MEMBER_STATUSES
    )

    return {
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
        "myStatus": my_membership.status if my_membership is not None else None,
        "myReadyAt": (
            my_membership.ready_at.isoformat()
            if my_membership is not None and my_membership.ready_at
            else None
        ),
    }


def _list_my_team_sessions(session: Session, player_id: str) -> list[dict]:
    """Активные TeamSession игрока (только SELECT, сортировка createdAt DESC)."""
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember

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

    return [
        _serialize_team_session(session, team_session, player_id)
        for team_session in team_sessions
    ]


def _create_team_session(
    session: Session,
    player_id: str,
    mission_id: str,
) -> dict:
    """Создать временную командную сессию. Может любой игрок (без Team).

    Сессия стартует с одним участником — создателем (status='joined');
    состав расширяется join-session эндпоинтом (следующий шаг). Все правила
    и количества берутся из validation_config миссии (код не хардкодит
    экономику). 7.1.b не списывает entryFee/ключи (7.1.c), не проверяет
    гео (7.1.d) и не переводит сессию из 'collecting'.
    """
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import MissionRun, TeamSession, TeamSessionMember
    from app.models import GamePlayer, Mission

    # 1. Player существует и активен (паттерн _ensure_player из teams_service).
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 2. Миссия существует, опубликована и командная.
    mission = session.get(Mission, mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(404, "Опубликованная миссия не найдена.")
    if mission.mission_type != "team":
        raise _mission_error(409, "Эта миссия не командная.")

    # 3. validation_config миссии валиден по geo/team-контракту.
    try:
        config = validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")

    # 4. Сессия — временное объединение игроков без привязки к постоянной
    # Team (в TeamSession нет team_id): создатель не обязан быть лидером
    # или состоять в команде. Ограничение — одна активная сессия на игрока.
    active_session_id = session.scalar(
        select(TeamSession.id)
        .join(TeamSessionMember, TeamSessionMember.team_session_id == TeamSession.id)
        .where(
            TeamSessionMember.player_id == player_id,
            TeamSession.status.in_(ACTIVE_SESSION_STATUSES),
        )
        .limit(1)
    )
    if active_session_id is not None:
        raise _mission_error(409, "У вас уже есть активная командная сессия.")


    # Создание (одна транзакция): TeamSession + per-player MissionRun +
    # TeamSessionMember. team_session_members.mission_run_id в БД NOT NULL —
    # обязательный MissionRun создаётся вместе с сессией.
    team_session = TeamSession(
        id=_new_id("team-session"),
        mission_id=mission.id,
        status="collecting",
        effective_config_snapshot=deepcopy(config),
        started_at=None,
        terminal_at=None,
    )
    session.add(team_session)
    session.flush()

    mission_run = MissionRun(
        id=_new_id("mission-run"),
        player_id=player_id,
        mission_id=mission.id,
        team_session_id=team_session.id,
        status=MISSION_RUN_STATUS_ACTIVE,
        effective_config_snapshot=deepcopy(config),
    )
    session.add(mission_run)
    session.flush()
    session.add(
        TeamSessionMember(
            id=_new_id("tsm"),
            team_session_id=team_session.id,
            player_id=player_id,
            mission_run_id=mission_run.id,
            status="joined",
            ready_at=None,
        )
    )

    session.flush()
    return _serialize_team_session(session, team_session, player_id)


def _all_ready_members_have_fresh_geo_proof(
    session: Session,
    members,
    config: dict,
) -> bool:
    """Свежий verified LocationProof у всех переданных участников (зона миссии).

    Единая точка проверки гео-присутствия для авто-старта (_mark_ready) и
    fallback-активации (_activate_session). Только SELECT, без записи.
    proofFreshnessSeconds уже «зашит» в expires_at proof при его создании.
    """
    from app.geo_team_runtime_models import LocationProof

    zone_id = config["geo"]["zoneId"]
    now = _utcnow()

    for member_row in members:
        latest_proof = session.scalar(
            select(LocationProof)
            .where(
                LocationProof.player_id == member_row.player_id,
                LocationProof.status == LOCATION_PROOF_STATUS_VERIFIED,
                LocationProof.zone_id == zone_id,
                LocationProof.expires_at > now,
            )
            .order_by(LocationProof.issued_at.desc())
            .limit(1)
        )
        if latest_proof is None:
            return False

    return True


def _mark_ready(
    session: Session,
    player_id: str,
    session_id: str,
) -> dict:
    """Подтвердить готовность игрока к старту командной миссии (7.1.c).

    Все числа — из mission.validation_config.economy (в коде нет хардкода).
    Списание entryFee и расходуемых ключей — ядро движка _apply_entry_debit
    (policy=None, команда читает validation_config): идемпотентно по
    reference_id=team_session.id и atomic в одной транзакции со сменой
    статусов ниже. Когда все активные участники ('joined'/'ready') стали
    'ready' — сессия переходит collecting → ready_to_start, а при свежих
    гео-proof у всех — авто-старт в active (без лидера).
    """
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember
    from app.models import GamePlayer, Mission

    # 1. Player существует и активен (паттерн _ensure_player из teams_service).
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 2. Командная сессия существует и в состоянии сбора.
    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status != "collecting":
        raise _mission_error(409, "Сессия не в состоянии сбора.")

    # 3. Игрок — участник этой сессии.
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is None:
        raise _mission_error(404, "Вы не участник этой сессии.")

    # 4. Участник ещё не отметился ('joined'); вышедшие/выбывшие не могут.
    if member.status != "joined":
        if member.status == "ready":
            raise _mission_error(409, "Вы уже отметились готовым.")
        if member.status == "left":
            raise _mission_error(409, "Вы вышли из сессии.")
        raise _mission_error(409, "Членство в сессии неактивно.")

    # 5. Миссия существует и опубликована.
    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")

    # 6. Валидный validation_config (правила экономики берутся из него).
    try:
        config = validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")

    # 7. Списание entryFeeRootAtomic и ключей — в той же транзакции, что и
    #    изменения статусов ниже (SessionLocal.begin() коммитит в конце).
    from app.mission_engine import _apply_entry_debit

    _apply_entry_debit(
        session,
        player_id=player_id,
        mission=mission,
        root_debit=config["economy"]["entryFeeRootAtomic"],
        requirements=config["economy"]["requiredItems"],
        reference_id=team_session.id,
        mission_run_id=member.mission_run_id,
    )

    # 8. Участник отметился готовым.
    member.status = "ready"
    member.ready_at = datetime.now(timezone.utc)

    # 9. Все активные участники в 'ready' → сессия готова к старту, а при
    #    свежих гео-proof у всех — авто-старт в active (без лидера).
    #    Участники статусов left/removed/settled не учитываются.
    session.flush()  # зафиксировать 'ready' текущего участника до выборки
    active_members = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
        )
    ).all()
    if active_members and all(
        member_row.status == "ready" for member_row in active_members
    ):
        team_session.status = "ready_to_start"

        if _all_ready_members_have_fresh_geo_proof(
            session,
            active_members,
            config,
        ):
            team_session.status = "active"
            team_session.started_at = _utcnow()

    return _serialize_team_session(session, team_session, player_id)


def create_team_session_entrypoint(player_id: str, mission_id: str) -> dict:
    """Точка вызова из HTTP-слоя: создать командную сессию (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _create_team_session(session, player_id, mission_id)


def mark_ready_entrypoint(player_id: str, session_id: str) -> dict:
    """Точка вызова из HTTP-слоя: подтвердить готовность (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _mark_ready(session, player_id, session_id)


def _join_team_session(
    session: Session,
    player_id: str,
    session_id: str,
) -> dict:
    """Присоединить игрока к временной командной сессии (status='collecting')."""
    from app.geo_team_runtime_models import (
        MissionRun,
        TeamSession,
        TeamSessionMember,
    )
    from app.models import GamePlayer

    # 1. Player существует и активен (паттерн _ensure_player).
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 2. Сессия существует и в состоянии сбора (присоединиться позже нельзя).
    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status != "collecting":
        raise _mission_error(409, "Сессия уже не в сборе.")

    # 3. Игрок ещё не участник ЭТОЙ сессии.
    existing = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if existing is not None:
        raise _mission_error(409, "Вы уже участник этой сессии.")

    # 4. Игрок не задействован в другой активной командной сессии.
    active_session_id = session.scalar(
        select(TeamSession.id)
        .join(TeamSessionMember, TeamSessionMember.team_session_id == TeamSession.id)
        .where(
            TeamSessionMember.player_id == player_id,
            TeamSession.status.in_(ACTIVE_SESSION_STATUSES),
        )
        .limit(1)
    )
    if active_session_id is not None:
        raise _mission_error(409, "У вас уже есть активная командная сессия.")

    # 5. Лимит состава — из effective_config_snapshot сессии (не из кода).
    config = team_session.effective_config_snapshot or {}
    max_members = (config.get("team") or {}).get("maxMembers")
    if max_members is not None:
        active_members = session.scalars(
            select(TeamSessionMember).where(
                TeamSessionMember.team_session_id == team_session.id,
                TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
            )
        ).all()
        if len(active_members) >= max_members:
            raise _mission_error(409, "Слишком много участников для этой миссии.")

    # 6. Создание (одна транзакция): MissionRun + TeamSessionMember.
    #    team_session_members.mission_run_id в БД NOT NULL — MissionRun
    #    создаётся вместе с членством.
    mission_run = MissionRun(
        id=_new_id("mission-run"),
        player_id=player_id,
        mission_id=team_session.mission_id,
        team_session_id=team_session.id,
        status=MISSION_RUN_STATUS_ACTIVE,
        effective_config_snapshot=deepcopy(config),
    )
    session.add(mission_run)
    session.flush()
    session.add(
        TeamSessionMember(
            id=_new_id("tsm"),
            team_session_id=team_session.id,
            player_id=player_id,
            mission_run_id=mission_run.id,
            status="joined",
            ready_at=None,
        )
    )
    session.flush()

    return _serialize_team_session(session, team_session, player_id)


def join_team_session(player_id: str, session_id: str) -> dict:
    """Точка вызова из HTTP-слоя: присоединиться к сессии (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _join_team_session(session, player_id, session_id)


def _is_inside_zone(
    zone,
    latitude: float,
    longitude: float,
) -> bool:
    """Dev check: is the point inside a radius zone (equirectangular approximation).

    Single spot to swap an external trusted verifier in prod."""
    if zone.zone_type != "radius":
        return False

    if zone.latitude is None or zone.longitude is None or zone.radius_meters is None:
        return False

    meters_per_degree = 111_320.0
    d_lat_m = (zone.latitude - latitude) * meters_per_degree
    d_lon_m = (zone.longitude - longitude) * meters_per_degree
    return (
        d_lat_m * d_lat_m + d_lon_m * d_lon_m
        <= zone.radius_meters * zone.radius_meters
    )


def _submit_location(
    session: Session,
    player_id: str,
    session_id: str,
    latitude: float,
    longitude: float,
    accuracy_meters: float,
) -> dict:
    """Record player presence vs. the mission geo zone.

    Raw coordinates are NOT persisted. accuracy_meters is reserved for an
    external verifier and is not used by the dev check. Single transaction."""
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember

    from app.models import GamePlayer, GeoZone, Mission


# 1. Player exists and active.
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 13.2-b-2: страна игрока — restricted с team в списке.
    if is_feature_restricted(session, player.country, "team"):
        raise _mission_error(403, "Командные миссии из вашей страны ограничены.")

    # 2. Session existsE presence only while collecting/ready_to_start.
    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status not in ("collecting", "ready_to_start"):
        raise _mission_error(409, "Сессия уже не в сборе.")


# 3. Player is a participant of this session.
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is None:
        raise _mission_error(404, "Вы не участник этой сессии.")

    # 4. Session membership is still active (joined/ready).
    if member.status not in ACTIVE_MEMBER_STATUSES:
        raise _mission_error(409, "Вы больше не в сессии.")

    # 5. Mission exists and is published.
    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")

    # 7. Valid validation_config..
    try:
        config = validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")


    # 8. Geo zone check:
    zone = session.scalar(
        select(GeoZone).where(
            GeoZone.slug == config["geo"]["zoneId"],
            GeoZone.status == "published",
        )
    )
    if zone is None:
        raise _mission_error(409, "Геозона недоступна.")

    # 9. Zone type support check:
    if zone.zone_type not in SUPPORTED_ZONE_TYPES:
        raise _mission_error(409, "Этот тип геозоны пока не поддерживается.")

    # Presence: verified/rejected via the dev verifier.
    verified = _is_inside_zone(zone, latitude, longitude)

    from app.geo_team_runtime_models import LocationProof
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=config["geo"]["proofFreshnessSeconds"])
    session.add(LocationProof(
        id=_new_id("location-proof"),
        player_id=player_id,
        provider=DEV_LOCATION_PROOF_PROVIDER,
        status=LOCATION_PROOF_STATUS_VERIFIED if verified else LOCATION_PROOF_STATUS_REJECTED,
        zone_id=config["geo"]["zoneId"],
        verifier_reference=None,
        issued_at=now,
        expires_at=expires_at,
    ))
    session.flush()

    # 10.0.5: фактическая страна игрока по координатам (geo-intel-offline).
    # Обновляем country, только если резолв дал iso2 с confidence >= 0.7;
    # иначе оставляем как есть (прежнее значение не затираем).
    resolved = resolve_country_or_none(latitude, longitude)
    if resolved is not None:
        player.country = resolved
        player.country_source = "auto"


    return {
        "sessionId": team_session.id,

        "zoneId": config["geo"]["zoneId"],
        "verified": verified,
        "expiresAt": expires_at.isoformat(),
    }


def submit_location_entrypoint(
    player_id: str,
    session_id: str,
    latitude: float,
    longitude: float,
    accuracy_meters: float,
) -> dict:
    """HTTP entrypoint: record presence (single transaction)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _submit_location(
            session, player_id, session_id, latitude, longitude, accuracy_meters
        )


def _activate_session(
    session: Session,
    player_id: str,
    session_id: str,
) -> dict:
    """Активировать сессию ready_to_start → active (fallback-эндпоинт).

    Основной путь — авто-старт в _mark_ready. Здесь может активировать
    любой активный участник сессии (лидера больше нет). Проверяет: все
    участники 'ready', у каждого свежий verified proof.
    """
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember
    from app.models import GamePlayer, Mission

    # 1. Player существует и активен (паттерн _ensure_player).
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 2. TeamSession существует и готова к старту.
    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status != "ready_to_start":
        raise _mission_error(409, "Сессия ещё не готова к старту.")

    # 3. Игрок — активный TeamSessionMember этой сессии.

    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is None or member.status not in ACTIVE_MEMBER_STATUSES:
        raise _mission_error(404, "Вы не участник этой сессии.")

    # 4. Миссия существует и опубликована.
    mission = session.get(Mission, team_session.mission_id)

    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")

    # 5. Валидный validation_config (переиспользовать проверку из _create_team_session).
    try:
        config = validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")

    # Проверка свежих verified proof'ов у всех 'ready'-участников.
    ready_members = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.status == "ready",
        )
    ).all()
    if not _all_ready_members_have_fresh_geo_proof(
        session,
        ready_members,
        config,
    ):
        raise _mission_error(
            409,
            "Не у всех участников свежая отметка присутствия.",
        )

    # Активация сессии.

    team_session.status = "active"
    team_session.started_at = _utcnow()
    session.flush()

    return _serialize_team_session(session, team_session, player_id)



def activate_session_entrypoint(player_id: str, session_id: str) -> dict:
    """Точка вызова из HTTP-слоя: активировать сессию (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _activate_session(session, player_id, session_id)


def _submit_answer(
    session: Session,
    player_id: str,
    session_id: str,
    answer: str | None,
) -> dict:
    """Игрок отправляет ответ → MissionRun.status='succeeded' + награды.

    Без валидации ответа (валидация — отдельный шаг, cipher).
    Награды начисляются по MissionReward миссии, идемпотентная привязка
    проводок — team_session.id (один раз на сессию на игрока).
    """
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import (
        MissionRun,
        TeamSession,
        TeamSessionMember,
    )
    from app.models import GamePlayer, Mission

    # 1. Player существует и активен (паттерн _ensure_player).
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 2. TeamSession существует, status='active'.
    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status != "active":
        raise _mission_error(409, "Сессия не активна.")

    # 3. Player — TeamSessionMember этой сессии.
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is None:
        raise _mission_error(404, "Вы не участник этой сессии.")

    # 4. member.status='ready' (подтвердил присутствие).
    if member.status != "ready":
        raise _mission_error(409, "Сначала подтвердите присутствие.")

    # 5. MissionRun у этого member существует, status='active'.
    mission_run = session.get(MissionRun, member.mission_run_id)
    if mission_run is None:
        raise _mission_error(404, "Прогресс не найден.")
    if mission_run.status != "active":
        raise _mission_error(409, "Вы уже завершили миссию.")

    # 6. Миссия опубликована, validation_config валиден (переиспользовать).
    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")
    try:
        validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")

    # Действие: переход MissionRun в 'succeeded' + награды за сессию.
    # НЕ трогаем TeamSession.status (переход сессии — 7.1.g).
    # НЕ валидируем answer (валидация — отдельный шаг, cipher).
    from app.mission_engine import _award_mission_rewards

    mission_run.status = "succeeded"
    mission_run.terminal_at = _utcnow()
    session.flush()

    awarded = _award_mission_rewards(
        session,
        player_id,
        mission,
        reference_id=team_session.id,
        mission_run_id=mission_run.id,
    )
    session.flush()

    return {
        "sessionId": team_session.id,
        "missionRunId": mission_run.id,
        "status": "succeeded",
        "terminalAt": mission_run.terminal_at.isoformat(),
        "awarded": awarded,
    }


def submit_answer_entrypoint(
    player_id: str,
    session_id: str,
    answer: str | None,
) -> dict:
    """Точка вызова из HTTP-слоя: отправить ответ (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _submit_answer(session, player_id, session_id, answer)


def list_my_team_sessions_entrypoint(player_id: str) -> dict:
    """Точка вызова из HTTP-слоя: {"sessions": [...]} активных сессий игрока."""
    from app.db import SessionLocal

    with SessionLocal() as session:
        sessions = _list_my_team_sessions(session, player_id)
    return {"sessions": sessions}
