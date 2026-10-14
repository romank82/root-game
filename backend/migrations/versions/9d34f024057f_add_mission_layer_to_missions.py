"""add mission_layer to missions

Revision ID: 9d34f024057f
Revises: 30116c3d9ae6
Create Date: 2026-10-14 11:03:40.569549

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9d34f024057f'
down_revision: Union[str, Sequence[str], None] = '30116c3d9ae6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "missions",
        sa.Column(
            "mission_layer",
            sa.String(length=32),
            nullable=False,
            server_default="solo",
        ),
    )
    with op.batch_alter_table("missions") as batch_op:
        batch_op.create_check_constraint(
            "ck_missions_mission_layer",
            "mission_layer IN ('story', 'team', 'solo')",
        )
    op.create_index(
        "ix_missions_mission_layer", "missions", ["mission_layer"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
