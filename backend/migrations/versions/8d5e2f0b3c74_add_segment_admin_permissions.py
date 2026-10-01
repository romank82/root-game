"""add Segment admin permissions

Revision ID: 8d5e2f0b3c74
Revises: 7c4d1e9a2b63
Create Date: 2026-09-28
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8d5e2f0b3c74"
down_revision: Union[str, Sequence[str], None] = "7c4d1e9a2b63"
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
                "code": "segments.read",
                "title": "Просмотр сегментов",
                "description": (
                    "Просмотр Segment, active-связей SegmentMission "
                    "и административной конфигурации сегментов."
                ),
                "category": "content",
                "is_active": True,
            },
            {
                "code": "segments.manage",
                "title": "Управление сегментами",
                "description": (
                    "Создание, изменение, публикация, снятие с публикации "
                    "и архивирование Segment без физического удаления."
                ),
                "category": "content",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Irreversible migration: permission catalog entries are historical "
        "administrative data and must not be physically deleted."
    )
