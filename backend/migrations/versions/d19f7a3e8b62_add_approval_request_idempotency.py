"""enforce approval request idempotency per requester

Revision ID: d19f7a3e8b62
Revises: c82e1d5f9a42
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op


revision: str = "d19f7a3e8b62"
down_revision: Union[str, Sequence[str], None] = "c82e1d5f9a42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT_NAME = "uq_admin_approval_requests_requester_request_id"


def upgrade() -> None:
    # SQLite cannot ALTER TABLE ADD CONSTRAINT directly. batch mode performs
    # copy-and-move there and remains valid for PostgreSQL.
    with op.batch_alter_table("admin_approval_requests") as batch_op:
        batch_op.create_unique_constraint(
            CONSTRAINT_NAME,
            ["requested_by_admin_id", "request_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("admin_approval_requests") as batch_op:
        batch_op.drop_constraint(CONSTRAINT_NAME, type_="unique")
