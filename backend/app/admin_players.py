"""Admin endpoints for player data (шаг 5.3, 10.0.4).

GET /api/v1/admin/players            — list with filters + pagination.
GET /api/v1/admin/players/profile-fields — конфиг полей профиля (10.0.2).
GET /api/v1/admin/players/{player_id} — full player card.
PATCH /api/v1/admin/players/{player_id} — корректировка country/gender/age
(10.0.4, update_admin_player_profile).

GET-эндпоинты требуют прямого права ``players.read`` и read-only (без записей
в БД). PATCH требует ``players.manage``: валидация (gender ∈ VALID_GENDERS,
age 0..120, country ISO-2), row-lock игрока (_lock_player) и аудит
(before/after, changedFields).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import sanitize_audit_data, write_admin_audit
from app.db import SessionLocal
from app.player_restrictions_engine import (
    ACTIVE_RESTRICTION_STATUS,
    REVOKED_RESTRICTION_STATUS,
    get_active_restrictions,
    recompute_player_status,
)
from app.models import (
    AdminUser,
    GamePlayer,
    GasWallet,
    GasTransaction,
    Item,
    Mission,
    PlayerItem,
    PlayerMission,
    PlayerRestriction,
    Wallet,
    WalletTransaction,
)

# Sprint 11.8 NanoROOT: 1 ROOT = 10^8 наноROOT (как в admin_player_wallet).
NANO_PER_ROOT = 100_000_000

router = APIRouter(prefix="/api/v1/admin/players", tags=["admin-players"])

PLAYERS_READ_PERMISSION = "players.read"
PLAYERS_MANAGE_PERMISSION = "players.manage"  # reserved for 5.4+
PLAYERS_RESTRICT_PERMISSION = "players.restrict"  # reserved for 5.7
PLAYERS_BLOCK_PERMISSION = "players.block"  # reserved for 5.7

# Конфиг полей профиля игрока для фронта (10.0.2). Отдаётся через
# GET /api/v1/admin/players/profile-fields и задаёт форму карточки:
# key — имя колонки GamePlayer, label — заголовок для UI, type — вид
# контрола, options/readOnly/min/max — атрибуты контрола. PATCH (запись) —
# 10.0.4 (update_admin_player_profile); константы VALID_GENDERS/AGE_MIN/AGE_MAX —
# источник для бэк-валидации.
PROFILE_FIELDS = [
    {
        "key": "nickname",
        "label": "Ник",
        "type": "text",
        "readOnly": True,
    },
    {
        "key": "country",
        "label": "Страна",
        "type": "text",
        "maxLength": 2,
    },
    {
        "key": "gender",
        "label": "Пол",
        "type": "select",
        "options": ["male", "female", "other", "unspecified"],
    },
    {
        "key": "age",
        "label": "Возраст",
        "type": "number",
        "min": 0,
        "max": 120,
    },
]
VALID_GENDERS = {"male", "female", "other", "unspecified"}
AGE_MIN = 0
AGE_MAX = 120


class PlayerProfileUpdatePayload(BaseModel):
    """PATCH профиля (10.0.4): только country/gender/age.
    nickname/лишние поля — 422 (extra=forbid)."""

    model_config = ConfigDict(extra="forbid")

    country: str | None = Field(default=None, max_length=2)
    gender: str | None = Field(default=None)
    age: int | None = Field(default=None, ge=AGE_MIN, le=AGE_MAX)


class GasAdjustmentPayload(BaseModel):
    """PATCH газа (10.4-c): начислить (+) / списать (-)."""

    model_config = ConfigDict(extra="forbid")

    amount: Decimal
    reason: str = Field(..., min_length=1, max_length=255)


class RootAdjustmentPayload(BaseModel):
    """PATCH ROOT (13.7-c): начислить (+) / списать (-)."""

    model_config = ConfigDict(extra="forbid")

    amount: int
    reason: str = Field(..., min_length=1, max_length=255)


class PlayerBlockPayload(BaseModel):
    """POST block/unblock (13.7-h): обязательный reason (1..255).

    Один payload на оба действия: причина блокировки (block) и причина
    снятия (unblock → revocation_reason) — в одном формате, extra=forbid.
    """

    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=255)


DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
DEFAULT_GAS_TX_LIMIT = 50
MAX_GAS_TX_LIMIT = 200
DEFAULT_ROOT_TX_LIMIT = 50
MAX_ROOT_TX_LIMIT = 200

RECENT_TRANSACTIONS_LIMIT = 20
MISSION_HISTORY_LIMIT = 10
RESTRICTIONS_LIMIT = 20


def _get_player_or_404(session: Session, player_id: str) -> GamePlayer:
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Игрок не найден.")
    return player


def _lock_player(session: Session, player_id: str) -> GamePlayer:
    """Игрок с FOR UPDATE (PostgreSQL; SQLite — не блокирует)."""
    player = session.scalar(
        select(GamePlayer)
        .where(GamePlayer.id == player_id)
        .with_for_update()
    )
    if player is None:
        raise HTTPException(status_code=404, detail="Игрок не найден.")
    return player


def _new_id(prefix: str) -> str:
    """Уникальный id с префиксом (паттерн остальных admin-модулей)."""
    return f"{prefix}-{uuid4().hex}"


def _serialize_player_summary(
    player: GamePlayer, wallet: Wallet | None
) -> dict[str, Any]:
    """Короткая строка списка (без external_id). rootBalance — кэш из wallet."""
    return {
        "id": player.id,
        "displayName": player.display_name,
        "authProvider": player.auth_provider,
        "status": player.status,
        "nickname": player.nickname,
        "country": player.country,
        "gender": player.gender,
        "age": player.age,
        "telegramUsername": player.telegram_username,
        "telegramFirstName": player.telegram_first_name,
        "telegramLastName": player.telegram_last_name,
        "telegramPhotoUrl": player.telegram_photo_url,
        "createdAt": player.created_at.isoformat() if player.created_at else None,
        "rootBalance": wallet.available_balance if wallet is not None else 0,
        # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
        "rootBalanceNano": (
            getattr(wallet, "available_balance_nano", None)
            if wallet is not None
            and getattr(wallet, "available_balance_nano", None) is not None
            else (wallet.available_balance * NANO_PER_ROOT if wallet is not None else None)
        ),
    }

def _serialize_player_card(session: Session, player: GamePlayer) -> dict[str, Any]:
    """Полная карточка игрока: batch-JOIN-запросы, без записей в БД.

    Wallet может отсутствовать (не создаём read-only эндпоинтом) — тогда
    блоки wallet/recentTransactions/stats отдают нули и пустые списки.
    GasWallet тоже может отсутствовать — gasBalance отдаётся как "0".
    """
    wallet = session.scalar(
        select(Wallet).where(Wallet.player_id == player.id)
    )
    gas_wallet = session.scalar(
        select(GasWallet).where(GasWallet.player_id == player.id)
    )
    # FakeSession в tests/test_admin_players.scalar() ветвится по подстроке
    # "wallets" и для "gas_wallets" отдаёт ROOT-заглушку без поля balance.
    # Реальная SQLAlchemy-сессия всегда возвращает GasWallet — здесь будет
    # его дробный Numeric-баланс. getattr-защита оставлена для фейка.
    gas_balance = (
        getattr(gas_wallet, "balance", Decimal("0"))
        if gas_wallet is not None
        else Decimal("0")
    )

    # Инвентарь: игровые строки PlayerItem с quantity > 0 + детали Item.
    inventory_rows = session.execute(
        select(PlayerItem, Item)
        .join(Item, PlayerItem.item_id == Item.id)
        .where(PlayerItem.player_id == player.id, PlayerItem.quantity > 0)
    ).all()
    inventory = [
        {
            "id": player_item.id,
            "itemId": item.id,
            "slug": item.slug,
            "code": item.code,
            "title": item.title,
            "symbol": item.symbol,
            "category": item.category,
            "rarity": item.rarity,
            "quantity": player_item.quantity,
            "obtainedFromType": player_item.obtained_from_type,
            "obtainedFromId": player_item.obtained_from_id,
        }
        for player_item, item in inventory_rows
    ]

    # Активные миссии: in_progress + available.
    active_rows = session.execute(
        select(PlayerMission, Mission)
        .join(Mission, PlayerMission.mission_id == Mission.id)
        .where(
            PlayerMission.player_id == player.id,
            PlayerMission.status.in_(["in_progress", "available"]),
        )
    ).all()
    active_missions = [
        {
            "missionId": mission.id,
            "slug": mission.slug,
            "title": mission.title,
            "missionType": mission.mission_type,
            "status": player_mission.status,
            "attemptCount": player_mission.attempt_count,
            "startedAt": (
                player_mission.started_at.isoformat()
                if player_mission.started_at
                else None
            ),
        }
        for player_mission, mission in active_rows
    ]

    # История миссий: только completed, новые сверху.
    history_rows = session.execute(
        select(PlayerMission, Mission)
        .join(Mission, PlayerMission.mission_id == Mission.id)
        .where(PlayerMission.player_id == player.id, PlayerMission.status == "completed")
        .order_by(PlayerMission.completed_at.desc())
        .limit(MISSION_HISTORY_LIMIT)
    ).all()
    mission_history = [
        {
            "missionId": mission.id,
            "slug": mission.slug,
            "title": mission.title,
            "status": player_mission.status,
            "attemptCount": player_mission.attempt_count,
            "startedAt": (
                player_mission.started_at.isoformat()
                if player_mission.started_at
                else None
            ),
            "completedAt": (
                player_mission.completed_at.isoformat()
                if player_mission.completed_at
                else None
            ),
        }
        for player_mission, mission in history_rows
    ]

    # Ограничения: активные сверху, лимит 20.
    restrictions = session.scalars(
        select(PlayerRestriction)
        .where(PlayerRestriction.player_id == player.id)
        .order_by(
            PlayerRestriction.status.asc(),
            PlayerRestriction.created_at.desc(),
        )
        .limit(RESTRICTIONS_LIMIT)
    ).all()
    restrictions_payload = [
        {
            "id": restriction.id,
            "restrictionType": restriction.restriction_type,
            "status": restriction.status,
            "reason": restriction.reason,
            "evidence": restriction.evidence,
            "adminId": restriction.admin_id,
            "startsAt": (
                restriction.starts_at.isoformat()
                if restriction.starts_at
                else None
            ),
            "expiresAt": (
                restriction.expires_at.isoformat()
                if restriction.expires_at
                else None
            ),
            "approvedByApprovalId": restriction.approval_request_id,
            "revokedAt": (
                restriction.revoked_at.isoformat()
                if restriction.revoked_at
                else None
            ),
            "revocationReason": restriction.revocation_reason,
        }
        for restriction in restrictions
    ]

    # Последние проводки ROOT (только если wallet есть).
    if wallet is not None:
        transactions = session.scalars(
            select(WalletTransaction)
            .where(WalletTransaction.wallet_id == wallet.id)
            .order_by(WalletTransaction.created_at.desc())
            .limit(RECENT_TRANSACTIONS_LIMIT)
        ).all()
        recent_transactions = [
            {
                "id": tx.id,
                "amount": tx.amount,
                "balanceAfter": tx.balance_after,
                # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
                "balanceAfterNano": (
                    getattr(tx, "balance_after_nano", None)
                    if getattr(tx, "balance_after_nano", None) is not None
                    else tx.balance_after * NANO_PER_ROOT
                ),
                "transactionType": tx.transaction_type,
                "reason": tx.reason,
                "referenceType": tx.reference_type,
                "referenceId": tx.reference_id,
                # Audit-редaction переиспользуется для перевыдачи metadata.
                "metadata": sanitize_audit_data(tx.metadata_json or {}),
                "createdAt": tx.created_at.isoformat() if tx.created_at else None,
            }
            for tx in transactions
        ]
    else:
        recent_transactions = []

    # Статистика. totalMissionsCompleted считаем всегда, суммы ROOT — только
    # при наличии кошелька (нулевые суммы при его отсутствии).
    total_missions_completed = session.scalar(
        select(func.count())
        .select_from(PlayerMission)
        .where(
            PlayerMission.player_id == player.id,
            PlayerMission.status == "completed",
        )
    ) or 0

    if wallet is not None:
        total_root_earned = session.scalar(
            select(func.coalesce(func.sum(WalletTransaction.amount), 0))
            .where(
                WalletTransaction.wallet_id == wallet.id,
                WalletTransaction.transaction_type == "credit",
            )
        ) or 0
        total_root_spent = session.scalar(
            select(func.coalesce(func.sum(WalletTransaction.amount), 0))
            .where(
                WalletTransaction.wallet_id == wallet.id,
                WalletTransaction.transaction_type == "debit",
            )
        ) or 0
    else:
        total_root_earned = 0
        total_root_spent = 0

    return {
        "player": {
            "id": player.id,
            "displayName": player.display_name,
            "authProvider": player.auth_provider,
            "status": player.status,
            "nickname": player.nickname,
            "country": player.country,
            "gender": player.gender,
            "age": player.age,
            "externalId": player.external_id,
            "telegram": {
                "username": player.telegram_username,
                "firstName": player.telegram_first_name,
                "lastName": player.telegram_last_name,
                "photoUrl": player.telegram_photo_url,
                "normalizedUsername": player.telegram_username_normalized,
            },
            "registeredAt": (
                player.created_at.isoformat() if player.created_at else None
            ),
            # Точной колонки «последняя активность» нет:
            # updated_at — приблизительная оценка (обновляется при /auth/telegram).
            "lastActivityAt": (
                player.updated_at.isoformat() if player.updated_at else None
            ),
            # Точное время последнего запроса (13.7-b): обновляется при каждом
            # обращении к профилю/карточке — основа статуса онлайн/офлайн (13.7-g).
            "lastSeenAt": (
                player.last_seen_at.isoformat() if player.last_seen_at else None
            ),
        },
        "wallet": (
            {
                "currency": wallet.currency,
                "availableBalance": wallet.available_balance,
                # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
                "availableBalanceNano": (
                    getattr(wallet, "available_balance_nano", None)
                    if getattr(wallet, "available_balance_nano", None) is not None
                    else wallet.available_balance * NANO_PER_ROOT
                ),
                "lockedBalance": wallet.locked_balance,
                # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
                "lockedBalanceNano": (
                    getattr(wallet, "locked_balance_nano", None)
                    if getattr(wallet, "locked_balance_nano", None) is not None
                    else wallet.locked_balance * NANO_PER_ROOT
                ),
            }
            if wallet is not None
            else {"currency": "ROOT", "availableBalance": 0, "lockedBalance": 0}
        ),
        # Газ (10.4-b): дробный Numeric(18,4). Сериализуем строкой, чтобы не
        # терять точность Decimal через float в JSON.
        "gasBalance": str(gas_balance),
        "inventory": inventory,
        "activeMissions": active_missions,
        "missionHistory": mission_history,
        "restrictions": restrictions_payload,
        "recentTransactions": recent_transactions,
        "stats": {
            "totalMissionsCompleted": total_missions_completed,
            "totalRootEarned": total_root_earned,
            "totalRootSpent": total_root_spent,
        },
    }


def _serialize_gas_transaction(tx: GasTransaction) -> dict[str, Any]:
    """Проводка газа (10.4-d): Decimal → строка (точность), metadata —
    через sanitize_audit_data, как recentTransactions в карточке."""
    return {
        "id": tx.id,
        "amount": str(tx.amount),
        "balanceAfter": str(tx.balance_after),
        "transactionType": tx.transaction_type,
        "reason": tx.reason,
        "referenceType": tx.reference_type,
        "referenceId": tx.reference_id,
        "metadata": sanitize_audit_data(tx.metadata_json or {}),
        "createdAt": tx.created_at.isoformat() if tx.created_at else None,
    }


def _serialize_root_transaction(tx: WalletTransaction) -> dict[str, Any]:
    """Проводка ROOT (13.7-e-1): Integer → число (не строка), metadata через
    sanitize_audit_data, как recentTransactions в карточке."""
    return {
        "id": tx.id,
        "amount": tx.amount,
        "balanceAfter": tx.balance_after,
        # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
        "balanceAfterNano": (
            getattr(tx, "balance_after_nano", None)
            if getattr(tx, "balance_after_nano", None) is not None
            else tx.balance_after * NANO_PER_ROOT
        ),
        "transactionType": tx.transaction_type,
        "reason": tx.reason,
        "referenceType": tx.reference_type,
        "referenceId": tx.reference_id,
        "metadata": sanitize_audit_data(tx.metadata_json or {}),
        "createdAt": tx.created_at.isoformat() if tx.created_at else None,
    }


@router.get("")
def list_admin_players(
    search: str | None = None,
    status: str | None = None,
    auth_provider: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
):
    """Список игроков с фильтрами и минимальной пагинацией (limit/offset)."""
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)

    conditions = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                GamePlayer.telegram_username.ilike(pattern),
                GamePlayer.display_name.ilike(pattern),
                GamePlayer.telegram_first_name.ilike(pattern),
                GamePlayer.nickname_lower.ilike(pattern),
            )
        )
    if status:
        conditions.append(GamePlayer.status == status)
    if auth_provider:
        conditions.append(GamePlayer.auth_provider == auth_provider)

    with SessionLocal() as session:  # read-only, не begin()
        total = session.scalar(
            select(func.count())
            .select_from(GamePlayer)
            .where(*conditions)
        ) or 0

        rows = session.execute(
            select(GamePlayer, Wallet)
            .outerjoin(Wallet, Wallet.player_id == GamePlayer.id)
            .where(*conditions)
            .order_by(GamePlayer.created_at.desc(), GamePlayer.id)
            .offset(offset)
            .limit(limit)
        ).all()
        players = [
            _serialize_player_summary(player, wallet) for player, wallet in rows
        ]

    return {
        "players": players,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# 13.7-i-1: статистика всех игроков (total/online/active). Активность по
# GamePlayer.last_seen_at (13.7-b), без отдельной таблицы login_events.
# Периоды в днях; онлайн — последние STATS_ONLINE_MINUTES минут.
STATS_PERIOD_DAYS = {"day": 1, "week": 7, "month": 30}
STATS_ONLINE_MINUTES = 5


@router.get("/stats")
def get_admin_players_stats(
    period: str = "day",
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
):
    """Статистика всех игроков (13.7-i-1): total/online/active.

    period: day (24ч) / week (7 дней) / month (30 дней); дефолт — day.
    total — все GamePlayer, online — last_seen_at за последние 5 минут,
    active — уникальные с последним визитом с начала периода.
    """
    days = STATS_PERIOD_DAYS.get(period)
    if days is None:
        raise HTTPException(422, "period должен быть day/week/month.")
    now = datetime.now(timezone.utc)
    online_since = now - timedelta(minutes=STATS_ONLINE_MINUTES)
    active_since = now - timedelta(days=days)
    with SessionLocal() as session:  # read-only, не begin()
        total = session.scalar(
            select(func.count()).select_from(GamePlayer)
        ) or 0
        online = session.scalar(
            select(func.count())
            .select_from(GamePlayer)
            .where(GamePlayer.last_seen_at >= online_since)
        ) or 0
        active = session.scalar(
            select(func.count())
            .select_from(GamePlayer)
            .where(GamePlayer.last_seen_at >= active_since)
        ) or 0
    return {
        "period": period,
        "total": total,
        "online": online,
        "active": active,
    }


@router.get("/profile-fields")
def get_profile_fields(
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
) -> dict:
    """Конфиг полей профиля игрока (для фронта, 10.0.2)."""
    return {"fields": PROFILE_FIELDS}


@router.get("/{player_id}")
def get_admin_player(
    player_id: str,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
):
    """Полная карточка игрока."""
    with SessionLocal() as session:  # read-only, не begin()
        player = _get_player_or_404(session, player_id)
        return {"player": _serialize_player_card(session, player)}


@router.patch("/{player_id}")
def update_admin_player_profile(
    player_id: str,
    payload: PlayerProfileUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
):
    """PATCH профиля (10.0.4): country/gender/age (direct, без approval)."""
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        player = _lock_player(session, player_id)

        before = {
            "country": player.country,
            "gender": player.gender,
            "age": player.age,
        }
        changed_fields: list[str] = []

        if "country" in updates:
            value = updates["country"]
            if value is not None:
                value = value.strip().upper()
                if len(value) != 2 or not value.isalpha():
                    raise HTTPException(
                        status_code=422,
                        detail="country должен быть ISO-2 (2 буквы).",
                    )
            player.country = value
            # 10.0.5-b: админская правка country = ручная (source='manual');
            # админский PATCH не блокируется (может исправить даже 'auto').
            player.country_source = "manual"
            changed_fields.append("country")

        if "gender" in updates:
            value = updates["gender"]
            if value is not None and value not in VALID_GENDERS:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "gender должен быть одним из: "
                        f"{', '.join(sorted(VALID_GENDERS))}."
                    ),
                )
            player.gender = value
            changed_fields.append("gender")

        if "age" in updates:
            player.age = updates["age"]
            changed_fields.append("age")

        session.flush()

        write_admin_audit(
            session,
            actor=admin,
            action="player.profile_updated",
            entity_type="player",
            entity_id=player_id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=before,
            after={
                "country": player.country,
                "gender": player.gender,
                "age": player.age,
            },
            metadata={"changedFields": changed_fields},
        )

        return {"player": _serialize_player_card(session, player)}


@router.patch("/{player_id}/gas")
def update_admin_player_gas(
    player_id: str,
    payload: GasAdjustmentPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
):
    """PATCH газа (10.4-c): начислить (+) / списать (-) газ игроку.

    Row-lock GasWallet (создаётся при отсутствии), immutable-проводка
    GasTransaction и аудит — в одной транзакции (SessionLocal.begin()).
    """
    if payload.amount == 0:
        raise HTTPException(
            status_code=422,
            detail="Сумма газа должна быть ненулевой.",
        )

    with SessionLocal.begin() as session:
        player = _get_player_or_404(session, player_id)
        gas_wallet = session.scalar(
            select(GasWallet)
            .where(GasWallet.player_id == player_id)
            .with_for_update()
        )
        if gas_wallet is None:
            gas_wallet = GasWallet(
                id=_new_id("gas-wallet"),
                player_id=player_id,
                balance=Decimal("0"),
            )
            session.add(gas_wallet)
            session.flush()

        old_balance = gas_wallet.balance
        new_balance = old_balance + payload.amount
        if new_balance < 0:
            raise HTTPException(
                status_code=422,
                detail="Недостаточно газа для списания.",
            )
        gas_wallet.balance = new_balance

        transaction_type = "credit" if payload.amount > 0 else "debit"
        session.add(
            GasTransaction(
                id=_new_id("gas-transaction"),
                gas_wallet_id=gas_wallet.id,
                amount=abs(payload.amount),
                balance_after=new_balance,
                transaction_type=transaction_type,
                reason=payload.reason,
                reference_type="admin_gas_adjustment",
                reference_id=_new_id("admin-gas-adjustment"),
                metadata_json={"adminId": admin.id},
            )
        )

        write_admin_audit(
            session,
            actor=admin,
            action="player.gas_adjusted",
            entity_type="player",
            entity_id=player_id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before={"gasBalance": str(old_balance)},
            after={"gasBalance": str(new_balance)},
            metadata={"amount": str(payload.amount), "reason": payload.reason},
        )

        session.flush()
        return {"player": _serialize_player_card(session, player)}


@router.patch("/{player_id}/root")
def update_admin_player_root(
    player_id: str,
    payload: RootAdjustmentPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
):
    """PATCH ROOT (13.7-c): начислить (+) / списать (-) ROOT игроку.

    Row-lock Wallet (создаётся при отсутствии, balance=0), immutable-проводка
    WalletTransaction и аудит — в одной транзакции (SessionLocal.begin()).
    """
    if payload.amount == 0:
        raise HTTPException(
            status_code=422,
            detail="Сумма ROOT должна быть ненулевой.",
        )

    with SessionLocal.begin() as session:
        player = _get_player_or_404(session, player_id)
        wallet = session.scalar(
            select(Wallet)
            .where(Wallet.player_id == player_id)
            .with_for_update()
        )
        if wallet is None:
            wallet = Wallet(
                id=_new_id("wallet"),
                player_id=player_id,
                currency="ROOT",
                available_balance=0,
                locked_balance=0,
            )
            session.add(wallet)
            session.flush()

        old_balance = wallet.available_balance
        new_balance = old_balance + payload.amount
        if new_balance < 0:
            raise HTTPException(
                status_code=422,
                detail="Недостаточно ROOT для списания.",
            )
        wallet.available_balance = new_balance

        transaction_type = "credit" if payload.amount > 0 else "debit"
        session.add(
            WalletTransaction(
                id=_new_id("wallet-transaction"),
                wallet_id=wallet.id,
                amount=abs(payload.amount),
                balance_after=new_balance,
                transaction_type=transaction_type,
                reason=payload.reason,
                reference_type="admin_root_adjustment",
                reference_id=_new_id("admin-root-adjustment"),
                metadata_json={"adminId": admin.id},
            )
        )

        write_admin_audit(
            session,
            actor=admin,
            action="player.root_adjusted",
            entity_type="player",
            entity_id=player_id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before={"rootBalance": old_balance},
            after={"rootBalance": new_balance},
            metadata={"amount": payload.amount, "reason": payload.reason},
        )

        session.flush()
        return {"player": _serialize_player_card(session, player)}


@router.post("/{player_id}/block")
def block_admin_player(
    player_id: str,
    payload: PlayerBlockPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
):
    """Заблокировать игрока (13.7-h): активный PlayerRestriction blocked + аудит.

    Идемпотентность: повторный block с уже активным blocked -> 409
    «Игрок уже заблокирован» (ядро против активных дублей одного типа,
    см. admin_player_restrictions: uq_player_restrictions_active_per_type).
    Write-through: recompute_player_status синхронизирует кэш
    GamePlayer.status (active -> blocked) — как в admin_player_restrictions.
    """
    with SessionLocal.begin() as session:
        player = _get_player_or_404(session, player_id)

        active = get_active_restrictions(session, player_id)
        if any(r.restriction_type == "blocked" for r in active):
            raise HTTPException(
                status_code=409,
                detail="Игрок уже заблокирован.",
            )

        restriction = PlayerRestriction(
            id=_new_id("player-restriction"),
            player_id=player_id,
            restriction_type="blocked",
            status=ACTIVE_RESTRICTION_STATUS,
            reason=payload.reason,
            admin_id=admin.id,
            starts_at=datetime.now(timezone.utc),
        )
        session.add(restriction)
        session.flush()

        # Write-through: кэш статуса пересчитывается после создания.
        recompute_player_status(session, player)

        write_admin_audit(
            session,
            actor=admin,
            action="player.blocked",
            entity_type="player",
            entity_id=player_id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before={"blocked": False},
            after={"blocked": True},
            metadata={"reason": payload.reason, "restrictionId": restriction.id},
        )
        session.flush()
        return {"player": _serialize_player_card(session, player), "blocked": True}


@router.post("/{player_id}/unblock")
def unblock_admin_player(
    player_id: str,
    payload: PlayerBlockPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
):
    """Разблокировать игрока (13.7-h): снять активный blocked + аудит.

    Снятие по образцу _apply_restriction_revoke (admin_player_restrictions):
    status='revoked' + revoked_at + revoked_by_admin_id +
    revocation_reason, а не expires_at=now (revoke — админ-действие,
    lifecycle остаётся в истории). Повторный unblock без активного
    blocked -> 409 «Игрок не заблокирован».
    """
    with SessionLocal.begin() as session:
        player = _get_player_or_404(session, player_id)

        active = get_active_restrictions(session, player_id)
        restriction = next(
            (r for r in active if r.restriction_type == "blocked"), None
        )
        if restriction is None:
            raise HTTPException(
                status_code=409,
                detail="Игрок не заблокирован.",
            )

        restriction.status = REVOKED_RESTRICTION_STATUS
        restriction.revoked_by_admin_id = admin.id
        restriction.revoked_at = datetime.now(timezone.utc)
        restriction.revocation_reason = payload.reason
        session.flush()

        # Write-through: кэш статуса пересчитывается после снятия
        # (blocked -> active).
        recompute_player_status(session, player)

        write_admin_audit(
            session,
            actor=admin,
            action="player.unblocked",
            entity_type="player",
            entity_id=player_id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before={"blocked": True},
            after={"blocked": False},
            metadata={"reason": payload.reason, "restrictionId": restriction.id},
        )
        session.flush()
        return {"player": _serialize_player_card(session, player), "blocked": False}


@router.get("/{player_id}/gas-transactions")
def list_admin_player_gas_transactions(
    player_id: str,
    limit: int = DEFAULT_GAS_TX_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
):
    """История транзакций газа игрока (10.4-d), пагинация (limit/offset)."""
    safe_limit = max(1, min(limit, MAX_GAS_TX_LIMIT))
    safe_offset = max(0, offset)
    with SessionLocal() as session:  # read-only, не begin()
        player = _get_player_or_404(session, player_id)
        gas_wallet = session.scalar(
            select(GasWallet).where(GasWallet.player_id == player.id)
        )
        # GasWallet может отсутствовать: read-only ручка не создаёт.
        if gas_wallet is None:
            return {
                "transactions": [],
                "total": 0,
                "limit": safe_limit,
                "offset": safe_offset,
            }
        base = select(GasTransaction).where(
            GasTransaction.gas_wallet_id == gas_wallet.id
        )
        total = (
            session.scalar(
                select(func.count())
                .select_from(GasTransaction)
                .where(GasTransaction.gas_wallet_id == gas_wallet.id)
            )
            or 0
        )
        rows = session.scalars(
            base.order_by(
                GasTransaction.created_at.desc(), GasTransaction.id.desc()
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
        return {
            "transactions": [_serialize_gas_transaction(tx) for tx in rows],
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }


@router.get("/{player_id}/root-transactions")
def list_admin_player_root_transactions(
    player_id: str,
    limit: int = DEFAULT_ROOT_TX_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_READ_PERMISSION)),
):
    """История ROOT-транзакций игрока (13.7-e-1), пагинация (limit/offset)."""
    safe_limit = max(1, min(limit, MAX_ROOT_TX_LIMIT))
    safe_offset = max(0, offset)
    with SessionLocal() as session:  # read-only, не begin()
        player = _get_player_or_404(session, player_id)
        wallet = session.scalar(select(Wallet).where(Wallet.player_id == player.id))
        # Wallet может отсутствовать: read-only ручка не создаёт.
        if wallet is None:
            return {
                "transactions": [],
                "total": 0,
                "limit": safe_limit,
                "offset": safe_offset,
            }
        base = select(WalletTransaction).where(
            WalletTransaction.wallet_id == wallet.id
        )
        total = (
            session.scalar(
                select(func.count())
                .select_from(WalletTransaction)
                .where(WalletTransaction.wallet_id == wallet.id)
            )
            or 0
        )
        rows = session.scalars(
            base.order_by(
                WalletTransaction.created_at.desc(), WalletTransaction.id.desc()
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()
        return {
            "transactions": [_serialize_root_transaction(tx) for tx in rows],
            "total": total,
            "limit": safe_limit,
            "offset": safe_offset,
        }
