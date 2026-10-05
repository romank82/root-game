"""add key_rules admin permissions

Revision ID: 481081d0694d
Revises: 357b704e50ff
Create Date: 2026-10-05 14:20:29.318466
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "481081d0694d"
down_revision: Union[str, Sequence[str], None] = "357b704e50ff"
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
                "code": "key_rules.read",
                "title": "Просмотр правил ключей",
                "description": (
                    "Просмотр правил ключей доступа и их игровой конфигурации."
                ),
                "category": "economy",
                "is_active": True,
            },
            {
                "code": "key_rules.manage",
                "title": "Управление правилами ключей",
                "description": (
                    "Создание, изменение и публикация правил ключей доступа "
                    "(расход, размер стопки, запрет передачи/продажи/обмена)."
                ),
                "category": "economy",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных. См. AGENTS.md и head-миграции
    (357b704e50ff, 3a9e1c7d5f24).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
