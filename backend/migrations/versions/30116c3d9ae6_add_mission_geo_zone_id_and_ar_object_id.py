"""add mission geo_zone_id and ar_object_id

Revision ID: 30116c3d9ae6
Revises: 37580bed3ce0
Create Date: 2026-10-12 21:08:08.983748

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '30116c3d9ae6'
down_revision: Union[str, Sequence[str], None] = '37580bed3ce0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("missions") as batch_op:
        batch_op.add_column(sa.Column("geo_zone_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("ar_object_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_missions_geo_zone_id", "geo_zones", ["geo_zone_id"], ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_missions_ar_object_id", "ar_objects", ["ar_object_id"], ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_missions_geo_zone_id", ["geo_zone_id"])
        batch_op.create_index("ix_missions_ar_object_id", ["ar_object_id"])


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
