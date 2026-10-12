"""add search_radius_meters to geo_zones

Revision ID: 08356e3fe9a2
Revises: 4c8e2f6a9d3b
Create Date: 2026-10-12 17:11:00.973242

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '08356e3fe9a2'
down_revision: Union[str, Sequence[str], None] = '4c8e2f6a9d3b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "geo_zones",
        sa.Column("search_radius_meters", sa.Integer(), nullable=True),
    )
    with op.batch_alter_table("geo_zones") as batch_op:
        batch_op.create_check_constraint(
            "ck_geo_zones_search_radius_positive",
            "search_radius_meters IS NULL OR search_radius_meters > 0",
        )


def downgrade() -> None:
    """Downgrade не поддерживается."""
    raise NotImplementedError(
        "Это часть шаблонной модели GeoZone; downgrade не поддерживается."
    )
