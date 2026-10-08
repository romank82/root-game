"""Источник истины по ограничениям игрока и синхронизация кэша GamePlayer.status.

PlayerRestriction — источник истины о гранулярных ограничениях (шаг 5.1).
GamePlayer.status — быстрый кэш-агрегат для auth-гейтинга (не-active =
вход запрещён). Неизменный контракт синхронизации:

  - recompute_player_status(session, player) пересчитывает кэш по активным
    ограничениям с lazy-expiry просроченных (active -> expired по expires_at).
    Приоритет статусов: blocked > suspended > active. Вызывается:
      * всегда при создании/снятии ограничения (write-through, шаг 5.7);
      * лениво из auth-гейтов (get_current_player_id, _upsert_telegram_player,
        mission_engine._ensure_player), когда кэш «не-active» — чтобы
        выдохшиеся или снятые ограничения раз и навсегда не запирали игрока
        вне входа (lazy recovery, подтверждено в плане 5.7).

Модуль — лист зависимостей (только models + SQLAlchemy), поэтому его можно
подключать из любого гейтингового/админ-модуля без циклических импортов.

Lifecycle ограничения: active -> expired (lazy по expires_at) либо
revoked (админом). Физическое удаление запрещено.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GamePlayer, PlayerRestriction

ACTIVE_RESTRICTION_STATUS = "active"
EXPIRED_RESTRICTION_STATUS = "expired"
REVOKED_RESTRICTION_STATUS = "revoked"

PLAYER_STATUS_ACTIVE = "active"
PLAYER_STATUS_SUSPENDED = "suspended"
PLAYER_STATUS_BLOCKED = "blocked"

# Полный каталог типов из CheckConstraint ck_player_restrictions_type.
VALID_RESTRICTION_TYPES = frozenset(
    {
        "chat_restricted",
        "transfer_restricted",
        "team_restricted",
        "mission_restricted",
        "payment_restricted",
        "withdrawal_restricted",
        "suspended",
        "blocked",
    }
)

# Типы, которые переключают кэш GamePlayer.status в не-active.
GATE_BLOCKING_TYPES = frozenset({"blocked", "suspended"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def get_active_restrictions(
    session: Session,
    player_id: str,
) -> list[PlayerRestriction]:
    """Активные ограничения игрока после ленивого expiry просроченных.

    Ограничения с expires_at <= now переводятся в статус expired прямо здесь
    (без фонового джоба), чтобы «активный» набор оставался правдивым.
    with_for_update блокирует строки на Postgres и защищает гонку
    «expire vs админ-операция».
    """
    rows = list(
        session.scalars(
            select(PlayerRestriction)
            .where(
                PlayerRestriction.player_id == player_id,
                PlayerRestriction.status == ACTIVE_RESTRICTION_STATUS,
            )
            .with_for_update()
        ).all()
    )

    now = _utcnow()
    due: list[PlayerRestriction] = []
    for restriction in rows:
        expires_at = restriction.expires_at
        if expires_at is None:
            continue
        # SQLite (локальный dev) возвращает naive datetime для
        # DateTime(timezone=True); PostgreSQL — aware. Нормализуем в UTC.
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= now:
            due.append(restriction)

    for restriction in due:
        restriction.status = EXPIRED_RESTRICTION_STATUS

    if due:
        session.flush()

    return [r for r in rows if r.status == ACTIVE_RESTRICTION_STATUS]


def recompute_player_status(
    session: Session,
    player: GamePlayer,
) -> tuple[str, bool]:
    """Синхронизировать GamePlayer.status с источником истины.

    Возвращает (new_status, changed) и пишет кэш только при изменении.
    Просроченные ограничения lazy-expire внутри; статус:

      blocked  — есть активное приведённое blocked;
      suspended— есть активное suspended и нет blocked;
      active   — иных блокирующих ограничений нет.

    Гранулярные типы (chat/transfer/team/mission/payment/withdrawal_restricted)
    на кэш входа не влияют — они блокируются отдельными доменами.
    """
    active = get_active_restrictions(session, player.id)

    if any(r.restriction_type == "blocked" for r in active):
        new_status = PLAYER_STATUS_BLOCKED
    elif any(r.restriction_type == "suspended" for r in active):
        new_status = PLAYER_STATUS_SUSPENDED
    else:
        new_status = PLAYER_STATUS_ACTIVE

    changed = player.status != new_status
    if changed:
        player.status = new_status
        session.flush()

    return new_status, changed