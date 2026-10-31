"""seed gas and ton system settings

Revision ID: dde2038a44d9
Revises: d4f0a1b2c3e7
Create Date: 2026-10-31

Зачем: validate_catalog_values() (app/system_settings_catalog.py) требует
присутствия ВСЕХ ключей код-каталога в таблице system_settings. Ключи
economy.gas_* добавлены в каталог в 51d43f1 (10.4-f, 2026-10-23), ton.* —
в e7a7fad (11.3, 2026-10-26), но data-seed к ним не приложен. Из-за этого на
любой БД, собранной из миграций, любой PUT /api/v1/admin/system-settings/{key}
отдавал 422 «Отсутствует системная настройка: economy.gas_fee_percent.».

Миграция append-only и идемпотентная: существующие строки (например,
вставленные вручную на dev) НЕ трогаются — вставляются только отсутствующие
ключи, поштучно (bulk_insert упал бы на PK при ручных строках). Значения
заморожены на момент миграции и должны совпадать с код-каталогом, иначе
admin_system_settings отдаёт 409 «Метаданные настройки не соответствуют
утверждённому каталогу». Только SQLAlchemy Core (sa.table + select/insert),
без диалект-специфичного SQL — работает и на SQLite, и на PostgreSQL.
created_at/updated_at заполняются server default (func.now()), как в
07131ffe9d13 / 6b9f3e7d2a15.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dde2038a44d9'
down_revision: Union[str, Sequence[str], None] = 'd4f0a1b2c3e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, value_json, value_type, category, title, description, is_sensitive)
GAS_AND_TON_SETTINGS = [
    (
        "economy.gas_fee_percent",
        1,
        "integer",
        "economy",
        "Процент газа за перевод",
        "Сколько газа списывается за перевод ROOT (% от суммы).",
        True,
    ),
    (
        "economy.gas_pack_10",
        10,
        "integer",
        "economy",
        "Пакет газа: 10",
        "Стоимость пакета 10 газа в звёздах Telegram.",
        True,
    ),
    (
        "economy.gas_pack_100",
        80,
        "integer",
        "economy",
        "Пакет газа: 100",
        "Стоимость пакета 100 газа в звёздах Telegram.",
        True,
    ),
    (
        "economy.gas_pack_1000",
        700,
        "integer",
        "economy",
        "Пакет газа: 1000",
        "Стоимость пакета 1000 газа в звёздах Telegram.",
        True,
    ),
    (
        "ton.payout_wallet",
        "",
        "string",
        "ton",
        "TON payout wallet",
        "Адрес «спец» кошелька для выплат ROOT → TON.",
        True,
    ),
    (
        "ton.min_amount_root",
        10,
        "integer",
        "ton",
        "Минимум вывода ROOT",
        "Минимальная сумма вывода ROOT в TON (целый ROOT).",
        False,
    ),
    (
        "ton.daily_withdrawal_limit",
        5000,
        "integer",
        "ton",
        "Дневной лимит вывода ROOT",
        "Дневной лимит вывода ROOT в TON на игрока.",
        False,
    ),
    (
        "ton.withdrawal_enabled",
        False,
        "boolean",
        "ton",
        "Вывод ROOT в TON включён",
        "Глобальный переключатель вывода ROOT → TON.",
        False,
    ),
]


def upgrade() -> None:
    """Adds the 8 missing catalog system_settings rows (10.4-f / 11.3).

    Идемпотентно: SELECT существующих ключей, затем поштучный INSERT только
    для отсутствующих. status='active' — иначе admin_system_settings не даст
    менять настройку (409 «Можно изменять только active системную настройку»).
    """
    bind = op.get_bind()

    settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.String()),
        sa.column("value_json", sa.JSON()),
        sa.column("value_type", sa.String()),
        sa.column("category", sa.String()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_sensitive", sa.Boolean()),
        sa.column("status", sa.String()),
    )

    existing_keys = set(
        bind.execute(sa.select(settings_table.c.key)).scalars().all()
    )

    for (
        key,
        value,
        value_type,
        category,
        title,
        description,
        sensitive,
    ) in GAS_AND_TON_SETTINGS:
        if key in existing_keys:
            continue
        bind.execute(
            settings_table.insert().values(
                key=key,
                value_json=value,
                value_type=value_type,
                category=category,
                title=title,
                description=description,
                is_sensitive=sensitive,
                status="active",
            )
        )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )
