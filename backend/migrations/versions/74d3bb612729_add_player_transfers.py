"""add player_transfers

Перевод ROOT между игроками (10.1+). Фундамент переводов (без Stars — позже).

Одна запись = один перевод. Логики перевода в этой миграции нет — только
таблица. Идемпотентность — (from_player_id, reference_id) (клиентский
request_id): уникальность в рамках отправителя, разные игроки с одинаковым
request_id не конфликтуют.

- status: 'completed' | 'rejected' (CheckConstraint ck_player_transfers_status).
- amount: целое, строго > 0 (CheckConstraint ck_player_transfers_amount_positive).
- ondelete RESTRICT у обоих FK на game_players.id: финансовая история не
  должна пропадать при удалении игрока.
- created_at/updated_at — server_default=now() (как TimestampMixin в моделях).

Revision ID: 74d3bb612729
Revises: 1dd561da2c34
Create Date: 2026-10-23 18:28:39.152493

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74d3bb612729'
down_revision: Union[str, Sequence[str], None] = '1dd561da2c34'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицу player_transfers (10.1+)."""
    op.create_table(
        "player_transfers",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("from_player_id", sa.String(length=64), nullable=False),
        sa.Column("to_player_id", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reference_id", sa.String(length=64), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["from_player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
            name="fk_player_transfers_from_player",
        ),
        sa.ForeignKeyConstraint(
            ["to_player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
            name="fk_player_transfers_to_player",
        ),
        sa.UniqueConstraint(
            "from_player_id",
            "reference_id",
            name="uq_player_transfers_from_reference",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_player_transfers_amount_positive",
        ),
        sa.CheckConstraint(
            "status IN ('completed','rejected')",
            name="ck_player_transfers_status",
        ),
    )
    op.create_index(
        "ix_player_transfers_from_player_id",
        "player_transfers",
        ["from_player_id"],
    )
    op.create_index(
        "ix_player_transfers_to_player_id",
        "player_transfers",
        ["to_player_id"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
