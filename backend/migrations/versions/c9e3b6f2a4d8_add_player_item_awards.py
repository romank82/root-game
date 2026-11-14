"""add player item awards (idempotent item grants)

B2: item-награды не имели ledger-защиты (в отличие от ROOT), поэтому два
параллельных submit могли дважды увеличить PlayerItem.quantity. Новая
append-only таблица фиксирует каждую выдачу строки награды за прогон;
уникальный ключ (player_id, mission_id, reward_id, reference_id) —
DB-level барьер идемпотентности.

Revision ID: c9e3b6f2a4d8
Revises: c8d2a5e1f3b7
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e3b6f2a4d8"
down_revision: Union[str, Sequence[str], None] = "c8d2a5e1f3b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать immutable-таблицу player_item_awards."""
    op.create_table(
        "player_item_awards",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("reward_id", sa.String(length=64), nullable=False),
        sa.Column("item_id", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity > 0",
            name="ck_player_item_awards_quantity_positive",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["item_id"],
            ["items.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id",
            "mission_id",
            "reward_id",
            "reference_id",
            name="uq_player_item_awards_grant",
        ),
    )
    op.create_index(
        op.f("ix_player_item_awards_player_id"),
        "player_item_awards",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_player_item_awards_mission_id"),
        "player_item_awards",
        ["mission_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_player_item_awards_item_id"),
        "player_item_awards",
        ["item_id"],
        unique=False,
    )
    op.create_index(
        "ix_player_item_awards_player_mission_item",
        "player_item_awards",
        ["player_id", "mission_id", "item_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade не поддерживается (immutable-миграция)."""
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )