from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.geo_team_runtime_models import InventoryEvent, PlayerFallbackEntitlement
from app.models import (
    Item,
    KeyRules,
    Mission,
    MissionReward,
    PlayerItem,
    SystemSetting,
    Wallet,
    WalletTransaction,
)
from app.system_settings_catalog import get_definition

logger = logging.getLogger(__name__)

# Ключи fallback-магазина (шаг 4.3a). Значения живут в system_settings
# (CMS-first): код читает настройки, а не хардкодит игровые правила.
FALLBACK_ENABLED_KEY = "shop.fallback.enabled"
FALLBACK_OFFER_ID_KEY = "shop.fallback.default_offer_id"
FALLBACK_QUOTA_LIMIT_KEY = "shop.fallback.default_quota_limit"
# Зарезервирован для 4.4+ (expires_at появится отдельной миграцией); в V1
# entitlement не имеет expires_at, поэтому значение не персистится.
FALLBACK_AVAILABLE_SECONDS_KEY = "shop.fallback.default_available_seconds"
# Цена fallback-ключа в ROOT (atomic units). Читается на каждый запрос —
# CMS-first: правило живёт в system_settings, а не в коде.
FALLBACK_PRICE_ROOT_KEY = "shop.fallback.default_price_root"

# Reference-тип покупки (шаг 4.4).  Уникальные индексы ledger —
# (wallet_id, reference_type, reference_id) на WalletTransaction и
# (player_item_id, event_type, reference_type, reference_id) на InventoryEvent —
# делают покупку естественно идемпотентной через reference_id.
FALLBACK_PURCHASE_REFERENCE_TYPE = "fallback_purchase"
INVENTORY_CREDITED_EVENT_TYPE = "credited"

ROOT_CURRENCY = "ROOT"


def _read_setting(session: Session, key: str):
    """Значение активной настройки либо default из каталога (до seeding)."""
    row = session.get(SystemSetting, key)
    if row is not None:
        return row.value_json

    definition = get_definition(key)
    return definition.default_value if definition is not None else None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _get_root_wallet_for_update(session: Session, player_id: str) -> Wallet | None:
    """ROOT-кошелёк игрока с FOR UPDATE.

    PostgreSQL лочит ряд до конца транзакции; SQLite игнорирует FOR UPDATE,
    реальную защиту от гонки дают unique-индексы ledger.
    """
    return session.scalar(
        select(Wallet)
        .where(Wallet.player_id == player_id, Wallet.currency == ROOT_CURRENCY)
        .with_for_update()
    )


def _mission_has_purchasable_key_reward(
    session: Session,
    mission_id: str,
) -> Item | None:
    """Первый published Item-награды миссии, подтверждённый KeyRules (CMS)."""
    item_reward = session.scalar(
        select(MissionReward)
        .where(
            MissionReward.mission_id == mission_id,
            MissionReward.reward_type == "item",
            MissionReward.item_id.is_not(None),
        )
        .order_by(MissionReward.sort_order, MissionReward.id)
    )
    if item_reward is None:
        return None

    item = session.get(Item, item_reward.item_id)
    if item is None or item.status != "published":
        return None

    key_rules = session.scalar(select(KeyRules).where(KeyRules.item_id == item.id))
    if key_rules is None:
        return None

    return item


def create_first_failure_entitlement(
    session: Session,
    player_id: str,
    mission_id: str,
    *,
    attempt_count_before: int,
) -> None:
    """Создать персональный fallback-entitlement после первого провала (4.3a).

    V1 semantics (docs/fallback-shop-contract.md): первый неверный ответ создаёт
    entitlement независимо от того, есть ли у миссии платная entry policy
    (работает и для бесплатных/legacy-миссий). Вызывать строго внутри транзакции
    submit_mission после успешного _consume_entry_resources и только когда
    _validate_submission вернул False.

    Идемпотентна: (player_id, mission_id) уникален в БД, а guard
    attempt_count_before != 0 исключает повторное создание при следующих
    провалах. Entitlement создаётся в статусе available с quota из настроек;
    покупка ключа — шаг 4.4.
    """
    if attempt_count_before != 0:
        return

    if _read_setting(session, FALLBACK_ENABLED_KEY) is not True:
        return

    offer_id = _read_setting(session, FALLBACK_OFFER_ID_KEY)
    if not isinstance(offer_id, str) or not offer_id.strip():
        logger.warning(
            "fallback entitlement skipped: shop.fallback.default_offer_id is empty "
            "(player_id=%s, mission_id=%s)",
            player_id,
            mission_id,
        )
        return

    quota_limit = _read_setting(session, FALLBACK_QUOTA_LIMIT_KEY)
    if (
        not isinstance(quota_limit, int)
        or isinstance(quota_limit, bool)
        or quota_limit < 1
    ):
        logger.warning(
            "fallback entitlement skipped: shop.fallback.default_quota_limit is not "
            "a positive integer (player_id=%s, mission_id=%s)",
            player_id,
            mission_id,
        )
        return

    if _mission_has_purchasable_key_reward(session, mission_id) is None:
        return

    existing = session.scalar(
        select(PlayerFallbackEntitlement).where(
            PlayerFallbackEntitlement.player_id == player_id,
            PlayerFallbackEntitlement.mission_id == mission_id,
        )
    )
    if existing is not None:
        return

    session.add(
        PlayerFallbackEntitlement(
            id=f"fallback-entitlement-{uuid4().hex}",
            player_id=player_id,
            mission_id=mission_id,
            offer_id=offer_id.strip(),
            quota_limit=quota_limit,
            consumed_count=0,
            status="available",
        )
    )
    session.flush()


def build_fallback_offers(session: Session, player_id: str) -> list[dict]:
    """Презентер персональных fallback-предложений игрока (4.3b).

    Возвращает только entitlement'ы запрошенного игрока и текущий CMS-статус
    предмета, плюс entitlementId (адрес пути для POST .../purchases, см. 4.4)
    и priceRoot из system_settings. Намеренно не включает pool/mode/expires,
    любые policy JSON и служебные метаданные (created_at, updated_at):
    публичная граница задана в docs/fallback-shop-contract.md.

    Presentation-правила:
    - shop.fallback.enabled is not True -> пустой список;
    - миссия не найдена (теоретически невозможно из-за FK RESTRICT) -> пропуск;
    - item не найден / не published / нет KeyRules -> status="disabled"
      (derived, в БД не пишется, entitlement.status не трогается).
    """
    if _read_setting(session, FALLBACK_ENABLED_KEY) is not True:
        return []

    entitlements = session.scalars(
        select(PlayerFallbackEntitlement).where(
            PlayerFallbackEntitlement.player_id == player_id,
        )
    ).all()

    offers: list[dict] = []
    for entitlement in entitlements:
        mission = session.get(Mission, entitlement.mission_id)
        if mission is None:
            continue

        item = _mission_has_purchasable_key_reward(session, entitlement.mission_id)
        effective_status = entitlement.status if item is not None else "disabled"
        remaining_quota = max(0, entitlement.quota_limit - entitlement.consumed_count)

        offers.append(
            {
                "missionId": entitlement.mission_id,
                "entitlementId": entitlement.id,
                "missionSlug": mission.slug,
                "missionTitle": mission.title,
                "offerId": entitlement.offer_id,
                "priceRoot": _read_setting(session, FALLBACK_PRICE_ROOT_KEY),
                "quotaLimit": entitlement.quota_limit,
                "consumedCount": entitlement.consumed_count,
                "remainingQuota": remaining_quota,
                "status": effective_status,
                "item": {
                    "id": item.id,
                    "slug": item.slug,
                    "code": item.code,
                    "title": item.title,
                    "symbol": item.symbol,
                    "category": item.category,
                    "rarity": item.rarity,
                }
                if item is not None
                else None,
            }
        )

    return offers


def get_fallback_offers(player_id: str) -> dict:
    """Точка вызова из HTTP-слоя: персональные офферы в формате {"offers": [...]}."""
    with SessionLocal.begin() as session:
        return {"offers": build_fallback_offers(session, player_id)}


def _build_purchase_result(
    entitlement: PlayerFallbackEntitlement,
    wallet: Wallet,
    item: Item,
    price: int,
) -> dict:
    """Компактный результат покупки (4.4). Без bootstrap и служебных метаданных."""
    return {
        "purchased": True,
        "entitlementId": entitlement.id,
        "consumedCount": entitlement.consumed_count,
        "remainingQuota": max(0, entitlement.quota_limit - entitlement.consumed_count),
        "status": entitlement.status,
        "priceRoot": price,
        "rootBalance": wallet.available_balance,
        "item": {
            "id": item.id,
            "slug": item.slug,
            "code": item.code,
            "title": item.title,
            "symbol": item.symbol,
            "category": item.category,
            "rarity": item.rarity,
        },
    }


def purchase_fallback_offer(
    session: Session,
    player_id: str,
    entitlement_id: str,
) -> dict:
    """Купить fallback-ключ за ROOT (шаг 4.4).

    Единственная атомарная транзакция (вызывать внутри SessionLocal.begin()):
    pre-checks -> идемпотентный возврат -> debit -> credit -> consumed/exhausted.
    Идемпотентность: reference_id = f"{entitlement.id}:{n}" со сквозными
    unique-индексами WalletTransaction и InventoryEvent.
    """
    # Lazy import из-за циклической связи модулей: mission_engine импортирует
    # fallback_shop на верхнем уровне (create_first_failure_entitlement).
    from app.mission_engine import MissionEngineError

    entitlement = session.scalar(
        select(PlayerFallbackEntitlement)
        .where(
            PlayerFallbackEntitlement.id == entitlement_id,
            PlayerFallbackEntitlement.player_id == player_id,
        )
        .with_for_update()
    )
    if entitlement is None:
        raise MissionEngineError(404, "Предложение не найдено.")

    if _read_setting(session, FALLBACK_ENABLED_KEY) is not True:
        raise MissionEngineError(409, "Магазин отключён.")

    item = _mission_has_purchasable_key_reward(session, entitlement.mission_id)
    if item is None:
        raise MissionEngineError(409, "Ключ недоступен.")

    price = _read_setting(session, FALLBACK_PRICE_ROOT_KEY)
    if not isinstance(price, int) or isinstance(price, bool) or price <= 0:
        logger.warning(
            "fallback purchase rejected: %s is not a positive integer "
            "(entitlement_id=%s)",
            FALLBACK_PRICE_ROOT_KEY,
            entitlement_id,
        )
        raise MissionEngineError(409, "Цена не настроена.")

    # Идемпотентный возврат committed-результата — ДО status-чеков: повторный
    # POST после успешной покупки (consumed_count == quota_limit, status уже
    # "exhausted") должен вернуть тот же результат, а не 409.
    if (
        entitlement.consumed_count > 0
        and entitlement.consumed_count >= entitlement.quota_limit
    ):
        wallet = _get_root_wallet_for_update(session, player_id)
        if wallet is not None:
            committed_reference_id = f"{entitlement.id}:{entitlement.consumed_count}"
            committed = session.scalar(
                select(WalletTransaction.id).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.reference_type
                    == FALLBACK_PURCHASE_REFERENCE_TYPE,
                    WalletTransaction.reference_id == committed_reference_id,
                )
            )
            if committed is not None:
                return _build_purchase_result(entitlement, wallet, item, price)

    if entitlement.status != "available":
        raise MissionEngineError(409, "Предложение недоступно.")

    if entitlement.consumed_count >= entitlement.quota_limit:
        raise MissionEngineError(409, "Квота исчерпана.")

    wallet = _get_root_wallet_for_update(session, player_id)
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

    if wallet.available_balance < price:
        raise MissionEngineError(409, "Недостаточно ROOT.")

    mission = session.get(Mission, entitlement.mission_id)
    if mission is None:
        # Теоретически невозможно (FK RESTRICT), но защищаемся явно.
        raise MissionEngineError(409, "Ключ недоступен.")

    new_count = entitlement.consumed_count + 1
    reference_id = f"{entitlement.id}:{new_count}"

    # Гонка двух параллельных POST: если проводка под нашим reference_id уже
    # закоммичена, вторая транзакция не должна дублировать списание.
    existing = session.scalar(
        select(WalletTransaction.id).where(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.reference_type == FALLBACK_PURCHASE_REFERENCE_TYPE,
            WalletTransaction.reference_id == reference_id,
        )
    )
    if existing is not None:
        return _build_purchase_result(entitlement, wallet, item, price)

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
            reason=f"Fallback purchase: {mission.slug}",
            reference_type=FALLBACK_PURCHASE_REFERENCE_TYPE,
            reference_id=reference_id,
            metadata_json={
                "entitlementId": entitlement.id,
                "missionId": mission.id,
                "itemId": item.id,
            },
        )
    )

    # Выдача ключа: PlayerItem upsert + immutable InventoryEvent("credited").
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
            obtained_from_type="fallback_purchase",
            obtained_from_id=entitlement.id,
        )
        session.add(player_item)
        session.flush()  # нужен player_item.id для InventoryEvent

    player_item.quantity += 1
    session.add(
        InventoryEvent(
            id=_new_id("inventory-event"),
            player_item_id=player_item.id,
            mission_run_id=None,
            event_type=INVENTORY_CREDITED_EVENT_TYPE,
            quantity_delta=1,
            reference_type=FALLBACK_PURCHASE_REFERENCE_TYPE,
            reference_id=reference_id,
            metadata_json={
                "entitlementId": entitlement.id,
                "missionId": mission.id,
                "itemId": item.id,
            },
        )
    )

    entitlement.consumed_count = new_count
    if new_count >= entitlement.quota_limit:
        entitlement.status = "exhausted"

    session.flush()

    return _build_purchase_result(entitlement, wallet, item, price)


def purchase_fallback_offer_entrypoint(player_id: str, entitlement_id: str) -> dict:
    """Точка вызова из HTTP-слоя: покупка в одной атомарной транзакции."""
    with SessionLocal.begin() as session:
        return purchase_fallback_offer(session, player_id, entitlement_id)

