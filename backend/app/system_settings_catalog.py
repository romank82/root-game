from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SystemSettingDefinition:
    key: str
    value_type: str
    default_value: int | bool | str | list[float] | list[str]
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
    "economy.gas_fee_percent": SystemSettingDefinition(
        key="economy.gas_fee_percent",
        value_type="integer",
        default_value=1,
        category="economy",
        title="Процент газа за перевод",
        description="Сколько газа списывается за перевод ROOT (% от суммы).",
        is_sensitive=True,
    ),
    "economy.gas_pack_10": SystemSettingDefinition(
        key="economy.gas_pack_10",
        value_type="integer",
        default_value=10,
        category="economy",
        title="Пакет газа: 10",
        description="Стоимость пакета 10 газа в звёздах Telegram.",
        is_sensitive=True,
    ),
    "economy.gas_pack_100": SystemSettingDefinition(
        key="economy.gas_pack_100",
        value_type="integer",
        default_value=80,
        category="economy",
        title="Пакет газа: 100",
        description="Стоимость пакета 100 газа в звёздах Telegram.",
        is_sensitive=True,
    ),
    "economy.gas_pack_1000": SystemSettingDefinition(
        key="economy.gas_pack_1000",
        value_type="integer",
        default_value=700,
        category="economy",
        title="Пакет газа: 1000",
        description="Стоимость пакета 1000 газа в звёздах Telegram.",
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
    "economy.mission_force_complete_approval_threshold": SystemSettingDefinition(
        key="economy.mission_force_complete_approval_threshold",
        value_type="integer",
        default_value=5000,
        category="economy",
        title="Порог approval для принудительного завершения миссии",
        description=(
            "Сумма ROOT-наград миссии, начиная с которой "
            "mission-force-complete требует approval."
        ),
        is_sensitive=True,
    ),
    "ton.payout_wallet": SystemSettingDefinition(
        key="ton.payout_wallet",
        value_type="string",
        default_value="",
        category="ton",
        title="TON payout wallet",
        description="Адрес «спец» кошелька для выплат ROOT → TON.",
        is_sensitive=True,
    ),
    "ton.payout_wallet_public_key": SystemSettingDefinition(
        key="ton.payout_wallet_public_key",
        value_type="string",
        default_value="",
        category="ton",
        title="Публичный ключ кошелька выплат",
        description=(
            "Ed25519 публичный ключ кошелька выплат (hex, 32 байта). "
            "По нему проверяется подпись BOC от TON Connect: без него "
            "подтверждение выплат невозможно."
        ),
        is_sensitive=True,
    ),
    "ton.legacy_autopayout_enabled": SystemSettingDefinition(
        key="ton.legacy_autopayout_enabled",
        value_type="boolean",
        default_value=False,
        category="ton",
        title="Старая автовыплата (аварийно)",
        description=(
            "УСТАРЕЛО. Включает автоматическую отправку ROOT с сервера по "
            "мнемонике TON_PAYOUT_MNEMONIC из .env. Это возвращает риск "
            "утечки ключа: используйте вкладку «Батчи выплат» с подписью в "
            "кошельке. Держать выключенным, кроме аварийной ситуации."
        ),
        is_sensitive=True,
    ),
    "ton.payout_processing_timeout_hours": SystemSettingDefinition(
        key="ton.payout_processing_timeout_hours",
        value_type="integer",
        default_value=24,
        category="ton",
        title="Таймаут обработки батча выплат",
        description=(
            "Сколько часов батч может висеть неподтверждённым, прежде чем "
            "фоновый джоб вернёт его заявки в pending. Защита от забытого "
            "батча, который держит деньги игроков."
        ),
        is_sensitive=False,
    ),
    "ton.payout_auto_confirm_enabled": SystemSettingDefinition(
        key="ton.payout_auto_confirm_enabled",
        value_type="boolean",
        default_value=True,
        category="ton",
        title="Автоподтверждение выплат",
        description=(
            "Фоновый джоб сам повторяет сверку с блокчейном по сохранённому "
            "подписанному BOC и подтверждает доставленные выплаты. Кнопка "
            "«Сверить» остаётся ручным дублем на случай отключения."
        ),
        is_sensitive=False,
    ),
    "ton.min_amount_root": SystemSettingDefinition(
        key="ton.min_amount_root",
        value_type="integer",
        default_value=10,
        category="ton",
        title="Минимум вывода ROOT",
        description="Минимальная сумма вывода ROOT в TON (целый ROOT).",
        is_sensitive=False,
    ),
    "ton.daily_withdrawal_limit": SystemSettingDefinition(
        key="ton.daily_withdrawal_limit",
        value_type="integer",
        default_value=5000,
        category="ton",
        title="Дневной лимит вывода ROOT",
        description="Дневной лимит вывода ROOT в TON на игрока.",
        is_sensitive=False,
    ),
    "ton.withdrawal_enabled": SystemSettingDefinition(
        key="ton.withdrawal_enabled",
        value_type="boolean",
        default_value=False,
        category="ton",
        title="Вывод ROOT в TON включён",
        description="Глобальный переключатель вывода ROOT → TON.",
        is_sensitive=False,
    ),
    "ton.deposit_enabled": SystemSettingDefinition(
        key="ton.deposit_enabled",
        value_type="boolean",
        default_value=False,
        category="ton",
        title="Депозит ROOT-jetton включён",
        description="Рубильник депозита ROOT-jetton (входящие).",
        is_sensitive=False,
    ),
    "ton.min_deposit_root": SystemSettingDefinition(
        key="ton.min_deposit_root",
        value_type="integer",
        default_value=1,
        category="ton",
        title="Минимум депозита ROOT",
        description="Минимальная сумма депозита ROOT-jetton (в ROOT).",
        is_sensitive=False,
    ),
    "ton.deposit_wallet": SystemSettingDefinition(
        key="ton.deposit_wallet",
        value_type="string",
        default_value="",
        category="ton",
        title="TON deposit wallet",
        description="Адрес «спец» кошелька для приёма ROOT-jetton (депозит).",
        is_sensitive=True,
    ),
    "gameplay.manual_item_adjustment_approval_threshold": SystemSettingDefinition(
        key="gameplay.manual_item_adjustment_approval_threshold",
        value_type="integer",
        default_value=5,
        category="gameplay",
        title="Порог approval для ручной выдачи/отзыва предметов",
        description="Количество предметов, с которого ручная выдача/отзыв ключа требует approval.",
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
    "shop.catalog.enabled": SystemSettingDefinition(
        key="shop.catalog.enabled",
        value_type="boolean",
        default_value=True,
        category="shop",
        title="Магазин ключей включён",
        description="Если true — общий каталог ключей доступен игрокам.",
        is_sensitive=False,
    ),
    "shop.catalog.default_price_root": SystemSettingDefinition(
        key="shop.catalog.default_price_root",
        value_type="integer",
        default_value=100,
        category="shop",
        title="Цена ключа в магазине",
        description="Цена одного ключа в ROOT (atomic units).",
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
    "monitoring.global_threshold": SystemSettingDefinition(
        key="monitoring.global_threshold",
        value_type="integer",
        default_value=100,
        category="monitoring",
        title="Глобальный порог ошибок группы",
        description=(
            "Минимальное число ошибок в группе (COUNT(*)), начиная с которого "
            "группа помечается isGlobal в /admin/monitoring/error-groups."
        ),
        is_sensitive=False,
    ),
    # Sprint Trans-2b-1: источник истины для ручного перевода контента
    # (миссии, сезоны, главы, сегменты, story_nodes). Новый язык добавляется
    # здесь — API и админка подхватывают его из CMS, без деплоя и миграции.
    # Коды строго двухбуквенные латинские в нижнем регистре (совместимо с
    # i18next supportedLngs на фронте).
    "content.supported_languages": SystemSettingDefinition(
        key="content.supported_languages",
        value_type="json",
        default_value=["ru", "en", "zh"],
        category="content",
        title="Поддерживаемые языки контента",
        description=(
            "Языки, на которые переводится контент (миссии, сезоны и т.д.). "
            "Новый язык добавляется здесь — система подхватит его автоматически."
        ),
        is_sensitive=False,
    ),
    # Sprint Referral R-2: реферальная программа (механика — R-3…R-6).
    # referral.enabled — рубильник: по умолчанию выключен, включение — осознанное
    # решение через CMS, а не побочный эффект деплоя. referral.reward_root —
    # сумма ROOT пригласившему, когда приглашённый достигает порога переводов
    # (economy.transfer_minimum_earned_root). is_sensitive=True: денежный
    # параметр, правка не-суперадмином — только через approval workflow.
    "referral.enabled": SystemSettingDefinition(
        key="referral.enabled",
        value_type="boolean",
        default_value=False,
        category="referral",
        title="Реферальная программа вкл/выкл",
        description=(
            "Если true — пригласивший получает ROOT, когда приглашённый "
            "достигает порога переводов."
        ),
        is_sensitive=False,
    ),
    "referral.reward_root": SystemSettingDefinition(
        key="referral.reward_root",
        value_type="integer",
        default_value=25,
        category="referral",
        title="Вознаграждение за приглашение (ROOT)",
        description=(
            "Сколько ROOT получает пригласивший, когда приглашённый "
            "достигает порога переводов."
        ),
        is_sensitive=True,
    ),
    "telegram.bot_username": SystemSettingDefinition(
        key="telegram.bot_username",
        value_type="string",
        default_value="",
        category="telegram",
        title="Имя Telegram-бота (username)",
        description=(
            "Username бота без @ (например, HimeraProtocolBot). "
            "Используется для сборки реферальной ссылки. "
            "Пустое значение — fallback на env TELEGRAM_BOT_USERNAME."
        ),
        is_sensitive=False,
    ),
    # Sprint 8.5-2b: гейт solo location-proof в submit_mission.
    # default "off" — старые клиенты и тесты без ключа не затрагиваются.
    # "enforce" + нет свежего verified LocationProof по zone.slug -> 409.
    "geo.solo_proof_mode": SystemSettingDefinition(
        key="geo.solo_proof_mode",
        value_type="string",
        default_value="off",
        category="geo",
        title="Гейт solo location-proof",
        description="Sprint 8.5: solo location-proof gate (off|enforce).",
        is_sensitive=False,
    ),
    # Sprint 8.9.e: античит solo location-proof (CMS-пороги вместо констант).
    # Значения-дефолты идентичны константам geo_anticheat и seed-миграции
    # d4e7a1c93b52 — поведение системы до/после перехода не меняется.
    "geo.anticheat_mode": SystemSettingDefinition(
        key="geo.anticheat_mode",
        value_type="string",
        default_value="flag",
        category="geo",
        title="Режим античита",
        # B7 (Security-Audit): "enforce" переименован в "review" — режим
        # никогда не блокировал, только писал флаг и ставил review.
        description="Sprint 8.9: античит solo location-proof (off|flag|review).",
        is_sensitive=False,
    ),
    "geo.anticheat_max_speed_kmh": SystemSettingDefinition(
        key="geo.anticheat_max_speed_kmh",
        value_type="integer",
        default_value=120,
        category="geo",
        title="Порог скорости античита (км/ч)",
        description="Скорость spawn->proof выше порога даёт velocity-сигнал.",
        is_sensitive=False,
    ),
    "geo.anticheat_min_elapsed_seconds": SystemSettingDefinition(
        key="geo.anticheat_min_elapsed_seconds",
        value_type="integer",
        default_value=5,
        category="geo",
        title="Минимальный интервал античита (с)",
        description="Меньший интервал spawn->proof не проверяется на velocity.",
        is_sensitive=False,
    ),
    "geo.anticheat_accuracy_min_meters": SystemSettingDefinition(
        key="geo.anticheat_accuracy_min_meters",
        value_type="integer",
        default_value=3,
        category="geo",
        title="Порог «идеальной» accuracy (м)",
        description="Accuracy не выше порога считается подозрительно идеальной.",
        is_sensitive=False,
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
        if definition.key == "geo.anticheat_max_speed_kmh" and not 1 <= value <= 1000:
            raise ValueError("geo.anticheat_max_speed_kmh должен быть от 1 до 1000.")
        if definition.key == "geo.anticheat_min_elapsed_seconds" and not 1 <= value <= 300:
            raise ValueError("geo.anticheat_min_elapsed_seconds должен быть от 1 до 300.")
        if definition.key == "geo.anticheat_accuracy_min_meters" and not 0 <= value <= 100:
            raise ValueError("geo.anticheat_accuracy_min_meters должен быть от 0 до 100.")
        return

    if definition.value_type == "boolean":
        if not isinstance(value, bool):
            raise ValueError("Значение должно быть boolean.")
        return

    if definition.value_type == "string":
        if not isinstance(value, str):
            raise ValueError("Значение должно быть строкой.")
        if definition.key == "geo.solo_proof_mode" and value not in ("off", "enforce"):
            raise ValueError("geo.solo_proof_mode должен быть 'off' или 'enforce'.")
        if definition.key == "geo.anticheat_mode" and value not in (
            "off",
            "flag",
            "review",
        ):
            raise ValueError(
                "geo.anticheat_mode должен быть 'off', 'flag' или 'review'. "
                "Устаревшее 'enforce' читается как 'review'."
            )
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

    # Sprint Trans-2b-1: value_type="json" проверяется по ключу (как и
    # множители выше), потому что общий json-бранч отсутствует. Без этой ветки
    # validate_catalog_values() падал бы на любом PUT system-settings с
    # «Неизвестный тип или ключ системной настройки.».
    if definition.key == "content.supported_languages":
        if not isinstance(value, list) or not value:
            raise ValueError(
                "Список языков контента должен быть непустым JSON-массивом."
            )
        if any(
            not isinstance(item, str) or re.fullmatch(r"[a-z]{2}", item) is None
            for item in value
        ):
            raise ValueError(
                "Каждый язык должен быть двухбуквенным латинским кодом "
                "в нижнем регистре (например, ru, en, zh)."
            )
        if len(set(value)) != len(value):
            raise ValueError("Коды языков не могут повторяться.")
        return

    raise ValueError("Неизвестный тип или ключ системной настройки.")


def validate_catalog_values(values_by_key: dict[str, Any]) -> None:
    """
    Validate individual values and cross-setting invariants.

    The caller must supply the effective values of the whole active catalog,
    with a proposed value substituted before calling this function.
    """
    # Sprint 8.5-5: строгий инвариант восстановлен после seed-миграции
    # geo.solo_proof_mode (b8f2c4d6e9a1). Все ключи каталога обязаны быть в
    # БД: иначе PUT /api/v1/admin/system-settings/{key} отдавал бы 422
    # «Отсутствует системная настройка: <key>.». Downgrade seed-миграций
    # запрещён (append-only), поэтому ключи из БД не исчезают.
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
