"""add ar_object scale/orientation and geozone location_constraints

Revision ID: 37580bed3ce0
Revises: 08356e3fe9a2
Create Date: 2026-10-12 18:25:50.705054

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '37580bed3ce0'
down_revision: Union[str, Sequence[str], None] = '08356e3fe9a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "ar_objects",
        sa.Column("scale_meters", sa.Float(), nullable=False, server_default="1.0"),
    )
    op.add_column(
        "ar_objects",
        sa.Column("orientation", sa.String(length=32), nullable=False, server_default="free"),
    )
    with op.batch_alter_table("ar_objects") as batch_op:
        batch_op.create_check_constraint(
            "ck_ar_objects_scale_range",
            "scale_meters > 0 AND scale_meters <= 10",
        )
        batch_op.create_check_constraint(
            "ck_ar_objects_orientation",
            "orientation IN ('free', 'upright', 'flat')",
        )

    op.add_column(
        "geo_zones",
        sa.Column("location_constraints", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
