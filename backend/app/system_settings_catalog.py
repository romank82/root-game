from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SystemSettingDefinition:
    key: str
    value_type: str
    default_value: int | bool | str | list[float]
    category: str
    title: str
    description: str
    is_sensitive: bool


SYSTEM_SETTING_CATALOG: dict[str, SystemSettingDefinition] = {
    "missions.max_active_solo": SystemSettingDefinition(
        key="missions.max_active_solo",
        value_type="integer",
        default_value=1,
        category="missions",
        title="Лимит активных solo-миссий",
        description="Максимальное число одновременно активных solo-миссий игрока.",
        is_sensitive=False,
    ),
    "missions.max_active_team": SystemSettingDefinition(
        key="missions.max_active_team",
        value_type="integer",
        default_value=1,
        category="missions",
        title="Лимит активных team-миссий",
        description="Максимальное число одновременно активных team-миссий игрока.",
        is_sensitive=False,
    ),
    "missions.max_active_global": SystemSettingDefinition(
        key="missions.max_active_global",
        value_type="integer",
        default_value=1,
        category="missions",
        title="Лимит активных global-миссий",
        description="Максимальное число одновременно активных global-миссий игрока.",
        is_sensitive=False,
    ),
    "missions.default_max_attempts": SystemSettingDefinition(
        key="missions.default_max_attempts",
        value_type="integer",
        default_value=3,
        category="missions",
        title="Число попыток по умолчанию",
        description="Число попыток для новых миссий без индивидуальной настройки.",
        is_sensitive=False,
    ),
    "missions.default_attempt_reward_multipliers": SystemSettingDefinition(
        key="missions.default_attempt_reward_multipliers",
        value_type="json",
        default_value=[1.0, 0.5, 0.25],
        category="missions",
        title="Множители награды за попытки",
        description="Множители награды для последовательных попыток миссии.",
        is_sensitive=False,
    ),
    "approvals.default_expiry_seconds": SystemSettingDefinition(
        key="approvals.default_expiry_seconds",
        value_type="integer",
        default_value=86400,
        category="approvals",
        title="Срок заявки по умолчанию",
        description="Срок действия новых approval-заявок в секундах.",
        is_sensitive=True,
    ),
    "economy.transfer_minimum_earned_root": SystemSettingDefinition(
        key="economy.transfer_minimum_earned_root",
        value_type="integer",
        default_value=50,
        category="economy",
        title="Порог заработанного ROOT для переводов",
        description="Подтверждённый выигрыш ROOT, требуемый для доступа к переводам.",
        is_sensitive=True,
    ),
    "economy.transfer_min_amount": SystemSettingDefinition(
        key="economy.transfer_min_amount",
        value_type="integer",
        default_value=1,
        category="economy",
        title="Минимальная сумма перевода",
        description="Минимальная сумма внутреннего перевода ROOT.",
        is_sensitive=True,
    ),
    "economy.transfer_max_amount": SystemSettingDefinition(
        key="economy.transfer_max_amount",
        value_type="integer",
        default_value=10000,
        category="economy",
        title="Максимальная сумма перевода",
        description="Максимальная сумма одного внутреннего перевода ROOT.",
        is_sensitive=True,
    ),
    "economy.daily_transfer_limit": SystemSettingDefinition(
        key="economy.daily_transfer_limit",
        value_type="integer",
        default_value=50000,
        category="economy",
        title="Дневной лимит переводов",
        description="Максимальная сумма внутренних переводов ROOT за сутки.",
        is_sensitive=True,
    ),
    "economy.manual_adjustment_approval_threshold": SystemSettingDefinition(
        key="economy.manual_adjustment_approval_threshold",
        value_type="integer",
        default_value=1000,
        category="economy",
        title="Порог approval для ручной корректировки",
        description="Сумма ROOT, с которой ручная корректировка требует approval.",
        is_sensitive=True,
    ),
    "shop.fallback.enabled": SystemSettingDefinition(
        key="shop.fallback.enabled",
        value_type="boolean",
        default_value=False,
        category="shop",
        title="Fallback-магазин после первого провала",
        description="Включает персональный магазин после первого провала миссии.",
        is_sensitive=False,
    ),
    "shop.fallback.default_offer_id": SystemSettingDefinition(
        key="shop.fallback.default_offer_id",
        value_type="string",
        default_value="",
        category="shop",
        title="Идентификатор fallback-предложения по умолчанию",
        description="Ссылка на CMS product; значение offer_id entitlement (V1).",
        is_sensitive=False,
    ),
    "shop.fallback.default_quota_limit": SystemSettingDefinition(
        key="shop.fallback.default_quota_limit",
        value_type="integer",
        default_value=1,
        category="shop",
        title="Лимит покупок fallback-ключа по умолчанию",
        description="Сколько раз игрок может купить ключ по предложению (quota_limit).",
        is_sensitive=False,
    ),
    "shop.fallback.default_available_seconds": SystemSettingDefinition(
        key="shop.fallback.default_available_seconds",
        value_type="integer",
        default_value=0,
        category="shop",
        title="Срок действия fallback-предложения по умолчанию",
        description="0 = бессрочно; иначе секунды. Резерв для 4.4+ (в V1 не персистится).",
        is_sensitive=False,
    ),
    "shop.fallback.default_price_root": SystemSettingDefinition(
        key="shop.fallback.default_price_root",
        value_type="integer",
        default_value=100,
        category="shop",
        title="Цена fallback-ключа в ROOT",
        description="Сколько ROOT игрок платит за покупку ключа из fallback-предложения (atomic units).",
        is_sensitive=False,
    ),
    "features.demo_seed_enabled": SystemSettingDefinition(
        key="features.demo_seed_enabled",
        value_type="boolean",
        default_value=False,
        category="features",
        title="Demo seed enabled",
        description="Зарезервированный флаг для ручного development demo seed.",
        is_sensitive=True,
    ),
    "features.demo_reset_enabled": SystemSettingDefinition(
        key="features.demo_reset_enabled",
        value_type="boolean",
        default_value=False,
        category="features",
        title="Demo reset enabled",
        description="Зарезервированный флаг для development-инструмента сброса demo-данных вне production (публичный reset удалён в 3.11.a).",
        is_sensitive=True,
    ),
}


def get_definition(key: str) -> SystemSettingDefinition | None:
    return SYSTEM_SETTING_CATALOG.get(key)


def validate_value(definition: SystemSettingDefinition, value: Any) -> None:
    """Validate a non-secret proposed setting value against its catalog schema."""
    if definition.value_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("Значение должно быть целым числом.")
        if value < 0:
            raise ValueError("Значение не может быть отрицательным.")
        if definition.key == "missions.default_max_attempts" and not 1 <= value <= 10:
            raise ValueError("missions.default_max_attempts должен быть от 1 до 10.")
        return

    if definition.value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Значение должно быть boolean.")
        return

    if definition.value_type == "string":
        if not isinstance(value, str):
            raise ValueError("Значение должно быть строкой.")
        return

    if definition.key == "missions.default_attempt_reward_multipliers":
        if not isinstance(value, list) or not value:
            raise ValueError("Множители должны быть непустым JSON-массивом.")
        if any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not 0 <= float(item) <= 1
            for item in value
        ):
            raise ValueError("Каждый множитель должен быть числом от 0 до 1.")
        if float(value[0]) != 1.0:
            raise ValueError("Первый множитель должен равняться 1.0.")
        if any(float(value[i]) > float(value[i - 1]) for i in range(1, len(value))):
            raise ValueError("Множители не могут возрастать.")
        return

    raise ValueError("Неизвестный тип или ключ системной настройки.")


def validate_catalog_values(values_by_key: dict[str, Any]) -> None:
    """
    Validate individual values and cross-setting invariants.

    The caller must supply the effective values of the whole active catalog,
    with a proposed value substituted before calling this function.
    """
    for key, definition in SYSTEM_SETTING_CATALOG.items():
        if key not in values_by_key:
            raise ValueError(f"Отсутствует системная настройка: {key}.")
        validate_value(definition, values_by_key[key])

    attempts = values_by_key["missions.default_max_attempts"]
    multipliers = values_by_key["missions.default_attempt_reward_multipliers"]
    if len(multipliers) != attempts:
        raise ValueError(
            "Число множителей должно совпадать с missions.default_max_attempts."
        )
