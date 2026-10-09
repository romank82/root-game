"""add team admin permissions

Revision ID: 6aff0c05e0c7
Revises: 5608ca00598a
Create Date: 2026-10-08 19:20:00.000000

Через копию ред.: добавляет в реестр admin_permissions права teams.read и
teams.manage (шаг 6.7.a). По умолчанию execution_mode — 'direct' (гранты
настраиваются супер-админом через admin UI/API).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6aff0c05e0c7"
down_revision: Union[str, Sequence[str], None] = "5608ca00598a"
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
                "code": "teams.read",
                "title": "Просмотр команд",
                "description": (
                    "Просмотр команд, их состава, истории, приглашений "
                    "и заявок на вступление."
                ),
                "category": "teams",
                "is_active": True,
            },
            {
                "code": "teams.manage",
                "title": "Управление командами (модерация)",
                "description": (
                    "Принудительное расформирование команды (force-disband) "
                    "и исключение игрока (force-kick). Может требовать "
                    "одобрения супер-админа (execution_mode)."
                ),
                "category": "teams",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Удаляет только два добавленных кода teams.*.

    Безопасно: гранты на них ссылаются через FK ondelete=RESTRICT, поэтому
    при существующих AdminUserPermission удаление не пройдёт (защита, а не
    потеря данных). Полный откат — только через проверенный backup.
    """
    op.execute(
        sa.text("DELETE FROM admin_permissions WHERE code IN ('teams.read', 'teams.manage')")
    )