"""drop attempt_deadline_seconds from mission_runtime_policies

Revision ID: 5c85930cfb3e
Revises: a444d52459f9
Create Date: 2026-10-16 18:52:17.230038

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "5c85930cfb3e"
down_revision: Union[str, Sequence[str], None] = "a444d52459f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop attempt_deadline_seconds column.

    Dialect-aware: PostgreSQL DROP COLUMN (after dropping the dependent CHECK
    constraint); SQLite batch_alter_table rebuilds the table data-preservingly.
    """
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.drop_constraint(
            "ck_mission_runtime_policies_deadline_positive",
            "mission_runtime_policies",
            type_="check",
        )
        op.drop_column("mission_runtime_policies", "attempt_deadline_seconds")
        return

    if dialect == "sqlite":
        # SQLite cannot ALTER TABLE DROP CONSTRAINT/DROP COLUMN directly.
        # Batch mode rebuilds the table, dropping the column and its CHECK.
        with op.batch_alter_table("mission_runtime_policies") as batch_op:
            batch_op.drop_constraint(
                "ck_mission_runtime_policies_deadline_positive",
                type_="check",
            )
            batch_op.drop_column("attempt_deadline_seconds")
        return

    raise RuntimeError(
        "This migration supports only SQLite and PostgreSQL."
    )


def downgrade() -> None:
    raise NotImplementedError("Schema extension; downgrade not supported.")
