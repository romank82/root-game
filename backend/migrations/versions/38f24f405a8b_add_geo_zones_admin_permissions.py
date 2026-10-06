"""add geo_zones admin permissions

Revision ID: 38f24f405a8b
Revises: a1d2aafc3d3b
Create Date: 2026-10-06 09:32:55.799452

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '38f24f405a8b'
down_revision: Union[str, Sequence[str], None] = 'a1d2aafc3d3b'
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
                "code": "geo_zones.read",
                "title": "Просмотр геозон",
                "description": (
                    "Просмотр справочника геозон и их параметров "
                    "(координаты, радиус, тип)."
                ),
                "category": "geo",
                "is_active": True,
            },
            {
                "code": "geo_zones.manage",
                "title": "Управление геозонами",
                "description": (
                    "Создание, изменение и публикация геозон "
                    "(radius/polygon/poi/event)."
                ),
                "category": "geo",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных. См. AGENTS.md и head-миграции
    (a1d2aafc3d3b, a9d4e2b8c7f1, 8f098e3e0a63).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
