"""add awarded_snapshot to team_session_members

Sprint 8.x-4-final-status-1: per-player awarded snapshot.

Append-only: снапшот наград игрока за командную сессию (dict из
_award_mission_rewards: root/items/storyNodeIds), пишется в
_submit_wave_answer в той же транзакции, что и награды. Поле nullable без
server_default — старые строки получают None («наград нет / не записано»).

Revision ID: d4f0a1b2c3e7
Revises: c8a4e2b6f9d3
Create Date: 2026-10-29 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4f0a1b2c3e7'
down_revision: Union[str, Sequence[str], None] = 'c8a4e2b6f9d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить awarded_snapshot (JSON, nullable) в team_session_members.

    Dialect-aware: PostgreSQL — plain ALTER ADD COLUMN; SQLite — batch
    (пересоздание таблицы с копированием данных, как в c8a4e2b6f9d3).
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.add_column(
            "team_session_members",
            sa.Column("awarded_snapshot", sa.JSON(), nullable=True),
        )
    else:
        with op.batch_alter_table("team_session_members") as batch_op:
            batch_op.add_column(
                sa.Column("awarded_snapshot", sa.JSON(), nullable=True)
            )


def downgrade() -> None:
    """Откатить: удалить awarded_snapshot (append-only, данные не восстанавливаются)."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_column("team_session_members", "awarded_snapshot")
    else:
        with op.batch_alter_table("team_session_members") as batch_op:
            batch_op.drop_column("awarded_snapshot")