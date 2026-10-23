"""add country_source to game_players

Источник значения country (10.0.5-b): 'manual' | 'auto' | NULL.

- NULL — до фичи / неизвестно: поле country редактируемо (ручной ввод
  в анкете, админская правка).
- 'auto' — определена автоматически по фактическим координатам игрока
  (geo-intel-offline, 10.0.5): ручной ввод country в анкете блокируется
  (422); gender/age — по-прежнему редактируемы.
- 'manual' — ручная правка (анкета игрока или админская корректировка);
  при следующей миссии игрока авто-резолв перебьёт (правило «фактическая
  страна приоритет»).

Backfill НЕ делаем (нельзя отличить auto от manual по историческим
данным); старые записи остаются NULL — это ок.

Revision ID: 1dd561da2c34
Revises: 249852dee5af
Create Date: 2026-10-23 15:43:09.206208

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1dd561da2c34'
down_revision: Union[str, Sequence[str], None] = '249852dee5af'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить nullable-колонку country_source ('manual'|'auto'|NULL)."""
    op.add_column(
        "game_players",
        sa.Column("country_source", sa.String(8), nullable=True),
    )


def downgrade() -> None:
    """Откат: удалить колонку (значения не используются на текущем этапе)."""
    op.drop_column("game_players", "country_source")
