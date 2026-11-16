"""seed ton.deposit_wallet system setting

Sprint 1.4: адрес «спец» кошелька для приёма ROOT-jetton (депозит).

Зачем: validate_catalog_values() (app/system_settings_catalog.py) требует
присутствия ВСЕХ ключей код-каталога в таблице system_settings. Ключ
ton.deposit_wallet добавлен в каталог в Sprint 1.4; без data-seed любой
PUT /api/v1/admin/system-settings/{key} отдавал бы 422 «Отсутствует системная
настройка: ton.deposit_wallet.». Значение по умолчанию пустое — адрес сейфа
задаётся админом через UI (поле появится автоматически: список настроек
читается из БД, редактор — по value_type).

Миграция append-only и идемпотентная: существующая строка НЕ трогается —
вставляется только при отсутствии ключа. Значения заморожены и должны
совпадать с код-каталогом, иначе admin_system_settings отдаёт 409
«Метаданные настройки не соответствуют утверждённому каталогу». Только
SQLAlchemy Core (sa.table + select/insert), без диалект-специфичного SQL —
работает и на SQLite, и на PostgreSQL.

Revision ID: b5e3d8a4c2f6
Revises: a4c7e2f9b6d1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5e3d8a4c2f6'
down_revision: Union[str, Sequence[str], None] = 'a4c7e2f9b6d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить ton.deposit_wallet, если его ещё нет (идемпотентно)."""
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
            settings_table.c.key == "ton.deposit_wallet"
        )
    ).scalar_one_or_none()

    if existing is None:
        bind.execute(
            settings_table.insert().values(
                key="ton.deposit_wallet",
                value_json="",
                value_type="string",
                category="ton",
                title="TON deposit wallet",
                description="Адрес «спец» кошелька для приёма ROOT-jetton (депозит).",
                is_sensitive=True,
                status="active",
            )
        )


def downgrade() -> None:
    """Откат: удалить ключ ton.deposit_wallet."""
    bind = op.get_bind()
    settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.String()),
    )
    bind.execute(
        sa.delete(settings_table).where(
            settings_table.c.key == "ton.deposit_wallet"
        )
    )
