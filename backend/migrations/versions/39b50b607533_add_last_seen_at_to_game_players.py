"""add last_seen_at to game_players

13.7-b: «последний визит» игрока (онлайн/офлайн). Обновляется в
get_current_player_id (main.py) при каждом запросе игрока.

- last_seen_at: DateTime(timezone=True), nullable=True (игроки до фичи
  остаются NULL — backfill не делаем), index=True (для сортировки и
  фильтров «онлайн»).
- Throttle НЕ делаем (пока): обновление на каждый запрос. Если станет
  медленно — throttle отдельным шагом.

Revision ID: 39b50b607533
Revises: 274519482c7d
Create Date: 2026-10-24 09:47:03.151782

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '39b50b607533'
down_revision: Union[str, Sequence[str], None] = '274519482c7d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить nullable-колонку last_seen_at (13.7-b) + индекс."""
    op.add_column(
        "game_players",
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_game_players_last_seen_at",
        "game_players",
        ["last_seen_at"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
