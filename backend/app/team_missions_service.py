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
from app.datetime_utils import ensure_utc
from app.geo_country import resolve_country_or_none

# Активные командные сессии — в этих статусах игрок задействован в миссии.
ACTIVE_SESSION_STATUSES = frozenset({"collecting", "ready_to_start", "active"})

# Активные участники сессии (членство ещё действует, не left/removed/settled).
ACTIVE_MEMBER_STATUSES = frozenset({"joined", "ready"})

# Окно отказа с возвратом платы для командной сессии (3 минуты с момента её
# создания) — зеркало CANCEL_DEADLINE_SECONDS = 180 из mission_engine.py
# (для solo это cancel_deadline_at; для сессий отдельного поля нет, считаем
# от created_at).
TEAM_CANCEL_REFUND_SECONDS = 180

# Зеркала констант команд (без кросс-импорта teams_service).
TEAM_STATUS_ACTIVE = "active"
MEMBER_STATUS_ACTIVE = "active"

# Статус per-player MissionRun при создании командной сессии (7.1.b).
# Валиден по ck_mission_runs_status; тот же, что используют тесты 7.1.a
# в _make_session/_add_session_member.
MISSION_RUN_STATUS_ACTIVE = "active"
# «Открытые» статусы прогресса: их нужно закрывать при финализации сессии и
# при выходе участника (reserved — из будущих резервов, в team-флоу пока не
# используется, но модель его допускает).
MISSION_RUN_OPEN_STATUSES = frozenset({"active", "reserved"})

# ---- 7.1.d: гео-присутствие ---------------------------------------------
# Dev-режим сам выступает trusted verifier; для prod появится внешний verifier.
# Эти константы — единственное место смены провайдера при переходе на prod.
DEV_LOCATION_PROOF_PROVIDER = "dev_mock"
LOCATION_PROOF_STATUS_VERIFIED = "verified"
LOCATION_PROOF_STATUS_REJECTED = "rejected"
SUPPORTED_ZONE_TYPES = frozenset({"radius"})  # polygon/poi — позже

# ---- Join proximity (сбор команды): «рядом» -------------------------------
# Лимит расстояния между участниками при create/join — 50 км (haversine до
# ВСЕХ активных участников). CMS-поле validation_config.geo.
# pairwiseProximityMeters пока НЕ используется: admin UI (MissionsSection)
# пишет туда хардкод 40 (метры) — переключение на CMS отдельным шагом
# вместе с полем в форме миссии.
PAIRWISE_PROXIMITY_LIMIT_METERS = 50_000
PAIRWISE_PROXIMITY_LIMIT_KM = PAIRWISE_PROXIMITY_LIMIT_METERS / 1000.0

# Подвкладка «Активные» (TerminalScreen → папка «Командные»): чужие лобби,
# в которые ещё можно вступить (сбор/готовность), и лимит выборки.
ACTIVE_LOBBY_STATUSES = frozenset({"collecting", "ready_to_start"})
ACTIVE_LOBBY_LIMIT = 50


def _mission_error(status_code: int, detail: str) -> Exception:
    """Ожидаемая ошибка игрового API (ленивый импорт, как в teams_service)."""
    from app.mission_engine import MissionEngineError

    return MissionEngineError(status_code, detail)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _normalize_country(value) -> str | None:
    """ISO-2 (верхний регистр) или None.

    geo_intel_offline иногда возвращает плейсхолдер '-99' вместо кода страны
    (например, Франция: {'country': 'France', 'iso2': '-99'}). Такие значения
    нельзя ни сохранять, ни сравнивать — считаем страну неизвестной.
    """
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    if len(normalized) != 2 or not normalized.isalpha():
        return None
    return normalized


def _resolve_join_geo(
    latitude: float | None,
    longitude: float | None,
    player,
) -> dict:
    """Координаты create/join → (latitude, longitude, country, city).

    Только чтение. Страна — geo_intel_offline (как 10.0.5), фолбэк — страна
    из профиля игрока (GamePlayer.country, могла быть определена ранее).
    Город — reverse_geocoder (ближайший 1000+ жителей в пределах 50 км).
    GPS не передан → все значения None (legacy-путь без гео).
    """
    if latitude is None or longitude is None:
        return {
            "latitude": None,
            "longitude": None,
            "country": None,
            "city": None,
        }

    from app.geo_city import resolve_city_or_none

    country = _normalize_country(resolve_country_or_none(latitude, longitude))
    if country is None:
        country = _normalize_country(player.country)
    return {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "country": country,
        "city": resolve_city_or_none(latitude, longitude),
    }


def _ensure_members_nearby(
    members,
    *,
    latitude: float,
    longitude: float,
    country: str | None,
) -> None:
    """Правило «рядом» при вступлении: одна страна + ≤ лимита км до ВСЕХ.

    Проверяются участники с сохранёнными join_*: сессии, созданные без GPS
    (legacy team-accept путь), не блокируются — сравнивать нечего.
    Ошибка 409 бросается ДО списания entry fee.
    """
    from geo_intel_offline import calculate_distance_km

    for member in members:
        if (
            country is not None
            and member.join_country is not None
            and member.join_country != country
        ):
            raise _mission_error(
                409,
                "Разные страны: участники команды должны быть из одной страны.",
            )
        if member.join_latitude is None or member.join_longitude is None:
            continue
        distance_km = calculate_distance_km(
            latitude,
            longitude,
            member.join_latitude,
            member.join_longitude,
        )
        if distance_km > PAIRWISE_PROXIMITY_LIMIT_KM:
            raise _mission_error(
                409,
                "Слишком далеко: "
                f"{distance_km:.1f} км, лимит "
                f"{PAIRWISE_PROXIMITY_LIMIT_KM:.0f} км.",
            )


def _serialize_team_session(
    session: Session,
    team_session,
    player_id: str,
) -> dict:
    """Сериализация TeamSession для игрока. Используется в 7.1.a и 7.1.b.

    Только SELECT: заголовок миссии (без content/validation_config — закрытые
    данные), активные участники для memberCount и членство игрока.

    Sprint 8.x-3: игровое состояние волн для фронта (мини-игра в TeamSession
    Screen): currentWave/maxWaves/waveStatus, wavePlayedCount + myWavePlayed
    (без player_id сыгравших и без имён/ников — только счётчик и флаг
    текущего игрока), cipherSession для мини-игры (correctCode/drums/
    timeLimitSeconds; None после финализации). "sessionStatus" не дублируем
    — уже есть "status".
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

    wave_played = list(team_session.wave_played_members or [])

    # cipherSession для мини-игры: ключи в camelCase (стиль фронта), хранение
    # в БД (correct_code) не меняем. После финализации сессия отсутствует → None.
    cipher_payload = None
    if isinstance(team_session.current_cipher_session, dict):
        cipher_payload = {
            "correctCode": team_session.current_cipher_session.get("correct_code"),
            "drums": team_session.current_cipher_session.get("drums"),
            "timeLimitSeconds": team_session.current_cipher_session.get(
                "timeLimitSeconds"
            ),
        }

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
        # Sprint 8.x-3: игровое состояние волн командной мини-игры.
        "currentWave": team_session.current_wave,
        "maxWaves": team_session.max_waves,
        "waveStatus": team_session.wave_status,
        "wavePlayedCount": len(wave_played),
        "myWavePlayed": player_id in wave_played,
        "cipherSession": cipher_payload,
    }


def _list_my_team_sessions(session: Session, player_id: str) -> list[dict]:
    """Активные TeamSession игрока (только SELECT, сортировка createdAt DESC)."""
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember

    # Мои членства в командных сессиях. Только активные (joined/ready):
    # вышедший (left) / выбывший (removed) / рассчитанный (settled) участник
    # НЕ должен получать сессию в /me — иначе фронт покажет карточку с
    # кнопками «ОТКРЫТЬ СЕССИЮ»/«ОТКАЗАТЬСЯ», которые ведут в тупик.
    memberships = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.player_id == player_id,
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
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


def _serialize_active_team_session(
    *,
    team_session,
    mission,
    member_count: int,
    max_members,
    distance_km: float,
) -> dict:
    """Карточка чужого лобби для подвкладки «Активные».

    Отдельный сериализатор: базовый ``_serialize_team_session`` не трогаем —
    он отдаёт данные СВОЕЙ сессии (myStatus/waves/cipher), которых у чужого
    лобби нет. Описание — публичное поле CMS ``Mission.description``.
    """
    free_slots = (
        max_members - member_count
        if isinstance(max_members, int)
        else None
    )
    return {
        "id": team_session.id,
        "mission_id": team_session.mission_id,
        "missionTitle": mission.title if mission is not None else None,
        "description": mission.description if mission is not None else None,
        "status": team_session.status,
        "createdAt": (
            team_session.created_at.isoformat()
            if team_session.created_at
            else None
        ),
        "memberCount": member_count,
        "maxMembers": max_members,
        "freeSlots": free_slots,
        # Максимальное расстояние до участников («до команды: X км»).
        "distanceKm": round(distance_km, 1),
    }


def _list_active_team_sessions(
    session: Session,
    player_id: str,
    latitude: float,
    longitude: float,
) -> list[dict]:
    """Чужие лобби в сборе для подвкладки «Активные» (только SELECT).

    Показываем только совместимые сессии:
    - status in ACTIVE_LOBBY_STATUSES (вступление ещё возможно);
    - игрок НЕ участник (свои сессии отдаёт /sessions/me);
    - есть свободные места (memberCount < maxMembers из validation_config);
    - известны координаты и страна всех участников (иначе «рядом» не проверить;
      legacy-сессии, созданные team-accept без GPS, не показываем);
    - все участники в одной стране с игроком (если страна определилась);
    - расстояние до КАЖДОГО участника ≤ лимита «рядом»;
      distanceKm в карточке — максимум по участникам.

    Сортировка: ближайшие сверху (стабильно сохраняет createdAt DESC при
    равных расстояниях).
    """
    from geo_intel_offline import calculate_distance_km

    from app.geo_team_runtime_models import TeamSession, TeamSessionMember
    from app.models import GamePlayer, Mission

    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")

    player_country = _normalize_country(
        resolve_country_or_none(latitude, longitude)
    ) or _normalize_country(player.country)

    # Мои активные членства — эти сессии не показываем (они уже в /me).
    my_session_ids = set(
        session.scalars(
            select(TeamSessionMember.team_session_id).where(
                TeamSessionMember.player_id == player_id,
                TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
            )
        ).all()
    )

    team_sessions = session.scalars(
        select(TeamSession)
        .where(TeamSession.status.in_(ACTIVE_LOBBY_STATUSES))
        .order_by(TeamSession.created_at.desc())
        .limit(ACTIVE_LOBBY_LIMIT)
    ).all()

    result: list[dict] = []
    for team_session in team_sessions:
        if team_session.id in my_session_ids:
            continue

        members = session.scalars(
            select(TeamSessionMember).where(
                TeamSessionMember.team_session_id == team_session.id,
                TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
            )
        ).all()
        if not members:
            continue

        config = team_session.effective_config_snapshot or {}
        max_members = (config.get("team") or {}).get("maxMembers")
        if max_members is not None and len(members) >= max_members:
            continue

        # Координаты всех участников должны быть известны.
        if any(
            member.join_latitude is None or member.join_longitude is None
            for member in members
        ):
            continue

        # Страна: только совместимые (если страна игрока определилась).
        if player_country is not None and any(
            member.join_country != player_country for member in members
        ):
            continue

        max_distance_km = max(
            calculate_distance_km(
                latitude,
                longitude,
                member.join_latitude,
                member.join_longitude,
            )
            for member in members
        )
        if max_distance_km > PAIRWISE_PROXIMITY_LIMIT_KM:
            continue

        mission = session.get(Mission, team_session.mission_id)
        result.append(
            _serialize_active_team_session(
                team_session=team_session,
                mission=mission,
                member_count=len(members),
                max_members=max_members,
                distance_km=max_distance_km,
            )
        )

    result.sort(key=lambda item: item["distanceKm"] or 0.0)
    return result


def _create_team_session(
    session: Session,
    player_id: str,
    mission_id: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    accuracy: float | None = None,
) -> dict:
    """Создать временную командную сессию. Может любой игрок (без Team).

    Сессия стартует с одним участником — создателем (status='joined');
    состав расширяется join-session эндпоинтом. Все правила и количества
    берутся из validation_config миссии (код не хардкодит EntryFee и
    расходуемые ключи списываются при создании сессии (accept), сессия не
    переводится из 'collecting'.

    Join proximity: GPS создателя (latitude/longitude) сохраняется в
    TeamSessionMember (join_latitude/join_longitude/join_country/join_city)
    до списания entry fee — по этим данным join проверяет «рядом».
    Создатель один — расстояние не с кем сравнивать; accuracy принимается
    для симметрии с solo-accept и не используется.
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
            # Только активное членство (joined/ready): вышедший (left) из
            # collecting-сессии игрок не должен блокироваться как «уже есть
            # активная» — симметрично _list_my_team_sessions.
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
            TeamSession.status.in_(ACTIVE_SESSION_STATUSES),
        )
        .limit(1)
    )
    if active_session_id is not None:
        raise _mission_error(409, "У вас уже есть активная командная сессия.")


    # Join proximity: страна/город/координаты создателя (только чтение:
    # geo_intel_offline + reverse_geocoder). Все None, если GPS не передан.
    join_geo = _resolve_join_geo(latitude, longitude, player)
    join_location_at = _utcnow() if join_geo["latitude"] is not None else None

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
            join_latitude=join_geo["latitude"],
            join_longitude=join_geo["longitude"],
            join_country=join_geo["country"],
            join_city=join_geo["city"],
            join_location_at=join_location_at,
        )
    )

    session.flush()
    from app.mission_engine import _apply_entry_debit

    _apply_entry_debit(
        session,
        player_id=player_id,
        mission=mission,
        root_debit=config["economy"]["entryFeeRootAtomic"],
        requirements=config["economy"]["requiredItems"],
        reference_id=team_session.id,
        mission_run_id=mission_run.id,
    )

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
    EntryFee и расходуемые ключи уже списаны при accept (create/join).
    Когда все активные участники ('joined'/'ready') стали
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

    # 7. Участник отметился готовым.
    member.status = "ready"
    member.ready_at = datetime.now(timezone.utc)

    # 8. Все активные участники в 'ready' → сессия готова к старту, а при
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


def create_team_session_entrypoint(
    player_id: str,
    mission_id: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    accuracy: float | None = None,
) -> dict:
    """Точка вызова из HTTP-слоя: создать командную сессию (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _create_team_session(
            session,
            player_id,
            mission_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
        )


def mark_ready_entrypoint(player_id: str, session_id: str) -> dict:
    """Точка вызова из HTTP-слоя: подтвердить готовность (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _mark_ready(session, player_id, session_id)


def _join_team_session(
    session: Session,
    player_id: str,
    session_id: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    accuracy: float | None = None,
) -> dict:
    """Присоединить игрока к временной командной сессии (status='collecting').

    Join proximity (Sprint 8.x-4): при переданном GPS до списания entry fee
    проверяются «одна страна» и «рядом ≤ 50 км до ВСЕХ активных участников».
    GPS/страна/город сохраняются в TeamSessionMember (join_*). accuracy
    принимается для симметрии с solo-accept и не используется.
    """
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
    #    Только активное членство (joined/ready): вышедший (left) из живой
    #    collecting-сессии не блокируется — симметрично _create_team_session.
    active_session_id = session.scalar(
        select(TeamSession.id)
        .join(TeamSessionMember, TeamSessionMember.team_session_id == TeamSession.id)
        .where(
            TeamSessionMember.player_id == player_id,
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
            TeamSession.status.in_(ACTIVE_SESSION_STATUSES),
        )
        .limit(1)
    )
    if active_session_id is not None:
        raise _mission_error(409, "У вас уже есть активная командная сессия.")

    # 5. Лимит состава — из effective_config_snapshot сессии (не из кода).
    #    Список активных участников нужен и для лимита, и для join proximity.
    config = team_session.effective_config_snapshot or {}
    active_members = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
        )
    ).all()
    max_members = (config.get("team") or {}).get("maxMembers")
    if max_members is not None and len(active_members) >= max_members:
        raise _mission_error(409, "Слишком много участников для этой миссии.")

    # 6. Join proximity (ДО списания entry fee): одна страна и расстояние
    #    ≤ лимита до ВСЕХ активных участников. Проверяется только при
    #    переданном GPS; участники без координат (legacy team-accept путь)
    #    пропускаются — сравнивать нечего.
    join_geo = _resolve_join_geo(latitude, longitude, player)
    if join_geo["latitude"] is not None:
        _ensure_members_nearby(
            active_members,
            latitude=join_geo["latitude"],
            longitude=join_geo["longitude"],
            country=join_geo["country"],
        )
    join_location_at = _utcnow() if join_geo["latitude"] is not None else None

    # 7. Создание (одна транзакция): MissionRun + TeamSessionMember.
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
            join_latitude=join_geo["latitude"],
            join_longitude=join_geo["longitude"],
            join_country=join_geo["country"],
            join_city=join_geo["city"],
            join_location_at=join_location_at,
        )
    )
    session.flush()

    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")

    from app.mission_engine import _apply_entry_debit

    _apply_entry_debit(
        session,
        player_id=player_id,
        mission=mission,
        root_debit=config["economy"]["entryFeeRootAtomic"],
        requirements=config["economy"]["requiredItems"],
        reference_id=team_session.id,
        mission_run_id=mission_run.id,
    )

    return _serialize_team_session(session, team_session, player_id)


def join_team_session(
    player_id: str,
    session_id: str,
    *,
    latitude: float | None = None,
    longitude: float | None = None,
    accuracy: float | None = None,
) -> dict:
    """Точка вызова из HTTP-слоя: присоединиться к сессии (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _join_team_session(
            session,
            player_id,
            session_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
        )


def _refund_team_entry(
    session: Session,
    *,
    player_id: str,
    mission: Mission,
    config: dict,
    team_session_id: str,
    mission_run_id: str | None,
) -> bool:
    """Возврат платы участнику командной сессии (зеркало _refund_mission_entry).

    При create/join списание выполняет _apply_entry_debit с reference_id =
    team_session.id (ROOT: WalletTransaction 'mission_entry_debit'; ключи:
    InventoryEvent 'consumed'). Возврат зеркалит ровно эти записи для ЭТОГО
    игрока: credit-проводка 'mission_entry_refund' с тем же reference_id и
    события 'credited'. Если игрок не платил (debit по его кошельку не найден)
    — ничего не возвращаем. Идемпотентность — unique-индексы ledger.
    """
    from app.models import InventoryEvent, PlayerItem, WalletTransaction
    from app.mission_engine import (
        ENTRY_DEBIT_REFERENCE_TYPE,
        ENTRY_ITEM_EVENT_TYPE,
        ENTRY_ITEM_REFERENCE_TYPE,
        ENTRY_ITEM_REFUND_EVENT_TYPE,
        ENTRY_REFUND_REFERENCE_TYPE,
        _get_root_wallet_for_update,
    )

    refunded = False
    economy = config.get("economy") or {}
    root_debit = economy.get("entryFeeRootAtomic", 0) or 0

    # 1. ROOT: credit-проводка — только если этот игрок реально заплатил.
    if root_debit > 0:
        wallet = _get_root_wallet_for_update(session, player_id)
        paid = session.scalar(
            select(WalletTransaction.id).where(
                WalletTransaction.wallet_id == wallet.id,
                WalletTransaction.reference_type == ENTRY_DEBIT_REFERENCE_TYPE,
                WalletTransaction.reference_id == team_session_id,
            )
        )
        existing_refund = session.scalar(
            select(WalletTransaction.id).where(
                WalletTransaction.wallet_id == wallet.id,
                WalletTransaction.reference_type == ENTRY_REFUND_REFERENCE_TYPE,
                WalletTransaction.reference_id == team_session_id,
            )
        )
        if paid is not None and existing_refund is None:
            wallet.available_balance += root_debit
            session.add(
                WalletTransaction(
                    id=_new_id("wallet-transaction"),
                    wallet_id=wallet.id,
                    amount=root_debit,
                    balance_after=wallet.available_balance,
                    transaction_type="credit",
                    reason="Team session leave refund (cancel window)",
                    reference_type=ENTRY_REFUND_REFERENCE_TYPE,
                    reference_id=team_session_id,
                    metadata_json={
                        "missionId": mission.id,
                        "missionSlug": mission.slug,
                        "missionRunId": mission_run_id,
                    },
                )
            )
            refunded = True

    # 2. Ключи: возвращаем ровно то, что реально списано у этого игрока
    #    по сессии (event_type='consumed', reference_id=team_session.id).
    consumed_events = session.scalars(
        select(InventoryEvent)
        .join(PlayerItem, PlayerItem.id == InventoryEvent.player_item_id)
        .where(
            PlayerItem.player_id == player_id,
            InventoryEvent.event_type == ENTRY_ITEM_EVENT_TYPE,
            InventoryEvent.reference_type == ENTRY_ITEM_REFERENCE_TYPE,
            InventoryEvent.reference_id == team_session_id,
        )
    ).all()
    for event in consumed_events:
        player_item = session.get(PlayerItem, event.player_item_id)
        if player_item is None:
            continue
        existing_return = session.scalar(
            select(InventoryEvent.id).where(
                InventoryEvent.player_item_id == player_item.id,
                InventoryEvent.event_type == ENTRY_ITEM_REFUND_EVENT_TYPE,
                InventoryEvent.reference_type == ENTRY_ITEM_REFERENCE_TYPE,
                InventoryEvent.reference_id == team_session_id,
            )
        )
        if existing_return is not None:
            continue
        quantity = abs(event.quantity_delta)
        player_item.quantity += quantity
        session.add(
            InventoryEvent(
                id=_new_id("inventory-event"),
                player_item_id=player_item.id,
                mission_run_id=event.mission_run_id,
                event_type=ENTRY_ITEM_REFUND_EVENT_TYPE,
                quantity_delta=quantity,
                reference_type=ENTRY_ITEM_REFERENCE_TYPE,
                reference_id=team_session_id,
                metadata_json=dict(event.metadata_json or {}),
            )
        )
        refunded = True

    return refunded


def _leave_team_session(
    session: Session,
    player_id: str,
    session_id: str,
) -> dict:
    """Выход игрока из командной сессии (7.1.e).

    Лобби-семантика: выйти можно только ДО старта игры — в 'collecting' или
    'ready_to_start'. В 'active' выход запрещён (409): игра уже идёт. Если с
    момента создания сессии прошло меньше TEAM_CANCEL_REFUND_SECONDS —
    участнику возвращается плата (зеркало expire_mission: credit-проводка с
    тем же reference_id, что и debit при mark_ready).

    Участник помечается 'left', его MissionRun закрывается всегда
    ('cancelled_before_start'). Сессия остаётся в своём текущем статусе
    ('collecting' / 'ready_to_start'), пока в ней есть активные участники;
    если не осталось никого — сессия и её MissionRun переводятся в
    терминальный 'cancelled_before_start' (физическое удаление запрещено
    правилами игры: история и FK-целостность сохраняются; с точки зрения
    игрока сессия исчезает — активных сессий у него больше нет).

    session_id: id сессии ИЛИ id миссии (фронт карточки знает только миссию;
    тогда ищется активная сессия игрока на эту миссию).
    """
    from app.geo_team_runtime_models import MissionRun, TeamSession, TeamSessionMember
    from app.models import GamePlayer, Mission

    # 1. Игрок существует и активен.
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 2. Сессия: по id сессии, либо (фолбэк) активная сессия игрока на миссию.
    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        team_session = session.scalar(
            select(TeamSession)
            .join(
                TeamSessionMember,
                TeamSessionMember.team_session_id == TeamSession.id,
            )
            .where(
                TeamSession.mission_id == session_id,
                TeamSessionMember.player_id == player_id,
                TeamSession.status.in_(ACTIVE_SESSION_STATUSES),
            )
            .limit(1)
        )
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status == "active":
        raise _mission_error(409, "Игра уже началась, выходить нельзя.")
    if team_session.status not in ("collecting", "ready_to_start"):
        raise _mission_error(409, "Сессия уже не в сборе.")

    # 3. Участник этой сессии (активный).
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is None:
        raise _mission_error(404, "Вы не участник этой сессии.")
    if member.status not in ACTIVE_MEMBER_STATUSES:
        raise _mission_error(409, "Членство в сессии неактивно.")

    # 4. Возврат платы в окне TEAM_CANCEL_REFUND_SECONDS от accept/create.
    refunded = False
    now = _utcnow()
    session_created_at = ensure_utc(team_session.created_at)
    cancel_window_end = (
        session_created_at + timedelta(seconds=TEAM_CANCEL_REFUND_SECONDS)
        if session_created_at is not None
        else None
    )
    mission = session.get(Mission, team_session.mission_id)
    if (
        cancel_window_end is not None
        and now < cancel_window_end
        and mission is not None
    ):
        config = team_session.effective_config_snapshot or {}
        refunded = _refund_team_entry(
            session,
            player_id=player_id,
            mission=mission,
            config=config,
            team_session_id=team_session.id,
            mission_run_id=member.mission_run_id,
        )

    # 5. Участник вышел.
    member.status = "left"
    member.left_at = now
    # SessionLocal(autoflush=False): зафиксировать 'left' до выборки
    # оставшихся участников (паттерн _mark_ready), иначе COUNT увидит
    # старого 'joined' и сессия не закроется.
    session.flush()

    # 6. Прогресс вышедшего закрывается всегда: для него лобби/игра завершены,
    #    MissionRun не должен остаться открытым.
    mission_run = session.get(MissionRun, member.mission_run_id)
    if mission_run is not None and mission_run.status in MISSION_RUN_OPEN_STATUSES:
        mission_run.status = "cancelled_before_start"
        mission_run.terminal_at = now

    # 7. Активных участников не осталось — сессия закрывается терминально
    #    (история сохраняется, активных сессий у игроков больше нет).
    remaining = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
        )
    ).all()
    if not remaining:
        team_session.status = "cancelled_before_start"
        team_session.terminal_at = now
        for run in session.scalars(
            select(MissionRun).where(
                MissionRun.team_session_id == team_session.id,
            )
        ).all():
            run.status = "cancelled_before_start"
            run.terminal_at = now
    # Иначе (есть активные участники) сессия остаётся в текущем статусе:
    # 'collecting' или 'ready_to_start' — до старта волн откатывать нечего.

    session.flush()
    return {"left": True, "refunded": refunded}


def leave_team_session(player_id: str, session_id: str) -> dict:
    """Точка вызова из HTTP-слоя: выйти из командной сессии (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _leave_team_session(session, player_id, session_id)


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


def _generate_cipher_session_for_wave(
    session: Session,
    team_session,
) -> dict:
    """Sprint 8.x-2b-1: сгенерировать cipher-сессию для текущей волны.

    Ключи результата — ровно как у CipherHandler.generate_session
    (НЕ переименовывать): correct_code, drums, timeLimitSeconds.
    """
    from app.mission_engine import _resolve_minigame_settings
    from app.minigame_handlers import get_handler
    from app.models import Mission

    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")

    settings = _resolve_minigame_settings(session, mission)
    handler = get_handler("cipher")
    if handler is None:
        raise _mission_error(409, "Мини-игра не поддерживается.")
    return handler.generate_session(settings)


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

    # Sprint 8.x-2b-1: волна 1 инициализируется при активации.
    # max_waves — из снапшота validationConfig.attempts.maxAttempts (как
    # _mark_ready читает team.maxMembers из эффективного снапшота); если
    # структура отсутствует/невалидна — консервативный default 3.
    config = team_session.effective_config_snapshot or {}
    attempts = config.get("attempts") or {}
    max_waves = attempts.get("maxAttempts")
    team_session.max_waves = (
        max_waves if isinstance(max_waves, int) and max_waves >= 1 else 3
    )
    team_session.current_wave = 1
    team_session.wave_status = "playing"
    team_session.wave_played_members = []
    team_session.current_cipher_session = _generate_cipher_session_for_wave(
        session, team_session
    )
    session.flush()

    return _serialize_team_session(session, team_session, player_id)


def _submit_wave_answer(
    session: Session,
    player_id: str,
    session_id: str,
    sequence: list[str] | None,
) -> dict:
    """Sprint 8.x-2b-1/2a: игрок отвечает на cipher волны.

    Ошибка игрока → команда переходит к следующей волне (новая
    current_cipher_session, wave_played_members сброшен); когда волн больше
    нет — миссия завершается неудачей (TeamSession.status='failed',
    terminal_at, current_cipher_session=None). Верный ответ → MissionRun
    succeeded + награды; когда сыграли ВСЕ активные члены — миссия succeeded
    (wave_status='passed'), иначе волна остаётся 'playing'. Мусорный
    sequence — 400 без смены статусов (hotfix 8.x-2b-1).
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
    from app.minigame_handlers import get_handler
    from app.models import GamePlayer, Mission

    # 1. Player существует и активен (паттерн _ensure_player).
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")
    if player.status != "active":
        raise _mission_error(403, "Игровой профиль неактивен.")

    # 2. TeamSession существует, status='active'. Row-lock (FOR UPDATE) от
    #    гонок: параллельные ответы участников пишут в одну строку
    #    (wave_played_members/current_wave/status) — паттерн проекта
    #    (admin_chapters.py, mission_engine._get_root_wallet_for_update);
    #    на SQLite with_for_update — no-op. Транзакция — та же, что и записи
    #    ниже (entrypoint открывает SessionLocal.begin()).
    team_session = session.scalar(
        select(TeamSession).where(TeamSession.id == session_id).with_for_update()
    )
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

    # 7. NEW: игрок уже сыграл в текущей волне.
    played = list(team_session.wave_played_members or [])
    if player_id in played:
        raise _mission_error(409, "Вы уже сыграли в этой волне.")

    # 8. Валидация sequence против cipher-сессии волны.
    session_data = team_session.current_cipher_session
    if session_data is None:
        raise _mission_error(409, "Игровая сессия не инициализирована.")
    # 8a. Мусорный формат ответа — ошибка клиента (400), а не провал волны:
    #     wave_status не меняем, validate_submission не вызываем (8.x-2b-1-hotfix).
    if (
        sequence is None
        or not isinstance(sequence, list)
        or not all(isinstance(el, str) for el in sequence)
    ):
        raise _mission_error(400, "Некорректный формат ответа.")
    handler = get_handler("cipher")
    accepted = (
        handler is not None
        and handler.validate_submission(
            session_data=session_data, sequence=sequence
        )
    )

    if not accepted:
        # Реальная ошибка игрока (НЕ мусор формата: тот отсечён выше как 400).
        # Волна провалена командой — переходим к следующей; когда волн больше
        # нет, миссия завершается неудачей. Наград нет (8.x-2b-2a).
        team_session.current_wave += 1
        if team_session.current_wave > team_session.max_waves:
            now = _utcnow()
            team_session.status = "failed"
            team_session.terminal_at = now
            team_session.current_cipher_session = None
            team_session.wave_status = "failed"
            # Финализация: у всех, кто ещё не закрыл свой MissionRun, прогресс
            # завершается failed. Ответивший ранее уже succeeded — не трогаем.
            for run in session.scalars(
                select(MissionRun).where(
                    MissionRun.team_session_id == team_session.id,
                )
            ).all():
                if run.status in MISSION_RUN_OPEN_STATUSES:
                    run.status = "failed"
                    run.terminal_at = now
        else:
            # Есть ещё волны: свежая cipher-сессия, сыгравшие обнуляются.
            team_session.wave_status = "playing"
            team_session.wave_played_members = []
            team_session.current_cipher_session = _generate_cipher_session_for_wave(
                session, team_session
            )
        session.flush()
        return {
            "sessionId": team_session.id,
            "waveStatus": team_session.wave_status,
            "currentWave": team_session.current_wave,
            "maxWaves": team_session.max_waves,
            "sessionStatus": team_session.status,
            "accepted": False,
            "message": "Неверная комбинация.",
        }

    # Правильный ответ: волна пройдена этим игроком (награды сразу).
    played.append(player_id)
    team_session.wave_played_members = played

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

    # Sprint 8.x-4-final-status-1: фиксируем награды игрока в снапшоте
    # TeamSessionMember (append-only, NULL = наград не было), чтобы при
    # финализации сессии (succeeded/failed) отдать их ВСЕМ членам команды,
    # а не только последнему отправившему. Пишется в той же транзакции,
    # что и награды. Повторный верный ответ не пройдёт сюда (409 «Вы уже
    # сыграли в этой волне» выше); перезапись тем же awarded идемпотентна —
    # ledger не дублируется (unique wallet_id+reference_type+reference_id).
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is not None:
        member.awarded_snapshot = awarded
    session.flush()

    # Волна завершена, когда сыграли ВСЕ активные участники (статусы те же,
    # что считает memberCount в _serialize_team_session — ACTIVE_MEMBER_STATUSES).
    # Тогда финализируем миссию; иначе — ждём остальных.
    active_players = session.scalars(
        select(TeamSessionMember.player_id).where(
            TeamSessionMember.team_session_id == team_session.id,
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
        )
    ).all()
    played_set = set(played)
    if active_players and all(pid in played_set for pid in active_players):
        now = _utcnow()
        team_session.wave_status = "passed"
        team_session.status = "succeeded"
        team_session.terminal_at = now
        team_session.current_cipher_session = None
        # Финализация-страховка: игравшие уже succeeded (выше); если по какой-то
        # причине остались открытые MissionRun (active/reserved) — закрываем
        # failed, чтобы не осталось «идущих» прогрессов после финала сессии.
        for run in session.scalars(
            select(MissionRun).where(
                MissionRun.team_session_id == team_session.id,
            )
        ).all():
            if run.status in MISSION_RUN_OPEN_STATUSES:
                run.status = "failed"
                run.terminal_at = now
    else:
        team_session.wave_status = "playing"
    session.flush()

    return {
        "sessionId": team_session.id,
        "missionRunId": mission_run.id,
        "waveStatus": team_session.wave_status,
        "currentWave": team_session.current_wave,
        "maxWaves": team_session.max_waves,
        "sessionStatus": team_session.status,
        "accepted": True,
        "awarded": awarded,
    }


def submit_wave_answer_entrypoint(
    player_id: str,
    session_id: str,
    sequence: list[str] | None,
) -> dict:
    """Точка вызова из HTTP-слоя: ответ cipher волны (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _submit_wave_answer(session, player_id, session_id, sequence)


def activate_session_entrypoint(player_id: str, session_id: str) -> dict:
    """Точка вызова из HTTP-слоя: активировать сессию (одна транзакция)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _activate_session(session, player_id, session_id)


def list_my_team_sessions_entrypoint(player_id: str) -> dict:
    """Точка вызова из HTTP-слоя: {"sessions": [...]} активных сессий игрока."""
    from app.db import SessionLocal

    with SessionLocal() as session:
        sessions = _list_my_team_sessions(session, player_id)
    return {"sessions": sessions}


def list_active_team_sessions_entrypoint(
    player_id: str,
    latitude: float,
    longitude: float,
) -> dict:
    """Точка вызова из HTTP-слоя: чужие лобби «Активные» (одна SELECT-сессия).

    GPS игрока приходит query-параметрами: по нему считаются страна и
    расстояние до участников (в БД координаты игрока не пишутся).
    """
    from app.db import SessionLocal

    with SessionLocal() as session:
        sessions = _list_active_team_sessions(
            session,
            player_id,
            latitude,
            longitude,
        )
    return {"sessions": sessions}


# ---- Sprint 8.x-4-final-status-2: последняя терминальная сессия ----------


def _get_last_terminal_team_session(session: Session, player_id: str):
    """Последняя терминальная TeamSession игрока (succeeded/failed) или None.

    Только SELECT. Терминальные сессии не видны через /me
    (ACTIVE_SESSION_STATUSES в _list_my_team_sessions) — этот хелпер отдаёт
    финал ВСЕМ членам команды, а не только последнему отправившему.
    terminal_at заполняется при финализации (_submit_wave_answer: и
    succeeded, и failed) → сортировка по terminal_at DESC корректна на
    SQLite и PostgreSQL (NULL не попадают в выборку). При равенстве — новее
    по created_at.
    """
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember

    session_ids = session.scalars(
        select(TeamSessionMember.team_session_id).where(
            TeamSessionMember.player_id == player_id,
        )
    ).all()

    if not session_ids:
        return None

    return session.scalar(
        select(TeamSession)
        .where(
            TeamSession.id.in_(session_ids),
            TeamSession.status.in_({"succeeded", "failed"}),
        )
        .order_by(TeamSession.terminal_at.desc(), TeamSession.created_at.desc())
        .limit(1)
    )


def last_terminal_team_session_entrypoint(player_id: str) -> dict:
    """Точка вызова из HTTP-слоя: {"session": {...} | None}.

    session — _serialize_team_session + "awarded" (награды ИГРОКА из его
    awarded_snapshot в TeamSessionMember; None, если наград не было).
    """
    from app.db import SessionLocal

    with SessionLocal() as session:
        team_session = _get_last_terminal_team_session(session, player_id)
        if team_session is None:
            return {"session": None}

        from app.geo_team_runtime_models import TeamSessionMember

        payload = _serialize_team_session(session, team_session, player_id)

        member = session.scalar(
            select(TeamSessionMember).where(
                TeamSessionMember.team_session_id == team_session.id,
                TeamSessionMember.player_id == player_id,
            )
        )
        payload["awarded"] = (
            member.awarded_snapshot
            if member is not None and member.awarded_snapshot
            else None
        )
        return {"session": payload}
