"""seed referral system settings

Revision ID: a7e4c1d9b830
Revises: c3d9a71f4b62
Create Date: 2026-11-06

Sprint Referral R-2: CMS-ключи реферальной программы.

Зачем data-seed обязателен: validate_catalog_values()
(app/system_settings_catalog.py) требует присутствия ВСЕХ ключей код-каталога
в таблице system_settings. Без строк любой PUT
/api/v1/admin/system-settings/{key} отдавал бы 422
«Отсутствует системная настройка: referral.enabled.» (та же природа, что баг,
исправленный в dde2038a44d9 и d8b3f5c72a91).

Миграция append-only и идемпотентная: SELECT существующих ключей, затем
поштучный INSERT только отсутствующих (bulk_insert упал бы на PK при ручной
строке на dev). Метаданные (value_type/category/is_sensitive) обязаны
совпадать с код-каталогом, иначе admin_system_settings отдаёт 409
«Метаданные настройки не соответствуют утверждённому каталогу»; title и
description продублированы из каталога для читаемости админки.
Только SQLAlchemy Core (sa.table + select/insert), без диалект-специфичного
SQL — работает и на SQLite, и на PostgreSQL.
created_at/updated_at заполняются server default (func.now()), как в
dde2038a44d9 / d8b3f5c72a91.

Значения заморожены на момент миграции: referral.enabled=False (фича
выключена до осознанного включения через CMS), referral.reward_root=25.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7e4c1d9b830'
down_revision: Union[str, Sequence[str], None] = 'c3d9a71f4b62'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, value_json, value_type, category, title, description, is_sensitive)
REFERRAL_SETTINGS = [
    (
        "referral.enabled",
        False,
        "boolean",
        "referral",
        "Реферальная программа вкл/выкл",
        (
            "Если true — пригласивший получает ROOT, когда приглашённый "
            "достигает порога переводов."
        ),
        False,
    ),
    (
        "referral.reward_root",
        25,
        "integer",
        "referral",
        "Вознаграждение за приглашение (ROOT)",
        (
            "Сколько ROOT получает пригласивший, когда приглашённый "
            "достигает порога переводов."
        ),
        True,
    ),
]


def upgrade() -> None:
    """Идемпотентно добавить referral.* (append-only).

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
    ) in REFERRAL_SETTINGS:
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
