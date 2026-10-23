"""add gas_wallet + gas_transaction

Газ (10.4): премиальная дробная валюта Numeric(18,4), покупается за Stars,
списывается за перевод ROOT. Отдельные таблицы от ROOT Wallet/WalletTransaction.

- gas_wallets: одна запись на игрока (UniqueConstraint player_id
  uq_gas_wallets_player_id), balance >= 0 (ck_gas_wallets_balance_nonnegative).
- gas_transactions: immutable-проводки; идемпотентность —
  (gas_wallet_id, reference_type, reference_id) (uq_gas_transactions_wallet_reference).
  reference_type/reference_id nullable (как в WalletTransaction): проводки
  операций всегда заполняют их; для NULL-значений PG/SQLite допускают
  несколько NULL-строк (стандартная семантика UNIQUE).
- amount > 0, balance_after >= 0 (CheckConstraint).
- ondelete RESTRICT у обоих FK: финансовая история не должна пропадать
  при удалении игрока/кошелька.
- balance: server_default=sa.text("0") (как в 0d81aed8029c/2f7a9c4e6d81);
  created_at/updated_at — server_default=now() (как TimestampMixin).

Revision ID: 7f2f8baa1358
Revises: 74d3bb612729
Create Date: 2026-10-23 21:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7f2f8baa1358'
down_revision: Union[str, Sequence[str], None] = '74d3bb612729'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицы gas_wallets и gas_transactions (10.4)."""
    op.create_table(
        "gas_wallets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column(
            "balance",
            sa.Numeric(18, 4),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
            name="fk_gas_wallets_player",
        ),
        sa.UniqueConstraint(
            "player_id",
            name="uq_gas_wallets_player_id",
        ),
        sa.CheckConstraint(
            "balance >= 0",
            name="ck_gas_wallets_balance_nonnegative",
        ),
    )
    op.create_index(
        "ix_gas_wallets_player_id",
        "gas_wallets",
        ["player_id"],
    )

    op.create_table(
        "gas_transactions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("gas_wallet_id", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("balance_after", sa.Numeric(18, 4), nullable=False),
        sa.Column("transaction_type", sa.String(length=16), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=True),
        sa.Column("reference_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["gas_wallet_id"],
            ["gas_wallets.id"],
            ondelete="RESTRICT",
            name="fk_gas_transactions_wallet",
        ),
        sa.UniqueConstraint(
            "gas_wallet_id",
            "reference_type",
            "reference_id",
            name="uq_gas_transactions_wallet_reference",
        ),
        sa.CheckConstraint(
            "amount > 0",
            name="ck_gas_transactions_amount_positive",
        ),
        sa.CheckConstraint(
            "balance_after >= 0",
            name="ck_gas_transactions_balance_after_nonnegative",
        ),
    )
    op.create_index(
        "ix_gas_transactions_wallet_id",
        "gas_transactions",
        ["gas_wallet_id"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )