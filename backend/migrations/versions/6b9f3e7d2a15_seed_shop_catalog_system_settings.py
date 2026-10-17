"""seed shop catalog system settings

Revision ID: 6b9f3e7d2a15
Revises: 5c85930cfb3e
Create Date: 2026-10-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b9f3e7d2a15'
down_revision: Union[str, Sequence[str], None] = '5c85930cfb3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SHOP_CATALOG_SETTINGS = [
    (
        "shop.catalog.enabled",
        False,
        "boolean",
        "shop",
        "Общий магазин ключей",
        "Включает общий каталог ключей (все published KEY items, Sprint 8.16).",
        False,
    ),
    (
        "shop.catalog.default_price_root",
        100,
        "integer",
        "shop",
        "Цена ключа в каталоге",
        "Сколько ROOT игрок платит за ключ из общего каталога (atomic units). "
        "Per-key цена — отдельный Sprint 8.18.",
        False,
    ),
]


def upgrade() -> None:
    """Adds the 2 shop.catalog.* system_settings rows (Sprint 8.16).

    Append-only data migration (CMS-first), по образцу
    07131ffe9d13_seed_shop_fallback_system_settings: строки должны существовать
    в system_settings, чтобы shop_service читал правила из CMS. created_at /
    updated_at заполняются server defaults (CURRENT_TIMESTAMP);
    is_sensitive/status полагаются на row defaults.
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
            ) in SHOP_CATALOG_SETTINGS
        ],
    )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )