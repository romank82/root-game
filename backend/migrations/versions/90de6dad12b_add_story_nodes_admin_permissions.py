"""add story_nodes admin permissions

Revision ID: 90de6dad12b
Revises: a3f9c18e42b7
Create Date: 2026-10-21

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '90de6dad12b'
down_revision: Union[str, Sequence[str], None] = 'a3f9c18e42b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade: добавить story_nodes.read / story_nodes.manage в каталог прав (append-only).

    Sprint 8.26 (StoryNode CRUD): два новых кода — чтение и управление
    сюжетными узлами. Схема таблицы story_nodes уже существует (модель
    StoryNode, models.py:89) — миграция схемы не требуется, только сид прав.

    Append-only, идемпотентно: строка добавляется только если code ещё не
    существует (SQLite — INSERT OR IGNORE, PostgreSQL — ON CONFLICT (code)
    DO NOTHING; code — PK таблицы admin_permissions).
    """
    bind = op.get_bind()

    rows = [
        {
            "code": "story_nodes.read",
            "title": "Просмотр сюжетных узлов",
            "description": (
                "Просмотр StoryNode (список, детали) во вкладке "
                "«Story Nodes» админ-панели."
            ),
            "category": "content",
            "is_active": True,
        },
        {
            "code": "story_nodes.manage",
            "title": "Управление сюжетными узлами",
            "description": (
                "Создание, изменение, публикация и архивация StoryNode "
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
    проверенный backup базы данных. См. AGENTS.md и миграции
    a3f9c18e42b7 / 04d49c146899 (аналогичный seed-стиль).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )