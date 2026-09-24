"""complete approval execution state machine

Revision ID: f7b2c9d4e613
Revises: e3a6f4b9c281
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7b2c9d4e613"
down_revision: Union[str, Sequence[str], None] = "e3a6f4b9c281"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("admin_approval_requests") as batch_op:
        batch_op.add_column(
            sa.Column(
                "cancelled_by_admin_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "cancelled_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "cancellation_reason",
                sa.Text(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "executed_by_admin_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_admin_approval_requests_cancelled_by_admin_id",
            "admin_users",
            ["cancelled_by_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_admin_approval_requests_executed_by_admin_id",
            "admin_users",
            ["executed_by_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_admin_approval_requests_cancelled_by_admin_id",
            ["cancelled_by_admin_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_admin_approval_requests_executed_by_admin_id",
            ["executed_by_admin_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("admin_approval_requests") as batch_op:
        batch_op.drop_index("ix_admin_approval_requests_executed_by_admin_id")
        batch_op.drop_index("ix_admin_approval_requests_cancelled_by_admin_id")
        batch_op.drop_constraint(
            "fk_admin_approval_requests_executed_by_admin_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_admin_approval_requests_cancelled_by_admin_id",
            type_="foreignkey",
        )
        batch_op.drop_column("executed_by_admin_id")
        batch_op.drop_column("cancellation_reason")
        batch_op.drop_column("cancelled_at")
        batch_op.drop_column("cancelled_by_admin_id")
