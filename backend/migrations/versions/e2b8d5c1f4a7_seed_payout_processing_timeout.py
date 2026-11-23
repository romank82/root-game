"""seed ton.payout_processing_timeout_hours system setting

Шаг 5 плана внешних выплат (docs/withdrawal-external-payout-plan.md):
фоновый джоб возвращает заявки просроченного батча в pending, чтобы забытый
батч не держал деньги игроков в processing бесконечно.

Зачем миграция: validate_catalog_values() требует присутствия ВСЕХ ключей
код-каталога в таблице system_settings. Без data-seed любой PUT
/api/v1/admin/system-settings/{key} отдавал бы 422.

Миграция append-only и идемпотентная: существующая строка НЕ трогается —
значение, выставленное админом, не перезаписывается. Значения заморожены и
совпадают с код-каталогом. Только SQLAlchemy Core: работает и на SQLite,
и на PostgreSQL.

Revision ID: e2b8d5c1f4a7
Revises: c7f1a4e9b2d8
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e2b8d5c1f4a7"
down_revision: Union[str, Sequence[str], None] = "c7f1a4e9b2d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SETTING_KEY = "ton.payout_processing_timeout_hours"


def _settings_table() -> sa.TableClause:
    return sa.table(
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


def upgrade() -> None:
    """Добавить ton.payout_processing_timeout_hours, если его ещё нет."""
    bind = op.get_bind()
    settings_table = _settings_table()

    existing = bind.execute(
        sa.select(settings_table.c.key).where(
            settings_table.c.key == SETTING_KEY
        )
    ).scalar_one_or_none()

    if existing is None:
        bind.execute(
            settings_table.insert().values(
                key=SETTING_KEY,
                value_json=24,
                value_type="integer",
                category="ton",
                title="Таймаут обработки батча выплат",
                description=(
                    "Сколько часов батч может висеть неподтверждённым, "
                    "прежде чем фоновый джоб вернёт его заявки в pending. "
                    "Защита от забытого батча, который держит деньги игроков."
                ),
                is_sensitive=False,
                status="active",
            )
        )


def downgrade() -> None:
    """Откат: удалить ключ ton.payout_processing_timeout_hours."""
    bind = op.get_bind()
    settings_table = _settings_table()
    bind.execute(
        sa.delete(settings_table).where(settings_table.c.key == SETTING_KEY)
    )
