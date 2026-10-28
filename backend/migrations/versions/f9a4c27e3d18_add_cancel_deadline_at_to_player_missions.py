"""add cancel_deadline_at to player_missions

Revision ID: f9a4c27e3d18
Revises: df5a8375c95e
Create Date: 2026-10-28 15:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f9a4c27e3d18'
down_revision: Union[str, Sequence[str], None] = 'df5a8375c95e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "player_missions",
        sa.Column(
            "cancel_deadline_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    """Downgrade schema.

    Dialect-aware: PostgreSQL поддерживает DROP COLUMN через ALTER;
    SQLite — через batch_alter_table (пересоздание таблицы).
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_column("player_missions", "cancel_deadline_at")
    else:
        with op.batch_alter_table("player_missions") as batch_op:
            batch_op.drop_column("cancel_deadline_at")
