"""add seasons admin permissions

Revision ID: 26f3a9c1d5e7
Revises: 0924efcc86a9
Create Date: 2026-10-21

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26f3a9c1d5e7'
down_revision: Union[str, Sequence[str], None] = '0924efcc86a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade: добавить seasons.read / seasons.manage в каталог прав (append-only).

    Sprint 8.21 (Season CRUD): два новых кода — чтение и управление сезонами.
    Append-only, идемпотентно: строка добавляется только если code ещё не
    существует (SQLite — INSERT OR IGNORE, PostgreSQL — ON CONFLICT (code)
    DO NOTHING; code — PK таблицы admin_permissions).
    """
    bind = op.get_bind()

    rows = [
        {
            "code": "seasons.read",
            "title": "Просмотр сезонов",
            "description": (
                "Просмотр Season (список, детали) во вкладке «Сезоны» "
                "админ-панели."
            ),
            "category": "content",
            "is_active": True,
        },
        {
            "code": "seasons.manage",
            "title": "Управление сезонами",
            "description": (
                "Создание, изменение, публикация и архивация Season "
                "без физического удаления."
            ),
            "category": "content",
            "is_active": True,
        },
    ]

    if bind.dialect.name == "sqlite":
        statement = sa.text(
            "INSERT OR IGNORE INTO admin_permissions (code, title, description, "
            "category, is_active) VALUES (:code, :title, :description, :category, "
            ":is_active)"
        )
    else:  # postgresql и прочие серверные СУБД
        statement = sa.text(
            "INSERT INTO admin_permissions (code, title, description, category, "
            "is_active) VALUES (:code, :title, :description, :category, :is_active) "
            "ON CONFLICT (code) DO NOTHING"
        )

    for row in rows:
        bind.execute(statement, row)


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных. См. AGENTS.md и head-миграцию
    04d49c146899 (аналогичный seed-стиль).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )