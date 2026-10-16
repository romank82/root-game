"""add entry_count to player_missions

Revision ID: a444d52459f9
Revises: d77ea4701199
Create Date: 2026-10-16 16:48:29.586328

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a444d52459f9'
down_revision: Union[str, Sequence[str], None] = 'd77ea4701199'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "player_missions",
        sa.Column("entry_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
