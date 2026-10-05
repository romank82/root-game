"""add reward_pool admin permissions

Revision ID: a9d4e2b8c7f1
Revises: 8f098e3e0a63
Create Date: 2026-10-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9d4e2b8c7f1"
down_revision: Union[str, Sequence[str], None] = "8f098e3e0a63"
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
                "code": "reward_pools.read",
                "title": "Просмотр пулов наград",
                "description": (
                    "Просмотр пулов случайных наград и их конфигурации "
                    "(награды и веса)."
                ),
                "category": "economy",
                "is_active": True,
            },
            {
                "code": "reward_pools.manage",
                "title": "Управление пулами наград",
                "description": (
                    "Создание и изменение пулов случайных наград: строки "
                    "наград, веса, статус draft/published."
                ),
                "category": "economy",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Откат прав reward_pools требует проверенного backup базы данных.
    См. AGENTS.md и head-миграции (8f098e3e0a63, 481081d0694d).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )