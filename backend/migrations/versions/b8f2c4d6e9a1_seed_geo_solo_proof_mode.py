"""seed geo.solo_proof_mode system setting

Sprint 8.5-5a: CMS-ключ гейта solo location-proof (off|enforce) — строка
обязана существовать в system_settings, чтобы админ мог включить enforce
через PUT /api/v1/admin/system-settings/geo.solo_proof_mode.

Идемпотентная append-only data-миграция (по образцу a7c9e1f3b5d2): вставляем
строку только если ключа ещё нет в system_settings (bulk_insert упал бы на
PK при ручных строках на dev). Только SQLAlchemy Core (sa.table +
select/insert), без диалект-специфичного SQL — работает и на SQLite, и на PG.
created_at/updated_at заполняются server default (func.now()).

ВАЖНО: строка обязана совпадать с код-каталогом (system_settings_catalog.py)
по value_type/category/is_sensitive — иначе admin_system_settings отдаёт 409.
Также validate_catalog_values() требует присутствия ВСЕХ ключей каталога,
поэтому эта миграция идёт в паре с возвратом строгого инварианта (Sprint
8.5-5a); downgrade запрещён (append-only), поэтому откат невозможен.

Revision ID: b8f2c4d6e9a1
Revises: f06ca2ff1b61
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8f2c4d6e9a1"
down_revision: Union[str, Sequence[str], None] = "f06ca2ff1b61"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PROOF_MODE_KEY = "geo.solo_proof_mode"


def upgrade() -> None:
    """Идемпотентно добавить geo.solo_proof_mode = "off" (append-only)."""
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
            settings_table.c.key == PROOF_MODE_KEY
        )
    ).first()
    if existing is not None:
        return

    bind.execute(
        settings_table.insert().values(
            key=PROOF_MODE_KEY,
            value_json="off",
            value_type="string",
            category="geo",
            title="Гейт solo location-proof",
            description="Sprint 8.5: solo location-proof gate (off|enforce).",
            is_sensitive=False,
            status="active",
        )
    )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )
