"""seed ton.payout_wallet_public_key system setting

Шаг 4 плана внешних выплат (docs/withdrawal-external-payout-plan.md):
подтверждение батча требует проверить подпись BOC от TON Connect. Для этого
нужен ed25519-публичный ключ кошелька выплат (hex, 32 байта).

Зачем миграция: validate_catalog_values() (app/system_settings_catalog.py)
требует присутствия ВСЕХ ключей код-каталога в таблице system_settings.
Ключ добавлен в каталог; без data-seed любой PUT
/api/v1/admin/system-settings/{key} отдавал бы 422 «Отсутствует системная
настройка». Значение по умолчанию пустое — ключ задаёт админ через UI, пока
он не задан, подтверждение выплат честно отказывает с 503.

Миграция append-only и идемпотентная: существующая строка НЕ трогается.
Значения заморожены и совпадают с код-каталогом, иначе admin_system_settings
отдаёт 409 «Метаданные настройки не соответствуют утверждённому каталогу».
Только SQLAlchemy Core — работает и на SQLite, и на PostgreSQL.

Revision ID: c7f1a4e9b2d8
Revises: d2298c323b55
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c7f1a4e9b2d8"
down_revision: Union[str, Sequence[str], None] = "d2298c323b55"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SETTING_KEY = "ton.payout_wallet_public_key"
SETTING_TITLE = "Публичный ключ кошелька выплат"
SETTING_DESCRIPTION = (
    "Ed25519 публичный ключ кошелька выплат (hex, 32 байта). "
    "По нему проверяется подпись BOC от TON Connect: без него "
    "подтверждение выплат невозможно."
)


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
    """Добавить ton.payout_wallet_public_key, если его ещё нет."""
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
                value_json="",
                value_type="string",
                category="ton",
                title=SETTING_TITLE,
                description=SETTING_DESCRIPTION,
                is_sensitive=True,
                status="active",
            )
        )


def downgrade() -> None:
    """Откат: удалить ключ ton.payout_wallet_public_key."""
    bind = op.get_bind()
    settings_table = _settings_table()
    bind.execute(
        sa.delete(settings_table).where(settings_table.c.key == SETTING_KEY)
    )
