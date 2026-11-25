"""add payout_batches.signed_boc and ton.payout_auto_confirm_enabled

Шаг «автоподтверждение выплат» (решение владельца 25.11.2026,
docs/token-migration-decisions.md п.9).

Зачем signed_boc: после подписи в Tonkeeper заявки остаются в processing,
пока блокчейн не покажет перевод. Если сеть отстаёт, админу приходилось
вручную жать «Сверить». Сохранённый BOC позволяет фоновому джобу повторить
сверку самому.

Зачем тумблер: без него автоподтверждение нельзя выключить без деплоя.

Миграция идемпотентна: проверяет наличие колонки/строки перед изменением.
Работает и на SQLite, и на PostgreSQL.

Revision ID: b7d4e1c8f2a3
Revises: a5c3e7d9b6f2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7d4e1c8f2a3"
down_revision: Union[str, Sequence[str], None] = "a5c3e7d9b6f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SETTING_KEY = "ton.payout_auto_confirm_enabled"


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


def _column_exists(bind, table: str, column: str) -> bool:
    inspector = sa.inspect(bind)
    return column in {item["name"] for item in inspector.get_columns(table)}


def upgrade() -> None:
    """Добавить signed_boc в payout_batches и тумблер автоподтверждения."""
    bind = op.get_bind()

    if not _column_exists(bind, "payout_batches", "signed_boc"):
        op.add_column(
            "payout_batches",
            sa.Column("signed_boc", sa.Text(), nullable=True),
        )

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
                value_json=True,
                value_type="boolean",
                category="ton",
                title="Автоподтверждение выплат",
                description=(
                    "Фоновый джоб сам повторяет сверку с блокчейном по "
                    "сохранённому подписанному BOC и подтверждает доставленные "
                    "выплаты. Кнопка «Сверить» остаётся ручным дублем."
                ),
                is_sensitive=False,
                status="active",
            )
        )


def downgrade() -> None:
    """Откат: удалить колонку и ключ настройки.

    ВАЖНО: на SQLite drop_column делается через пересоздание таблицы
    (batch_alter_table), а пересоздание теряет выраженный частичный индекс
    uq_payout_batches_one_open. Без него три воркера gunicorn смогут создать
    три открытых батча — это защита от двойных выплат. Поэтому индекс
    восстанавливаем явно после отката.
    """
    bind = op.get_bind()

    settings_table = _settings_table()
    bind.execute(
        sa.delete(settings_table).where(settings_table.c.key == SETTING_KEY)
    )

    if _column_exists(bind, "payout_batches", "signed_boc"):
        with op.batch_alter_table("payout_batches") as batch_op:
            batch_op.drop_column("signed_boc")

    # Восстановить инвариант «один открытый батч», если он потерялся.
    index_names = {
        item["name"] for item in sa.inspect(bind).get_indexes("payout_batches")
    }
    if "uq_payout_batches_one_open" not in index_names:
        op.create_index(
            "uq_payout_batches_one_open",
            "payout_batches",
            [sa.text("(1)")],
            unique=True,
            postgresql_where=sa.text("status IN ('ready', 'submitted')"),
            sqlite_where=sa.text("status IN ('ready', 'submitted')"),
        )
