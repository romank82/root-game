"""seed content supported languages setting

Revision ID: d8b3f5c72a91
Revises: c5d8e2f14a7b
Create Date: 2026-11-04

Sprint Trans-2b-1: CMS-настройка content.supported_languages — источник истины
для ручного перевода контента (миссии, сезоны, главы, сегменты, story_nodes).
Новый язык добавляется в CMS, без деплоя и без миграции.

Зачем data-seed обязателен: validate_catalog_values() (app/system_settings_catalog.py)
требует присутствия ВСЕХ ключей код-каталога в таблице system_settings. Без строки
любой PUT /api/v1/admin/system-settings/{key} отдавал бы 422
«Отсутствует системная настройка: content.supported_languages.» (той же природы,
что баг, исправленный в dde2038a44d9).

Миграция append-only и идемпотентная: SELECT существующего ключа, затем INSERT
только если строки нет (bulk_insert упал бы на PK при ручной строке на dev).
Метаданные (value_type/category/is_sensitive) обязаны совпадать с код-каталогом,
иначе admin_system_settings отдаёт 409 «Метаданные настройки не соответствуют
утверждённому каталогу». Только SQLAlchemy Core (sa.table + select/insert), без
диалект-специфичного SQL — работает и на SQLite, и на PostgreSQL.
created_at/updated_at заполняются server default (func.now()).
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d8b3f5c72a91"
down_revision: Union[str, Sequence[str], None] = "c5d8e2f14a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SUPPORTED_LANGUAGES_KEY = "content.supported_languages"
DEFAULT_SUPPORTED_LANGUAGES = ["ru", "en", "zh"]


def upgrade() -> None:
    """Идемпотентно добавить content.supported_languages (append-only)."""
    bind = op.get_bind()

    settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.String()),
        sa.column("value_json", sa.JSON()),
        sa.column("value_type", sa.String()),
        sa.column("category", sa.String()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("is_sensitive", sa.Boolean()),
        sa.column("status", sa.String()),
    )

    existing = bind.execute(
        sa.select(settings_table.c.key).where(
            settings_table.c.key == SUPPORTED_LANGUAGES_KEY
        )
    ).first()
    if existing is not None:
        return

    bind.execute(
        settings_table.insert().values(
            key=SUPPORTED_LANGUAGES_KEY,
            value_json=DEFAULT_SUPPORTED_LANGUAGES,
            value_type="json",
            category="content",
            title="Поддерживаемые языки контента",
            description=(
                "Языки, на которые переводится контент (миссии, сезоны и т.д.). "
                "Новый язык добавляется здесь — система подхватит его автоматически."
            ),
            is_sensitive=False,
            status="active",
        )
    )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )
