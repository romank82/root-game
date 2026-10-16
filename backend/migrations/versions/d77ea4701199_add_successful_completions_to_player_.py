"""add successful_completions to player_missions

Revision ID: d77ea4701199
Revises: 922c9bace039
Create Date: 2026-10-16 10:31:44.417040

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd77ea4701199'
down_revision: Union[str, Sequence[str], None] = '922c9bace039'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "player_missions",
        sa.Column(
            "successful_completions",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
