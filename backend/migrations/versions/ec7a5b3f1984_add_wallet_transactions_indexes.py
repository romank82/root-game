"""add wallet transactions indexes

Индексы для реестра транзакций (9.2): фильтры по created_at (from/to)
и по transaction_type (credit/debit). Без них запросы по диапазону дат
упираются в seq scan таблицы проводок; композит (type, created_at)
покрывает типовой случай «все credit/debit за период».

Revision ID: ec7a5b3f1984
Revises: f4c2e8a1d9b6
Create Date: 2026-10-22
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "ec7a5b3f1984"
down_revision: Union[str, Sequence[str], None] = "f4c2e8a1d9b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Индексы для реестра транзакций (9.2).

    Добавление индексов — не destructive: существующие данные и
    схема не меняются, только ускоряются фильтры реестра.
    """
    op.create_index(
        "ix_wallet_transactions_created_at",
        "wallet_transactions",
        ["created_at"],
    )
    op.create_index(
        "ix_wallet_transactions_type_created",
        "wallet_transactions",
        ["transaction_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_wallet_transactions_type_created",
        table_name="wallet_transactions",
    )
    op.drop_index(
        "ix_wallet_transactions_created_at",
        table_name="wallet_transactions",
    )