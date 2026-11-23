"""seed ton.legacy_autopayout_enabled system setting

Старая автоматическая выплата (send_jetton_transfer с мнемоникой из .env)
заблокирована на уровне эндпоинта: она возвращает риск утечки ключа, ради
устранения которого сделаны внешние выплаты (docs/withdrawal-external-payout.md).

Эндпоинт POST /api/v1/admin/withdrawals/batch отдаёт 410, пока этот ключ не
равен true. Ключ добавлен в код-каталог, поэтому его нужно посеять: иначе
validate_catalog_values() ломает ЛЮБОЕ сохранение настроек (422 «Отсутствует
системная настройка»).

Миграция append-only и идемпотентная: существующая строка НЕ трогается, чтобы
аварийно выставленное админом значение не перезаписывалось. Значения
заморожены и совпадают с код-каталогом. Только SQLAlchemy Core — работает и
на SQLite, и на PostgreSQL.

Revision ID: a5c3e7d9b6f2
Revises: e2b8d5c1f4a7
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a5c3e7d9b6f2"
down_revision: Union[str, Sequence[str], None] = "e2b8d5c1f4a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SETTING_KEY = "ton.legacy_autopayout_enabled"


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
    """Добавить ton.legacy_autopayout_enabled = false, если его ещё нет."""
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
                value_json=False,
                value_type="boolean",
                category="ton",
                title="Старая автовыплата (аварийно)",
                description=(
                    "УСТАРЕЛО. Включает автоматическую отправку ROOT с сервера "
                    "по мнемонике TON_PAYOUT_MNEMONIC из .env. Это возвращает "
                    "риск утечки ключа: используйте вкладку «Батчи выплат» с "
                    "подписью в кошельке. Держать выключенным, кроме аварийной "
                    "ситуации."
                ),
                is_sensitive=True,
                status="active",
            )
        )


def downgrade() -> None:
    """Откат: удалить ключ ton.legacy_autopayout_enabled."""
    bind = op.get_bind()
    settings_table = _settings_table()
    bind.execute(
        sa.delete(settings_table).where(settings_table.c.key == SETTING_KEY)
    )
