from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.geo_team_runtime_models import PlayerFallbackEntitlement
from app.models import Item, KeyRules, Mission, MissionReward, SystemSetting
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


def _read_setting(session: Session, key: str):
    """Значение активной настройки либо default из каталога (до seeding)."""
    row = session.get(SystemSetting, key)
    if row is not None:
        return row.value_json

    definition = get_definition(key)
    return definition.default_value if definition is not None else None


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
    предмета. Намеренно не включает price/pool/mode/expires, любые policy JSON
    и служебные метаданные (created_at, updated_at): цена появится в 4.4 вместе
    со схемой продукта, а публичная граница задана в docs/fallback-shop-contract.md.

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
                "missionSlug": mission.slug,
                "missionTitle": mission.title,
                "offerId": entitlement.offer_id,
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
