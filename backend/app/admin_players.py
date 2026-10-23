"""Read-only admin endpoints for player data (шаг 5.3).

GET /api/v1/admin/players            — list with filters + pagination.
GET /api/v1/admin/players/profile-fields — конфиг полей профиля (10.0.2).
GET /api/v1/admin/players/{player_id} — full player card.

Оба эндпоинта требуют прямого права ``players.read``. Эндпоинты read-only:
используем ``SessionLocal()`` без ``begin()``, никаких записей в БД.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import sanitize_audit_data
from app.db import SessionLocal
from app.models import (
    AdminUser,
    GamePlayer,
    Item,
    Mission,
    PlayerItem,
    PlayerMission,
    PlayerRestriction,
    Wallet,
    WalletTransaction,
)

router = APIRouter(prefix="/api/v1/admin/players", tags=["admin-players"])

PLAYERS_READ_PERMISSION = "players.read"
PLAYERS_MANAGE_PERMISSION = "players.manage"  # reserved for 5.4+
PLAYERS_RESTRICT_PERMISSION = "players.restrict"  # reserved for 5.7
PLAYERS_BLOCK_PERMISSION = "players.block"  # reserved for 5.7

# Конфиг полей профиля игрока для фронта (10.0.2). Отдаётся через
# GET /api/v1/admin/players/profile-fields и задаёт форму карточки:
# key — имя колонки GamePlayer, label — заголовок для UI, type — вид
# контрола, options/readOnly/min/max — атрибуты контрола. PATCH (запись)
# появится позже (34-C); константы VALID_GENDERS/AGE_MIN/AGE_MAX —
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

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200
RECENT_TRANSACTIONS_LIMIT = 20
MISSION_HISTORY_LIMIT = 10
RESTRICTIONS_LIMIT = 20


def _get_player_or_404(session: Session, player_id: str) -> GamePlayer:
    player = session.get(GamePlayer, player_id)
    if player is None:
        raise HTTPException(status_code=404, detail="Игрок не найден.")
    return player


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
    }

def _serialize_player_card(session: Session, player: GamePlayer) -> dict[str, Any]:
    """Полная карточка игрока: batch-JOIN-запросы, без записей в БД.

    Wallet может отсутствовать (не создаём read-only эндпоинтом) — тогда
    блоки wallet/recentTransactions/stats отдают нули и пустые списки.
    """
    wallet = session.scalar(
        select(Wallet).where(Wallet.player_id == player.id)
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
        },
        "wallet": (
            {
                "currency": wallet.currency,
                "availableBalance": wallet.available_balance,
                "lockedBalance": wallet.locked_balance,
            }
            if wallet is not None
            else {"currency": "ROOT", "availableBalance": 0, "lockedBalance": 0}
        ),
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