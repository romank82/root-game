"""add segments_missions association table

Revision ID: 6a1b2c_add_segments_missions
Revises: 5ce90f22ef13
Create Date: 2026-09-28 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6a1b2c_add_segments_missions"
down_revision = "5ce90f22ef13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "segments_missions",
        sa.Column("segment_id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("segment_id", "mission_id"),
    )
    op.create_index(
        "ix_segments_missions_segment_id",
        "segments_missions",
        ["segment_id"],
        unique=False,
    )
    op.create_index(
        "ix_segments_missions_mission_id",
        "segments_missions",
        ["mission_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_segments_missions_mission_id",
        table_name="segments_missions",
    )
    op.drop_index(
        "ix_segments_missions_segment_id",
        table_name="segments_missions",
    )
    op.drop_table("segments_missions")
