"""seed telegram.bot_username system setting

Revision ID: 2f8b4c1a6e0d
Revises: dcc8fb912a89
Create Date: 2026-11-08

Sprint 8.x-ref-link-cms: CMS-first для имени Telegram-бота.

Зачем data-seed обязателен: validate_catalog_values()
(app/system_settings_catalog.py) требует присутствия ВСЕХ ключей код-каталога
в таблице system_settings. Без строки любой PUT
/api/v1/admin/system-settings/{key} отдавал бы 422
«Отсутствует системная настройка: telegram.bot_username.» (та же природа, что
баг, исправленный в dde2038a44d9, d8b3f5c72a91 и a7e4c1d9b830).

Миграция append-only и идемпотентная: SELECT существующих ключей, затем
поштучный INSERT только отсутствующего (bulk_insert упал бы на PK при ручной
строке на dev). Метаданные (value_type/category/is_sensitive) обязаны
совпадать с код-каталогом, иначе admin_system_settings отдаёт 409
«Метаданные настройки не соответствуют утверждённому каталогу»; title и
description продублированы из каталога для читаемости админки.
Только SQLAlchemy Core (sa.table + select/insert), без диалект-специфичного
SQL — работает и на SQLite, и на PostgreSQL.
created_at/updated_at заполняются server default (func.now()), как в
dde2038a44d9 / d8b3f5c72a91 / a7e4c1d9b830.

Значение заморожено на момент миграции: telegram.bot_username=""
(пустая строка — CMS-first срабатывает только при явном заполнении через
админку; до этого shareLink собирается из env TELEGRAM_BOT_USERNAME).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2f8b4c1a6e0d'
down_revision: Union[str, Sequence[str], None] = 'dcc8fb912a89'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, value_json, value_type, category, title, description, is_sensitive)
TELEGRAM_SETTINGS = [
    (
        "telegram.bot_username",
        "",
        "string",
        "telegram",
        "Имя Telegram-бота (username)",
        (
            "Username бота без @ (например, HimeraProtocolBot). "
            "Используется для сборки реферальной ссылки. "
            "Пустое значение — fallback на env TELEGRAM_BOT_USERNAME."
        ),
        False,
    ),
]


def upgrade() -> None:
    """Идемпотентно добавить telegram.bot_username (append-only).

    SELECT существующих ключей, затем INSERT только отсутствующих.
    status='active' — иначе admin_system_settings не даст менять настройку
    (409 «Можно изменять только active системную настройку»).
    """
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

    existing_keys = set(
        bind.execute(sa.select(settings_table.c.key)).scalars().all()
    )

    for (
        key,
        value,
        value_type,
        category,
        title,
        description,
        sensitive,
    ) in TELEGRAM_SETTINGS:
        if key in existing_keys:
            continue
        bind.execute(
            settings_table.insert().values(
                key=key,
                value_json=value,
                value_type=value_type,
                category=category,
                title=title,
                description=description,
                is_sensitive=sensitive,
                status="active",
            )
        )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )
