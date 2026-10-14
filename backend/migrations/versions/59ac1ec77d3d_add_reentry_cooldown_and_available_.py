"""add reentry cooldown and available_again_at

Revision ID: 59ac1ec77d3d
Revises: 2b240af22580
Create Date: 2026-10-14 15:01:40.033419

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '59ac1ec77d3d'
down_revision: Union[str, Sequence[str], None] = '2b240af22580'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "missions",
        sa.Column(
            "reentry_cooldown_seconds",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    with op.batch_alter_table("missions") as batch_op:
        batch_op.create_check_constraint(
            "ck_missions_reentry_cooldown_nonnegative",
            "reentry_cooldown_seconds >= 0",
        )

    op.add_column(
        "player_missions",
        sa.Column("available_again_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
