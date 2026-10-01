"""reconcile model index metadata

Revision ID: 1a6d4c8e2b75
Revises: 0b9e7c6d5a41
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "1a6d4c8e2b75"
down_revision: Union[str, Sequence[str], None] = "0b9e7c6d5a41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The model has declared this index since AdminUser gained
    # created_by_admin_id; the original migration created the FK but omitted it.
    op.create_index(
        "ix_admin_users_created_by_admin_id",
        "admin_users",
        ["created_by_admin_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_users_created_by_admin_id",
        table_name="admin_users",
    )
