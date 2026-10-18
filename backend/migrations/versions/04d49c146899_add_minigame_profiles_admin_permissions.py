"""add minigame_profiles admin permissions

Revision ID: 04d49c146899
Revises: 2c14ba97fae3
Create Date: 2026-10-18 09:25:41.042393

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '04d49c146899'
down_revision: Union[str, Sequence[str], None] = '2c14ba97fae3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add minigame_profiles admin permissions (append-only).

    Sprint 8.17 шаг 3: мин. два новых кода — чтение и управление справочником
    профилей мини-игр. Append-only, идемпотентно: строка добавляется только если
    code ещё не существует (SQLite — INSERT OR IGNORE, PostgreSQL — ON CONFLICT
    (code) DO NOTHING; code — PK таблицы admin_permissions).
    """
    bind = op.get_bind()

    rows = [
        {
            "code": "minigame_profiles.read",
            "title": "Просмотр профилей мини-игр",
            "description": (
                "Просмотр справочника профилей настроек мини-игр "
                "(cipher/code_repair/text_answer)."
            ),
            "category": "minigame",
            "is_active": True,
        },
        {
            "code": "minigame_profiles.manage",
            "title": "Управление профилями мини-игр",
            "description": (
                "Создание, изменение, публикация и архивация профилей "
                "настроек мини-игр."
            ),
            "category": "minigame",
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
    проверенный backup базы данных. См. AGENTS.md и head-миграции
    (2c14ba97fae3, 38f24f405a8b, a1d2aafc3d3b).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )

