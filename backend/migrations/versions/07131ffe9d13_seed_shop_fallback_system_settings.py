"""seed shop fallback system settings

Revision ID: 07131ffe9d13
Revises: 15ed269093cb
Create Date: 2026-10-07 00:30:13.122719

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07131ffe9d13'
down_revision: Union[str, Sequence[str], None] = '15ed269093cb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SHOP_FALLBACK_SETTINGS = [
    (
        "shop.fallback.enabled",
        False,
        "boolean",
        "shop",
        "Fallback-магазин после первого провала",
        "Включает персональный магазин после первого провала миссии.",
        False,
    ),
    (
        "shop.fallback.default_offer_id",
        "",
        "string",
        "shop",
        "Идентификатор fallback-предложения по умолчанию",
        "Ссылка на CMS product; значение offer_id entitlement (V1).",
        False,
    ),
    (
        "shop.fallback.default_quota_limit",
        1,
        "integer",
        "shop",
        "Лимит покупок fallback-ключа по умолчанию",
        "Сколько раз игрок может купить ключ по предложению (quota_limit).",
        False,
    ),
    (
        "shop.fallback.default_available_seconds",
        0,
        "integer",
        "shop",
        "Срок действия fallback-предложения по умолчанию",
        "0 = бессрочно; иначе секунды. Резерв для 4.4+ (в V1 не персистится).",
        False,
    ),
]


def upgrade() -> None:
    """Adds the 4 shop.fallback.* system_settings rows with catalog defaults.

    Append-only data migration (CMS-first): the rows must exist so that admin
    PUT /system-settings/{key} passes validate_catalog_values for the new
    catalog keys. created_at/updated_at are filled by server defaults
    (CURRENT_TIMESTAMP); is_sensitive/status also rely on row defaults.
    """
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
    op.bulk_insert(
        settings_table,
        [
            {
                "key": key,
                "value_json": value,
                "value_type": value_type,
                "category": category,
                "title": title,
                "description": description,
                "is_sensitive": sensitive,
                "status": "active",
            }
            for (
                key,
                value,
                value_type,
                category,
                title,
                description,
                sensitive,
            ) in SHOP_FALLBACK_SETTINGS
        ],
    )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )
