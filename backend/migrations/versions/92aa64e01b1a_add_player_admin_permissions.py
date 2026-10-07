"""add player admin permissions

Revision ID: 92aa64e01b1a
Revises: 32958b0d96cd
Create Date: 2026-10-07 11:41:50.886362

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '92aa64e01b1a'
down_revision: Union[str, Sequence[str], None] = '32958b0d96cd'
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
                "code": "players.read",
                "title": "Просмотр игроков",
                "description": "Просмотр карточки игрока и списка игроков.",
                "category": "players",
                "is_active": True,
            },
            {
                "code": "players.manage",
                "title": "Ручные операции с игроками",
                "description": (
                    "Ручное начисление/списание ROOT, выдача/отзыв ключей, "
                    "отмена/завершение миссий."
                ),
                "category": "players",
                "is_active": True,
            },
            {
                "code": "players.restrict",
                "title": "Ограничения игроков",
                "description": (
                    "Создание и снятие ограничений игрока (chat/transfer/team/"
                    "mission/payment/withdrawal_restricted, suspended)."
                ),
                "category": "players",
                "is_active": True,
            },
            {
                "code": "players.block",
                "title": "Блокировка игроков",
                "description": (
                    "Полная блокировка доступа игрока (restriction_type=blocked) "
                    "и её снятие."
                ),
                "category": "players",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Откат прав players требует проверенного backup базы данных.
    См. AGENTS.md и head-миграцию (32958b0d96cd).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
