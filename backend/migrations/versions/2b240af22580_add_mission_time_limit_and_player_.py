"""add mission time limit and player deadline

Revision ID: 2b240af22580
Revises: 9d34f024057f
Create Date: 2026-10-14 14:02:21.793728

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2b240af22580'
down_revision: Union[str, Sequence[str], None] = '9d34f024057f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "missions",
        sa.Column("execution_time_limit_seconds", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("missions") as batch_op:
        batch_op.create_check_constraint(
            "ck_missions_execution_time_limit_positive",
            "execution_time_limit_seconds IS NULL OR execution_time_limit_seconds > 0",
        )

    op.add_column(
        "player_missions",
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
