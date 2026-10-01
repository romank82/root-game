"""make wallet transactions immutable

Revision ID: 0b9e7c6d5a41
Revises: 8d5e2f0b3c74
Create Date: 2026-09-30
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0b9e7c6d5a41"
down_revision: Union[str, Sequence[str], None] = "8d5e2f0b3c74"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POSTGRES_FUNCTION = "prevent_wallet_transaction_mutation"
_POSTGRES_TRIGGER = "wallet_transactions_no_mutation"
_SQLITE_UPDATE_TRIGGER = "wallet_transactions_no_update"
_SQLITE_DELETE_TRIGGER = "wallet_transactions_no_delete"


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name

    if dialect_name == "postgresql":
        op.execute(
            f"""
            CREATE FUNCTION {_POSTGRES_FUNCTION}()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'wallet_transactions are immutable'
                    USING ERRCODE = '55000';
                RETURN NULL;
            END;
            $$;
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {_POSTGRES_TRIGGER}
            BEFORE UPDATE OR DELETE ON wallet_transactions
            FOR EACH ROW
            EXECUTE FUNCTION {_POSTGRES_FUNCTION}();
            """
        )
        return

    if dialect_name == "sqlite":
        op.execute(
            f"""
            CREATE TRIGGER {_SQLITE_UPDATE_TRIGGER}
            BEFORE UPDATE ON wallet_transactions
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'wallet_transactions are immutable');
            END;
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER {_SQLITE_DELETE_TRIGGER}
            BEFORE DELETE ON wallet_transactions
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'wallet_transactions are immutable');
            END;
            """
        )
        return

    raise RuntimeError(
        "wallet transaction immutability migration supports only "
        "SQLite and PostgreSQL."
    )


def downgrade() -> None:
    dialect_name = op.get_bind().dialect.name

    if dialect_name == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} ON wallet_transactions"
        )
        op.execute(f"DROP FUNCTION IF EXISTS {_POSTGRES_FUNCTION}()")
        return

    if dialect_name == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_UPDATE_TRIGGER}")
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_DELETE_TRIGGER}")
        return

    raise RuntimeError(
        "wallet transaction immutability migration supports only "
        "SQLite and PostgreSQL."
    )
