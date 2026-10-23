"""add profile fields to game_players

Поля профиля игрока (10.0.2): country (ISO-2), gender (enum), age.
Nullable: существующие игроки без профиля; заполняются через PATCH (34-C).

- country — ISO-3166 alpha-2 (RU, US, DE): короткий нормализованный код,
  равенство в фильтрах (не ILIKE по свободному тексту).
- gender — male / female / other / unspecified.
- age — целое, 0..120.

Валидация значений (gender — enum, age — диапазон) — на бэке, в PATCH
(34-C), не в модели/миграции.

Revision ID: 249852dee5af
Revises: 884a02f1a72d
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "249852dee5af"
down_revision: Union[str, Sequence[str], None] = "884a02f1a72d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить три nullable-колонки профиля игрока."""
    op.add_column(
        "game_players",
        sa.Column("country", sa.String(2), nullable=True),
    )
    op.add_column(
        "game_players",
        sa.Column("gender", sa.String(16), nullable=True),
    )
    op.add_column(
        "game_players",
        sa.Column("age", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Откат: удалить колонки профиля (пустые на текущем этапе — не disruptive)."""
    op.drop_column("game_players", "age")
    op.drop_column("game_players", "gender")
    op.drop_column("game_players", "country")
