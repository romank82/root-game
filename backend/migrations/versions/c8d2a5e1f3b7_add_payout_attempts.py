"""add payout attempt durable outbox

A6+A7: durable state machine for TON payouts. One row per Jetton transfer
attempt: 'sending' is created BEFORE the blockchain send, then the attempt
transitions to 'sent' (with tx_hash) or 'failed' (with error). The partial
unique indexes prevent (a) two concurrent 'sending' attempts for the same
withdrawal and (b) a second send after a 'sending'/'sent' attempt already
exists. query_id is the blockchain-level idempotency key of the transfer.

Revision ID: c8d2a5e1f3b7
Revises: a7f3c2d9e1b0
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8d2a5e1f3b7"
down_revision: Union[str, Sequence[str], None] = "a7f3c2d9e1b0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать immutable-таблицу payout_attempts (idempotent outbox для TON)."""
    op.create_table(
        "payout_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "withdrawal_id",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("query_id", sa.String(length=64), nullable=False),
        sa.Column("tx_hash", sa.String(length=256), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
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
        sa.CheckConstraint(
            "status IN ('sending', 'sent', 'failed')",
            name="ck_payout_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["withdrawal_id"],
            ["withdrawal_requests.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id", name="uq_payout_attempts_query_id"),
    )
    op.create_index(
        op.f("ix_payout_attempts_withdrawal_id"),
        "payout_attempts",
        ["withdrawal_id"],
        unique=False,
    )
    # Не более одной 'sending'/'sent' попытки на заявку: гонка двух
    # batch-запусков и повторная отправка уже отправленной выплаты.
    op.create_index(
        "uq_payout_attempts_no_second_send",
        "payout_attempts",
        ["withdrawal_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('sending', 'sent')"),
        sqlite_where=sa.text("status IN ('sending', 'sent')"),
    )


def downgrade() -> None:
    """Downgrade не поддерживается (immutable-миграция)."""
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )