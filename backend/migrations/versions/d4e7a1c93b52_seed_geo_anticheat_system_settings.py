"""seed geo.anticheat_* system settings

Sprint 8.9.e-1: CMS-ключи античита solo location-proof — строки обязаны
существовать в system_settings, иначе:
* GET /api/v1/admin/system-settings/{key} -> 404 (ключ не виден в админке:
  list_system_settings отдаёт только строки из БД);
* PUT -> 422 «Отсутствует системная настройка: <key>.» — validate_catalog_values
  требует присутствия ВСЕХ ключей каталога (system_settings_catalog.py).

Ключи (значения = текущие константы geo_anticheat, поведение не меняется):
* geo.anticheat_mode = "flag"  (off|flag|enforce)
* geo.anticheat_max_speed_kmh = 120
* geo.anticheat_min_elapsed_seconds = 5
* geo.anticheat_accuracy_min_meters = 3

Идемпотентная append-only data-миграция (по образцу b8f2c4d6e9a1): каждая
строка вставляется только если ключа ещё нет в system_settings (bulk_insert
упал бы на PK при ручных строках на dev). Только SQLAlchemy Core (sa.table +
select/insert), без диалект-специфичного SQL — работает и на SQLite, и на
PostgreSQL. created_at/updated_at заполняются server default (func.now()).

ВАЖНО: строки обязаны совпадать с код-каталогом (system_settings_catalog.py)
по value_type/category/is_sensitive — иначе admin_system_settings отдаёт 409.
Каталог дополняется отдельным шагом (8.9.e-2): порядок применения миграции и
каталога не важен (миграция только добавляет строки), но оба шага должны
попасть в один релиз. downgrade запрещён (append-only), откат невозможен.

Revision ID: d4e7a1c93b52
Revises: b8f2c4d6e9a1
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4e7a1c93b52"
down_revision: Union[str, Sequence[str], None] = "b8f2c4d6e9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, value_json, value_type, title, description).
# Для всех строк: category="geo", is_sensitive=False, status="active".
GEO_ANTICHEAT_SETTINGS = (
    (
        "geo.anticheat_mode",
        "flag",
        "string",
        "Режим античита",
        "Sprint 8.9: античит solo location-proof (off|flag|enforce).",
    ),
    (
        "geo.anticheat_max_speed_kmh",
        120,
        "integer",
        "Порог скорости античита (км/ч)",
        "Скорость spawn->proof выше порога даёт velocity-сигнал.",
    ),
    (
        "geo.anticheat_min_elapsed_seconds",
        5,
        "integer",
        "Минимальный интервал античита (с)",
        "Меньший интервал spawn->proof не проверяется на velocity.",
    ),
    (
        "geo.anticheat_accuracy_min_meters",
        3,
        "integer",
        "Порог «идеальной» accuracy (м)",
        "Accuracy не выше порога считается подозрительно идеальной.",
    ),
)


def upgrade() -> None:
    """Идемпотентно добавить 4 ключа geo.anticheat_* (append-only)."""
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

    for key, value, value_type, title, description in GEO_ANTICHEAT_SETTINGS:
        existing = bind.execute(
            sa.select(settings_table.c.key).where(
                settings_table.c.key == key
            )
        ).first()
        if existing is not None:
            continue

        bind.execute(
            settings_table.insert().values(
                key=key,
                value_json=value,
                value_type=value_type,
                category="geo",
                title=title,
                description=description,
                is_sensitive=False,
                status="active",
            )
        )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )
