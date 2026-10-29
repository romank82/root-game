"""Спринт 8.x-4-dev-bot: ВРЕМЕННЫЕ dev-эндпоинты для проверки командной мини-игры.

Позволяют dev-боту (игрок id="player-bot-1", external_id="bot-1") вступить в
командную сессию, стать ready, отметить гео-присутствие, активировать сессию и
пройти волну (отправить верный код). Нужно заказчику, чтобы проверить
командную мини-игру (волны, «провал одного = провал всех», «ждём других»)
без второго Telegram-аккаунта.

ТОЛЬКО для локальной разработки: HTTP-роуты в main.py защищены проверкой
settings.app_env == "development" (в проде — 404 «Not Found»). После проверки
фичи модуль вместе с роутами удалим отдельным коммитом (revert dev-bot).

ВНИМАНИЕ (dev-обвязка, прод-логика не трогается):
- join/activate/submit_wave_answer ПЕРЕИСПОЛЬЗУЮТ существующие функции
  team_missions_service (не копируются и не правятся).
- Экономика: бот НЕ списывает entryFee/ключи при ready (обход _mark_ready —
  иначе не хватило бы ROOT; задание разрешает обход для dev-бота). Награды за
  верный ответ бот получает штатным путём _submit_wave_answer — dev-only,
  на других игроков не влияет.
- Активация идёт через явный _activate_session: он инициализирует волну 1
  (current_wave/current_cipher_session/wave_played_members). Авто-старт из
  ready-логики так не делает, поэтому здесь не используется.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

# Идентификаторы dev-бота (find-or-create по (auth_provider, external_id)).
BOT_PLAYER_ID = "player-bot-1"
BOT_EXTERNAL_ID = "bot-1"
BOT_AUTH_PROVIDER = "dev"


def _mission_error(status_code: int, detail: str) -> Exception:
    """Ожидаемая ошибка игрового API (ленивый импорт, как в team_missions_service)."""
    from app.mission_engine import MissionEngineError

    return MissionEngineError(status_code, detail)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _get_or_create_bot_player(session: Session):
    """Найти dev-бота или создать (без миграции, только в dev)."""
    from app.models import GamePlayer

    bot = session.scalar(
        select(GamePlayer).where(
            GamePlayer.auth_provider == BOT_AUTH_PROVIDER,
            GamePlayer.external_id == BOT_EXTERNAL_ID,
        )
    )
    if bot is not None:
        return bot

    bot = GamePlayer(
        id=BOT_PLAYER_ID,
        display_name="БОТ",
        auth_provider=BOT_AUTH_PROVIDER,
        external_id=BOT_EXTERNAL_ID,
        nickname="devbot",
        nickname_lower="devbot",
        status="active",
    )
    session.add(bot)
    session.flush()
    return bot


def _bot_join_session(session: Session, session_id: str) -> dict:
    """Вступить ботом в командную сессию (MissionRun + TeamSessionMember)."""
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember

    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status != "collecting":
        raise _mission_error(409, "Сессия уже не в сборе.")

    bot = _get_or_create_bot_player(session)

    existing = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == session_id,
            TeamSessionMember.player_id == bot.id,
        )
    )
    if existing is not None:
        return {
            "sessionId": session_id,
            "botPlayerId": bot.id,
            "memberStatus": existing.status,
            "alreadyMember": True,
        }

    # Существующая логика join: создаёт MissionRun + TeamSessionMember,
    # проверяет лимит состава и «другая активная сессия».
    from app.team_missions_service import _join_team_session

    _join_team_session(session, bot.id, session_id)
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == session_id,
            TeamSessionMember.player_id == bot.id,
        )
    )
    return {
        "sessionId": session_id,
        "botPlayerId": bot.id,
        "memberStatus": member.status if member is not None else None,
    }


def _bot_ready(session: Session, session_id: str) -> dict:
    """Поставить боту status='ready' (без списания entryFee/ключей) и при всех
    готовых членах перевести сессию ready_to_start."""
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import TeamSession, TeamSessionMember
    from app.models import Mission
    from app.team_missions_service import ACTIVE_MEMBER_STATUSES

    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status not in ("collecting", "ready_to_start"):
        raise _mission_error(409, "Сессия не в состоянии сбора.")

    bot = _get_or_create_bot_player(session)
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == session_id,
            TeamSessionMember.player_id == bot.id,
        )
    )
    if member is None:
        raise _mission_error(409, "Бот не участник сессии (сначала /dev/bot/join).")

    if member.status == "joined":
        member.status = "ready"
        member.ready_at = _utcnow()
        session.flush()

    if member.status not in ACTIVE_MEMBER_STATUSES:
        raise _mission_error(409, "Членство бота неактивно.")

    # Как в _mark_ready (пункт 9): все активные члены готовы → ready_to_start.
    # Авто-старт в active НЕ дублируем: волны инициализирует _activate_session.
    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")
    try:
        config = validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")

    active_members = session.scalars(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == session_id,
            TeamSessionMember.status.in_(ACTIVE_MEMBER_STATUSES),
        )
    ).all()
    if active_members and all(
        member_row.status == "ready" for member_row in active_members
    ):
        team_session.status = "ready_to_start"
    session.flush()

    return {
        "sessionId": team_session.id,
        "botPlayerId": bot.id,
        "memberStatus": member.status,
        "sessionStatus": team_session.status,
    }


def _bot_submit_location(session: Session, session_id: str) -> dict:
    """Отметить боту гео-присутствие: создать verified LocationProof напрямую
    (без координат — dev-бот всегда «в зоне»)."""
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import LocationProof, TeamSession, TeamSessionMember
    from app.models import Mission
    from app.team_missions_service import (
        DEV_LOCATION_PROOF_PROVIDER,
        LOCATION_PROOF_STATUS_VERIFIED,
    )

    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status not in ("collecting", "ready_to_start"):
        raise _mission_error(409, "Сессия уже не в сборе.")

    bot = _get_or_create_bot_player(session)
    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == session_id,
            TeamSessionMember.player_id == bot.id,
        )
    )
    if member is None:
        raise _mission_error(409, "Бот не участник сессии (сначала /dev/bot/join).")

    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")
    try:
        config = validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")

    now = _utcnow()
    expires_at = now + timedelta(seconds=config["geo"]["proofFreshnessSeconds"])
    session.add(
        LocationProof(
            id=_new_id("location-proof"),
            player_id=bot.id,
            provider=DEV_LOCATION_PROOF_PROVIDER,
            status=LOCATION_PROOF_STATUS_VERIFIED,
            zone_id=config["geo"]["zoneId"],
            verifier_reference=None,
            issued_at=now,
            expires_at=expires_at,
        )
    )
    session.flush()

    return {
        "sessionId": team_session.id,
        "botPlayerId": bot.id,
        "proofStatus": "verified",
        "expiresAt": expires_at.isoformat(),
    }


def _dev_submit_location_for_player(
    session: Session,
    player_id: str,
    session_id: str,
) -> dict:
    """Dev: verified LocationProof для ТЕКУЩЕГО игрока (без GPS).

    Нужен, чтобы заказчик вне геозоны мог дать свежий proof и активировать
    сессию. Только dev: роут защищён _ensure_dev_environment (в проде — 404).
    """
    from app.geo_team_contract import (
        GeoTeamConfigurationError,
        validate_team_mission_validation_config,
    )
    from app.geo_team_runtime_models import LocationProof, TeamSession, TeamSessionMember
    from app.models import GamePlayer, Mission
    from app.team_missions_service import (
        DEV_LOCATION_PROOF_PROVIDER,
        LOCATION_PROOF_STATUS_VERIFIED,
    )

    player = session.get(GamePlayer, player_id)
    if player is None:
        raise _mission_error(404, "Игрок не найден.")

    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status not in ("collecting", "ready_to_start"):
        raise _mission_error(409, "Сессия уже не в сборе.")

    member = session.scalar(
        select(TeamSessionMember).where(
            TeamSessionMember.team_session_id == session_id,
            TeamSessionMember.player_id == player_id,
        )
    )
    if member is None:
        raise _mission_error(409, "Вы не участник этой сессии.")
    if member.status != "ready":
        raise _mission_error(409, "Сначала подтвердите готовность.")

    mission = session.get(Mission, team_session.mission_id)
    if mission is None or mission.status != "published":
        raise _mission_error(409, "Миссия недоступна.")
    try:
        config = validate_team_mission_validation_config(mission.validation_config)
    except GeoTeamConfigurationError:
        raise _mission_error(409, "Конфигурация командной миссии невалидна.")

    now = _utcnow()
    expires_at = now + timedelta(seconds=config["geo"]["proofFreshnessSeconds"])
    session.add(
        LocationProof(
            id=_new_id("location-proof"),
            player_id=player_id,
            provider=DEV_LOCATION_PROOF_PROVIDER,
            status=LOCATION_PROOF_STATUS_VERIFIED,
            zone_id=config["geo"]["zoneId"],
            verifier_reference=None,
            issued_at=now,
            expires_at=expires_at,
        )
    )
    session.flush()

    return {
        "sessionId": team_session.id,
        "playerId": player_id,
        "proofStatus": "verified",
        "expiresAt": expires_at.isoformat(),
    }


def _bot_activate(session: Session, session_id: str) -> dict:
    """Активировать сессию ready_to_start → active (инициализирует волну 1)."""
    from app.team_missions_service import _activate_session

    bot = _get_or_create_bot_player(session)
    serialized = _activate_session(session, bot.id, session_id)
    return {
        "sessionId": serialized.get("id", session_id),
        "botPlayerId": bot.id,
        "status": serialized.get("status"),
    }


def _bot_play_wave(session: Session, session_id: str) -> dict:
    """Бот отвечает на текущую волну верным кодом (correct_code из
    current_cipher_session)."""
    from app.geo_team_runtime_models import TeamSession
    from app.team_missions_service import _submit_wave_answer

    team_session = session.get(TeamSession, session_id)
    if team_session is None:
        raise _mission_error(404, "Командная сессия не найдена.")
    if team_session.status != "active":
        raise _mission_error(409, "Сессия не активна.")

    bot = _get_or_create_bot_player(session)

    played = list(team_session.wave_played_members or [])
    if bot.id in played:
        return {
            "sessionId": team_session.id,
            "botPlayerId": bot.id,
            "alreadyPlayed": True,
            "waveStatus": team_session.wave_status,
            "currentWave": team_session.current_wave,
            "maxWaves": team_session.max_waves,
            "sessionStatus": team_session.status,
        }

    cipher = team_session.current_cipher_session
    if not isinstance(cipher, dict):
        raise _mission_error(409, "Игровая сессия не инициализирована.")
    correct_code = cipher.get("correct_code")
    if not isinstance(correct_code, list) or not all(
        isinstance(symbol, str) for symbol in correct_code
    ):
        raise _mission_error(409, "Игровая сессия не инициализирована.")

    return _submit_wave_answer(session, bot.id, session_id, list(correct_code))


# ---- Entrypoint'ы (одна транзакция, стиль team_missions_service) ----

def dev_bot_join_entrypoint(session_id: str) -> dict:
    """HTTP entrypoint: вступить ботом в командную сессию."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _bot_join_session(session, session_id)


def dev_bot_ready_entrypoint(session_id: str) -> dict:
    """HTTP entrypoint: бот готов (без списания entryFee)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _bot_ready(session, session_id)


def dev_bot_submit_location_entrypoint(session_id: str) -> dict:
    """HTTP entrypoint: verified LocationProof для бота."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _bot_submit_location(session, session_id)


def dev_location_me_entrypoint(player_id: str, session_id: str) -> dict:
    """HTTP entrypoint: verified LocationProof для текущего игрока (dev)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _dev_submit_location_for_player(session, player_id, session_id)


def dev_bot_activate_entrypoint(session_id: str) -> dict:
    """HTTP entrypoint: активировать сессию (инициализация волны 1)."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _bot_activate(session, session_id)


def dev_bot_play_wave_entrypoint(session_id: str) -> dict:
    """HTTP entrypoint: бот отвечает на волну верным кодом."""
    from app.db import SessionLocal

    with SessionLocal.begin() as session:
        return _bot_play_wave(session, session_id)