"""Общий магазин ключей (Sprint 8.16).

Независим от fallback_shop.py: fallback оставлен как deprecated, работает и не
трогается. Публичный каталог — все Item(category=KEY, status=published);
покупка возможна любое количество раз, пока есть ROOT, без
quota_limit / consumed_count / exhausted.

CMS-first: магазин включается настройкой shop.catalog.enabled, цена читается
из shop.catalog.default_price_root (per-key цена — отдельный Sprint 8.18).
Правила живут в system_settings, в коде — только механизмы и валидация.

Идемпотентность: reference_id = f"{item.id}:{n}", где n — порядковый номер
покупки ключа (счётчик берётся из player_item.quantity ДО инкремента).
Сквозные unique-индексы WalletTransaction (wallet_id, reference_type,
reference_id) и InventoryEvent (player_item_id, event_type, reference_type,
reference_id) — те же, что у fallback-покупки (шаг 4.4) и наград
mission_engine, поэтому миграций под идемпотентность не требуется.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo_team_runtime_models import InventoryEvent
from app.models import (
    Item,
    PlayerItem,
    SystemSetting,
    Wallet,
    WalletTransaction,
)

logger = logging.getLogger(__name__)

# Ключи каталога в system_settings (CMS-first): флаг и цена не хардкодятся.
SHOP_ENABLED_KEY = "shop.catalog.enabled"
SHOP_PRICE_ROOT_KEY = "shop.catalog.default_price_root"

# Reference-тип покупки каталога. Уникальные индексы ledger —
# (wallet_id, reference_type, reference_id) на WalletTransaction и
# (player_item_id, event_type, reference_type, reference_id) на InventoryEvent —
# делают покупку естественно идемпотентной через reference_id.
SHOP_PURCHASE_REFERENCE_TYPE = "shop_purchase"
INVENTORY_CREDITED_EVENT_TYPE = "credited"

ROOT_CURRENCY = "ROOT"


def _read_setting(session: Session, key: str, default=None):
    """Значение настройки из system_settings либо default (до/без seeding)."""
    row = session.get(SystemSetting, key)
    if row is not None:
        return row.value_json
    return default


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _get_root_wallet_for_update(session: Session, player_id: str) -> Wallet:
    """ROOT-кошелёк игрока с FOR UPDATE (создаётся при отсутствии).

    PostgreSQL лочит ряд до конца транзакции; SQLite игнорирует FOR UPDATE,
    реальную защиту от гонки дают unique-индексы ledger.
    """
    wallet = session.scalar(
        select(Wallet)
        .where(Wallet.player_id == player_id, Wallet.currency == ROOT_CURRENCY)
        .with_for_update()
    )
    if wallet is None:
        wallet = Wallet(
            id=_new_id("wallet"),
            player_id=player_id,
            currency=ROOT_CURRENCY,
            available_balance=0,
            locked_balance=0,
        )
        session.add(wallet)
        session.flush()
    return wallet


def list_catalog_items(session: Session, player_id: str) -> list[dict]:
    """Список всех published KEY items с ценой и owned-количеством игрока.

    Presentation-правила (Sprint 8.16):
    - shop.catalog.enabled is not True -> пустой список;
    - shop.catalog.default_price_root не положительное целое -> пустой список;
    - в список попадают только Item(category=KEY, status=published);
    - owned — стэк игрока из player_items (0, если ещё не покупал).
    """
    if _read_setting(session, SHOP_ENABLED_KEY, False) is not True:
        return []

    price = _read_setting(session, SHOP_PRICE_ROOT_KEY, 100)
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        return []

    items = session.scalars(
        select(Item)
        .where(Item.category == "KEY", Item.status == "published")
        .order_by(Item.title, Item.code)
    ).all()

    owned_rows = session.execute(
        select(PlayerItem.item_id, PlayerItem.quantity).where(
            PlayerItem.player_id == player_id,
        )
    ).all()
    owned = {item_id: quantity for item_id, quantity in owned_rows}

    return [
        {
            "itemId": item.id,
            "code": item.code,
            "title": item.title,
            "symbol": item.symbol,
            "category": item.category,
            "rarity": item.rarity,
            "priceRoot": price,
            "owned": owned.get(item.id, 0),
        }
        for item in items
    ]


def _build_purchase_result(
    item: Item,
    price: int,
    root_balance: int,
    owned: int,
) -> dict:
    """Компактный результат покупки из каталога (без bootstrap)."""
    return {
        "purchased": True,
        "itemId": item.id,
        "code": item.code,
        "title": item.title,
        "priceRoot": price,
        "rootBalance": root_balance,
        "owned": owned,
    }


def purchase_catalog_item(
    session: Session,
    player_id: str,
    item_id: str,
) -> dict:
    """Купить ключ из общего каталога за ROOT (без квоты).

    Единственная атомарная транзакция (вызывать внутри SessionLocal.begin()):
    pre-checks -> идемпотентный возврат -> debit -> credit.
    """
    # Lazy import из-за циклической связи модулей: mission_engine импортирует
    # fallback_shop на верхнем уровне (create_first_failure_entitlement), а
    # shop_service может импортироваться теми же модулями в будущем.
    from app.mission_engine import MissionEngineError

    if _read_setting(session, SHOP_ENABLED_KEY, False) is not True:
        raise MissionEngineError(409, "Магазин отключён.")

    price = _read_setting(session, SHOP_PRICE_ROOT_KEY, 100)
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        logger.warning(
            "catalog purchase rejected: %s is not a positive integer (item_id=%s)",
            SHOP_PRICE_ROOT_KEY,
            item_id,
        )
        raise MissionEngineError(409, "Цена не настроена.")

    item = session.get(Item, item_id)
    if item is None or item.category != "KEY" or item.status != "published":
        raise MissionEngineError(404, "Товар не найден.")

    # PlayerItem — существующая строка стака либо новая.
    player_item = session.scalar(
        select(PlayerItem).where(
            PlayerItem.player_id == player_id,
            PlayerItem.item_id == item.id,
        )
    )
    if player_item is None:
        player_item = PlayerItem(
            id=_new_id("player-item"),
            player_id=player_id,
            item_id=item.id,
            quantity=0,
            obtained_from_type="shop_purchase",
            obtained_from_id=None,
        )
        session.add(player_item)
        session.flush()  # нужен player_item.id для InventoryEvent

    # reference_id от порядкового номера покупки ключа: детерминированный,
    # растёт вместе с quantity, уникален на (player_item/wallet, reference_type).
    reference_id = f"{item.id}:{player_item.quantity + 1}"

    wallet = _get_root_wallet_for_update(session, player_id)

    # Идемпотентность (в т.ч. гонка двух параллельных POST): если проводка под
    # нашим reference_id уже закоммичена, повторный POST возвращает тот же
    # результат и НЕ списывает ROOT повторно. Проверка стоит ДО проверки
    # баланса: повтор уже успешной покупки не должен падать на
    # «Недостаточно ROOT», если баланс к этому времени изменился.
    existing = session.scalar(
        select(WalletTransaction.id).where(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.reference_type == SHOP_PURCHASE_REFERENCE_TYPE,
            WalletTransaction.reference_id == reference_id,
        )
    )
    if existing is not None:
        # player_item.quantity уже отражает закоммиченный стэк.
        return _build_purchase_result(
            item,
            price,
            wallet.available_balance,
            player_item.quantity,
        )

    if wallet.available_balance < price:
        raise MissionEngineError(409, "Недостаточно ROOT.")

    # Списание ROOT. amount всегда положительный (инвариант 4.1):
    # transaction_type="debit" определяет направление.
    wallet.available_balance -= price
    session.add(
        WalletTransaction(
            id=_new_id("wallet-transaction"),
            wallet_id=wallet.id,
            amount=price,
            balance_after=wallet.available_balance,
            transaction_type="debit",
            reason=f"Shop purchase: {item.code}",
            reference_type=SHOP_PURCHASE_REFERENCE_TYPE,
            reference_id=reference_id,
            metadata_json={"itemId": item.id},
        )
    )

    # Выдача ключа: PlayerItem upsert + immutable InventoryEvent("credited").
    player_item.quantity += 1
    session.add(
        InventoryEvent(
            id=_new_id("inventory-event"),
            player_item_id=player_item.id,
            mission_run_id=None,
            event_type=INVENTORY_CREDITED_EVENT_TYPE,
            quantity_delta=1,
            reference_type=SHOP_PURCHASE_REFERENCE_TYPE,
            reference_id=reference_id,
            metadata_json={"itemId": item.id},
        )
    )

    session.flush()

    return _build_purchase_result(
        item,
        price,
        wallet.available_balance,
        player_item.quantity,
    )