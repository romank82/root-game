"""seed monitoring global threshold

Sprint M-5: системная настройка monitoring.global_threshold — минимальное
число ошибок в группе (COUNT(*)), начиная с которого группа помечается
isGlobal в /admin/monitoring/error-groups.

Идемпотентная append-only data-миграция (по образцу dde2038a44d9): вставляем
строку только если ключа ещё нет в system_settings (bulk_insert упал бы на
PK при ручных строках на dev). Только SQLAlchemy Core (sa.table +
select/insert), без диалект-специфичного SQL — работает и на SQLite, и на PG.
created_at/updated_at заполняются server default (func.now()).

ВАЖНО: строка обязана совпадать с код-каталогом (system_settings_catalog.py)
по value_type/category/is_sensitive — иначе admin_system_settings отдаёт 409.
Также validate_catalog_values() требует присутствия ВСЕХ ключей каталога,
поэтому эта миграция обязана идти в паре с добавлением ключа в каталог.

Revision ID: a7c9e1f3b5d2
Revises: f3a5b7c9d2e4
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c9e1f3b5d2'
down_revision: Union[str, Sequence[str], None] = 'f3a5b7c9d2e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


THRESHOLD_KEY = "monitoring.global_threshold"


def upgrade() -> None:
    """Идемпотентно добавить monitoring.global_threshold = 100 (append-only)."""
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
            settings_table.c.key == THRESHOLD_KEY
        )
    ).first()
    if existing is not None:
        return

    bind.execute(
        settings_table.insert().values(
            key=THRESHOLD_KEY,
            value_json=100,
            value_type="integer",
            category="monitoring",
            title="Глобальный порог ошибок группы",
            description=(
                "Минимальное число ошибок в группе (COUNT(*)), начиная с "
                "которого группа помечается isGlobal в "
                "/admin/monitoring/error-groups."
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
