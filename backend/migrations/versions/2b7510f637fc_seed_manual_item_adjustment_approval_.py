"""seed manual item adjustment approval threshold setting

Revision ID: 2b7510f637fc
Revises: 6aff0c05e0c7
Create Date: 2026-10-10 07:34:44.466328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b7510f637fc'
down_revision: Union[str, Sequence[str], None] = '6aff0c05e0c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Seed gameplay.manual_item_adjustment_approval_threshold (7.4).

    Append-only data migration: добавляет недостающий ключ каталога
    system_settings_catalog.py в таблицу system_settings. Схема не меняется.
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
                "key": "gameplay.manual_item_adjustment_approval_threshold",
                "value_json": 5,
                "value_type": "integer",
                "category": "gameplay",
                "title": "Порог approval для ручной выдачи/отзыва предметов",
                "description": (
                    "Количество предметов, с которого ручная выдача/отзыв "
                    "ключа требует approval."
                ),
                "is_sensitive": True,
                "status": "active",
            },
        ],
    )


def downgrade() -> None:
    """Remove the seeded row (only this key; other settings untouched)."""
    op.execute(
        sa.text(
            "DELETE FROM system_settings "
            "WHERE key = 'gameplay.manual_item_adjustment_approval_threshold'"
        )
    )
