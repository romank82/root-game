"""seed shop fallback price setting

Revision ID: 1c439c558aa7
Revises: 07131ffe9d13
Create Date: 2026-10-07 09:53:08.856919

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1c439c558aa7'
down_revision: Union[str, Sequence[str], None] = '07131ffe9d13'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed shop.fallback.default_price_root (шаг 4.4).

    Append-only data migration: добавляет 5-й ключ shop.fallback.* рядом
    с четырьмя из 07131ffe9d13. Схема не меняется.
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
                "key": "shop.fallback.default_price_root",
                "value_json": 100,
                "value_type": "integer",
                "category": "shop",
                "title": "Цена fallback-ключа в ROOT",
                "description": "Сколько ROOT игрок платит за покупку ключа из fallback-предложения (atomic units).",
                "is_sensitive": False,
                "status": "active",
            },
        ],
    )


def downgrade() -> None:
    """Immutable policy: data-миграции не откатываются."""
    raise NotImplementedError("Append-only data migration; downgrade is not supported.")
