"""add mission category to missions

Revision ID: 4c8e2f6a9d3b
Revises: 2b7510f637fc
Create Date: 2026-10-10 12:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "4c8e2f6a9d3b"
down_revision: Union[str, Sequence[str], None] = "2b7510f637fc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    dialect = op.get_bind().dialect.name

    # A constant server default covers pre-existing rows immediately, so the
    # column can be added as NOT NULL in one step on both dialects. Real values
    # are backfilled right after from the legacy mission_type vocabulary.
    op.add_column(
        "missions",
        sa.Column(
            "mission_category",
            sa.String(length=32),
            nullable=False,
            server_default="solo",
        ),
    )
    op.create_index(
        "ix_missions_mission_category",
        "missions",
        ["mission_category"],
        unique=False,
    )

    op.execute(
        sa.text(
            "UPDATE missions SET mission_category = 'team' "
            "WHERE mission_type = 'team'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE missions SET mission_category = 'solo' "
            "WHERE mission_type IN ('text_answer', 'code_repair')"
        )
    )
    # Safety net: no row should be NULL, but never leave one behind.
    op.execute(
        sa.text(
            "UPDATE missions SET mission_category = 'solo' "
            "WHERE mission_category IS NULL"
        )
    )

    if dialect == "postgresql":
        op.create_check_constraint(
            "ck_missions_mission_category",
            "missions",
            "mission_category IN ('solo', 'team', 'race', 'co-op')",
        )
        return

    if dialect == "sqlite":
        # SQLite cannot ALTER TABLE ADD CONSTRAINT directly. Batch mode rebuilds
        # the table data-preservingly and installs the same CHECK as PostgreSQL.
        with op.batch_alter_table("missions") as batch_op:
            batch_op.create_check_constraint(
                "ck_missions_mission_category",
                "mission_category IN ('solo', 'team', 'race', 'co-op')",
            )
        return

    raise RuntimeError(
        "Mission category migration supports only SQLite and PostgreSQL."
    )


def downgrade() -> None:
    op.drop_index("ix_missions_mission_category", table_name="missions")
    op.drop_column("missions", "mission_category")