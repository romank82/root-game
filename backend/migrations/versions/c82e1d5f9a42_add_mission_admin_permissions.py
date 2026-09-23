"""add mission admin permissions

Revision ID: c82e1d5f9a42
Revises: b91a7c4d2e10
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c82e1d5f9a42"
down_revision: Union[str, Sequence[str], None] = "b91a7c4d2e10"
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
                "code": "missions.read",
                "title": "Просмотр миссий",
                "description": "Просмотр миссий и их административной конфигурации.",
                "category": "content",
                "is_active": True,
            },
            {
                "code": "missions.manage",
                "title": "Управление миссиями",
                "description": (
                    "Создание, изменение, публикация и снятие с публикации миссий."
                ),
                "category": "content",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM admin_permissions "
            "WHERE code IN ('missions.read', 'missions.manage')"
        )
    )
