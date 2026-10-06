"""add ar_objects admin permissions

Revision ID: 15ed269093cb
Revises: f1ab8ea28db5
Create Date: 2026-10-06 13:56:06.127967

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '15ed269093cb'
down_revision: Union[str, Sequence[str], None] = 'f1ab8ea28db5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
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
                "code": "ar_objects.read",
                "title": "Просмотр AR-объектов",
                "description": (
                    "Просмотр справочника AR-объектов и их конфигурации "
                    "(тип, ассеты, сценарии, мини-игры)."
                ),
                "category": "content",
                "is_active": True,
            },
            {
                "code": "ar_objects.manage",
                "title": "Управление AR-объектами",
                "description": (
                    "Создание, изменение и публикация AR-объектов "
                    "(привязка к геозонам, ассеты, сценарии обнаружения)."
                ),
                "category": "content",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных. См. AGENTS.md и head-миграции
    (f1ab8ea28db5, 38f24f405a8b).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
