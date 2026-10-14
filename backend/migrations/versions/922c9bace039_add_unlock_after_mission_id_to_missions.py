"""add unlock_after_mission_id to missions

Revision ID: 922c9bace039
Revises: 59ac1ec77d3d
Create Date: 2026-10-14 16:46:34.396694

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '922c9bace039'
down_revision: Union[str, Sequence[str], None] = '59ac1ec77d3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "missions",
        sa.Column("unlock_after_mission_id", sa.String(length=64), nullable=True),
    )
    with op.batch_alter_table("missions") as batch_op:
        batch_op.create_foreign_key(
            "fk_missions_unlock_after_mission_id",
            "missions",
            ["unlock_after_mission_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_missions_unlock_after_mission_id",
            ["unlock_after_mission_id"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
