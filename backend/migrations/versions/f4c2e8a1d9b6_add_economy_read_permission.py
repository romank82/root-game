"""add economy.read permission

Revision ID: f4c2e8a1d9b6
Revises: 90de6dad12b
Create Date: 2026-10-22

Сид economy.read (Этап 9.1). Append-only.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f4c2e8a1d9b6"
down_revision: Union[str, Sequence[str], None] = "90de6dad12b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    permission_table = sa.table(
        "admin_permissions",
        sa.column("code", sa.String()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("category", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "code": "economy.read",
                "title": "Просмотр экономики (сверка баланса)",
                "description": (
                    "Просмотр экономики: сверка балансов кошельков "
                    "с ledger-проводками (Этап 9.1, часть 1)."
                ),
                "category": "economy",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Откат прав economy.read требует проверенного backup базы данных.
    См. AGENTS.md.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )