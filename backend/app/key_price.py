"""Резолв цены ключа (Sprint 8.20): per-key цена из key_rules.price.

Приоритет:
1. key_rules.price — положительное целое (per-key цена, задаётся в админке);
2. глобальная настройка system_settings[global_setting_key]
   (shop.fallback.default_price_root / shop.catalog.default_price_root);
3. переданный default.

Используется общим магазином (shop_service.py) и fallback-магазином
(fallback_shop.py). Логика списания/выдачи остаётся в вызывающих модулях —
здесь только источник цены (CMS-first: правило живёт в БД/настройках).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import KeyRules, SystemSetting
from app.system_settings_catalog import get_definition


def _read_global_setting(session: Session, key: str):
    """Значение активной настройки либо default из каталога (до seeding)."""
    row = session.get(SystemSetting, key)
    if row is not None:
        return row.value_json

    definition = get_definition(key)
    return definition.default_value if definition is not None else None


def _is_positive_price(value) -> bool:
    return (
        isinstance(value, int) and not isinstance(value, bool) and value > 0
    )


def resolve_key_price(
    session: Session,
    item_id: str | None,
    *,
    global_setting_key: str,
    default: int = 1,
) -> int:
    """Цена ключа: key_rules.price, иначе глобальная настройка, иначе default.

    item_id=None (компонент оффера без конкретного ключа, например
    disabled-предложение) — сразу глобальная настройка/default.
    """
    if item_id:
        rule = session.scalars(
            select(KeyRules).where(KeyRules.item_id == item_id)
        ).first()
        if rule is not None and _is_positive_price(rule.price):
            return rule.price  # type: ignore[return-value]

    global_price = _read_global_setting(session, global_setting_key)
    if _is_positive_price(global_price):
        return global_price  # type: ignore[return-value]
    return default