from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.geo_team_runtime_models import InventoryEvent, PlayerFallbackEntitlement
from app.key_price import resolve_key_price
from app.models import (
    Item,
    KeyRules,
    Mission,
    MissionReward,
    PlayerItem,
    PlayerMission,
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


def mission_has_purchasable_key_reward(
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


def _resolve_fallback_key_item(
    session: Session,
    entitlement: PlayerFallbackEntitlement,
) -> Item | None:
    """Предмет, на который выдан entitlement (4.3b/4.4, Sprint 8.16).

    Основной источник — entitlement.item_id: у миссии может быть несколько
    ключей-наград, и каждый entitlement адресует свой item. Для legacy-строк
    (item_id NULL до миграции add item_id) — первый опубликованный
    ключ-награда миссии (до Sprint 8.16 такой ключ был один).

    Если item_id заполнен, но предмет недоступен (нет/unpublished/без
    KeyRules) — возвращаем None (fallback НЕ делаем, чтобы не подсовывать
    игроку другой предмет): оффер помечается disabled / покупка отдаёт 409.
    """
    if entitlement.item_id:
        item = session.get(Item, entitlement.item_id)
        if item is None or item.status != "published":
            return None
        key_rules = session.scalar(select(KeyRules).where(KeyRules.item_id == item.id))
        if key_rules is None:
            return None
        return item
    return mission_has_purchasable_key_reward(session, entitlement.mission_id)


def is_key_reserved_for_player(
    session: Session,
    player_id: str,
    mission_id: str,
    item_id: str | None = None,
) -> bool:
    """Sprint 8.14/8.16: ключ уже зарезервирован в fallback-магазине?

    True, если для (player_id, mission_id) существует PlayerFallbackEntitlement
    (при item_id is None — любой), либо — Sprint 8.16 — entitlement именно на
    этот ключ (item_id). В обоих случаях item-награда при успехе НЕ выдаётся:
    ключ уже в магазине.
    """
    query = select(PlayerFallbackEntitlement.id).where(
        PlayerFallbackEntitlement.player_id == player_id,
        PlayerFallbackEntitlement.mission_id == mission_id,
    )
    if item_id is not None:
        query = query.where(PlayerFallbackEntitlement.item_id == item_id)
    existing = session.scalar(query)
    return existing is not None


def close_unspent_after_award(
    session: Session,
    player_id: str,
    mission_id: str,
    awarded_item_ids: list[str],
) -> None:
    """Sprint 8.17.13-fix: закрыть невыкупленный fallback-депозит после награды.

    Баг: игрок провалил 1-ю попытку в заходе → создан entitlement (available,
    quota=1). Не купил. В новом заходе успех с 1-й → ключ выдан наградой, но
    старый available-оффер остался в магазине → можно купить второй ключ.
    Нарушение XOR «ключ либо награда, либо магазин» между заходами.

    Фикс: при выдаче ключа наградой срезаем невыкупленный остаток у entitlement
    (quota_limit = consumed_count, status = exhausted). Уже выкупленное не
    трогаем (consumed_count >= quota_limit → no-op), disabled (админский флаг)
    не трогаем. Инвариант XOR становится верным и между заходами.
    """
    if not awarded_item_ids:
        return
    unique_item_ids = {item_id for item_id in awarded_item_ids if item_id}
    if not unique_item_ids:
        return
    for item_id in unique_item_ids:
        entitlement = session.scalar(
            select(PlayerFallbackEntitlement)
            .where(
                PlayerFallbackEntitlement.player_id == player_id,
                PlayerFallbackEntitlement.mission_id == mission_id,
                PlayerFallbackEntitlement.item_id == item_id,
            )
            .with_for_update()
        )
        if entitlement is None:
            continue
        if entitlement.status == "disabled":
            continue  # админский флаг — не трогаем
        if entitlement.consumed_count >= entitlement.quota_limit:
            continue  # уже выкуплено — no-op
        entitlement.quota_limit = entitlement.consumed_count
        entitlement.status = "exhausted"


def create_first_failure_entitlements(
    session: Session,
    player_id: str,
    mission_id: str,
    *,
    attempt_count_before: int,
) -> None:
    """Создать персональный fallback-entitlement на КАЖДЫЙ ключ-награду (4.3a).

    Sprint 8.16: при провале первой попытки в fallback-магазин попадают ВСЕ
    item-награды миссии (каждая отдельным entitlement'ом), подтверждённые
    KeyRules из CMS. Повторные провалы внутри захода (attempt_count_before != 0)
    ничего не добавляют, а новый заход переармирует существующие entitlement'ы
    (Sprint 8.17): quota_limit накапливается на reward.amount каждого захода,
    consumed_count сохраняется (шаг 8b).

    V1 semantics (docs/fallback-shop-contract.md): первый неверный ответ создаёт
    entitlement'ы независимо от того, есть ли у миссии платная entry policy
    (работает и для бесплатных/legacy-миссий). Вызывать строго внутри транзакции
    submit_mission после успешного _consume_entry_resources и только когда
    _validate_submission вернул False. offer_id = item.id (Sprint 8.16:
    предложение адресует сам ключ, а не CMS-продукт из настроек).
    """
    if attempt_count_before != 0:
        return

    if _read_setting(session, FALLBACK_ENABLED_KEY) is not True:
        return

    quota_limit = _read_setting(session, FALLBACK_QUOTA_LIMIT_KEY)
    if (
        not isinstance(quota_limit, int)
        or isinstance(quota_limit, bool)
        or quota_limit < 1
    ):
        logger.warning(
            "fallback entitlements skipped: shop.fallback.default_quota_limit is not "
            "a positive integer (player_id=%s, mission_id=%s)",
            player_id,
            mission_id,
        )
        return

    # Sprint 8.17 (шаг 8): номер текущего захода — маркер для re-arm.
    # Читаем PlayerMission из сессии (identity-map вернёт тот же объект, что
    # в submit-потоке): entry_count уже инкрементирован при accept нового
    # захода. Если PlayerMission нет (прямой вызов вне миссии) — 0.
    player_mission = session.scalar(
        select(PlayerMission).where(
            PlayerMission.player_id == player_id,
            PlayerMission.mission_id == mission_id,
        )
    )
    current_entry_count = (
        player_mission.entry_count if player_mission is not None else 0
    )

    rewards = session.scalars(
        select(MissionReward).where(
            MissionReward.mission_id == mission_id,
            MissionReward.reward_type == "item",
            MissionReward.item_id.is_not(None),
        )
    ).all()

    for reward in rewards:
        item = session.get(Item, reward.item_id)
        if item is None or item.status != "published":
            continue
        key_rules = session.scalar(select(KeyRules).where(KeyRules.item_id == item.id))
        if key_rules is None:
            continue
        existing = session.scalar(
            select(PlayerFallbackEntitlement).where(
                PlayerFallbackEntitlement.player_id == player_id,
                PlayerFallbackEntitlement.mission_id == mission_id,
                PlayerFallbackEntitlement.item_id == item.id,
            )
        )
        if existing is not None:
            # Sprint 8.17 (шаг 8b): НАКОПЛЕНИЕ между заходами. quota_limit —
            # «сколько всего депонировано» (растёт), consumed_count — «сколько
            # куплено». Re-arm на новый заход НЕ сбрасывает consumed_count, а
            # добавляет депозит текущего захода (reward.amount) к quota_limit.
            # Guard attempt_count_before == 0 выше гарантирует: не чаще раза
            # за заход. "disabled" не трогаем — админский отключатель выше.
            if (
                existing.run_entry_count != current_entry_count
                and existing.status in ("available", "exhausted")
            ):
                deposit_amount = reward.amount or 1
                existing.quota_limit += deposit_amount
                existing.run_entry_count = current_entry_count
                # Статус выводится из остатка: осталось что купить → available.
                if existing.consumed_count < existing.quota_limit:
                    existing.status = "available"
                else:
                    existing.status = "exhausted"
            continue
        # Sprint 8.17 (шаг 8b): quota_limit = «сколько ключей депонировано».
        # При создании — количество из награды миссии (reward.amount), а не
        # system_settings.default_quota_limit (настройка остаётся сентинелом
        # конфигурации, см. guard выше).
        deposit_amount = reward.amount or 1
        session.add(
            PlayerFallbackEntitlement(
                id=_new_id("fallback-entitlement"),
                player_id=player_id,
                mission_id=mission_id,
                item_id=item.id,
                offer_id=item.id,
                quota_limit=deposit_amount,
                consumed_count=0,
                run_entry_count=current_entry_count,
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

        item = _resolve_fallback_key_item(session, entitlement)
        effective_status = entitlement.status if item is not None else "disabled"
        remaining_quota = max(0, entitlement.quota_limit - entitlement.consumed_count)

        offers.append(
            {
                "missionId": entitlement.mission_id,
                "entitlementId": entitlement.id,
                "missionSlug": mission.slug,
                "missionTitle": mission.title,
                "offerId": entitlement.offer_id,
                "priceRoot": resolve_key_price(
                    session,
                    item.id if item is not None else None,
                    global_setting_key=FALLBACK_PRICE_ROOT_KEY,
                    default=1,
                ),
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
    Идемпотентность: reference_id = f"{entitlement.id}:{run}:{n}" (run —
    run_entry_count захода, Sprint 8.17) со сквозными unique-индексами
    WalletTransaction и InventoryEvent.
    """
    # Lazy import из-за циклической связи модулей: mission_engine импортирует
    # fallback_shop на верхнем уровне (create_first_failure_entitlements).
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

    item = _resolve_fallback_key_item(session, entitlement)
    if item is None:
        raise MissionEngineError(409, "Ключ недоступен.")

    price = resolve_key_price(
        session,
        item.id,
        global_setting_key=FALLBACK_PRICE_ROOT_KEY,
        default=1,
    )
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
            committed_reference_id = (
                f"{entitlement.id}:{entitlement.run_entry_count}:"
                f"{entitlement.consumed_count}"
            )
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
    # Sprint 8.17 (шаг 8/8b): reference_id = {id}:{run}:{count}. run_entry_count
    # и монотонный consumed_count (после re-arm квота копится, consumed НЕ
    # сбрасывается) дают сквозную уникальность: проводки каждого захода имеют
    # свой reference_id и не конфликтуют с прошлыми заходами.
    reference_id = f"{entitlement.id}:{entitlement.run_entry_count}:{new_count}"

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

