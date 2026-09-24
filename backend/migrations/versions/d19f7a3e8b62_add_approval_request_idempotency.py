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


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_admin_approval_requests_requester_request_id",
        "admin_approval_requests",
        ["requested_by_admin_id", "request_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_admin_approval_requests_requester_request_id",
        "admin_approval_requests",
        type_="unique",
    )
