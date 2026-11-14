"""add withdrawal request_id (client idempotency key)

A10: повторный POST /api/v1/me/withdrawals (двойной клик/retry сети) не
должен создавать вторую заявку и второе списание ROOT. request_id —
клиентский idempotency key; partial unique (player_id, request_id) WHERE
request_id IS NOT NULL защищает на уровне БД. Колонка nullable: у
исторических заявок ключа нет, backfill не требуется.

Revision ID: d1f5e8b3c7a2
Revises: c9e3b6f2a4d8
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1f5e8b3c7a2"
down_revision: Union[str, Sequence[str], None] = "c9e3b6f2a4d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить request_id и partial unique индекс идемпотентности."""
    op.add_column(
        "withdrawal_requests",
        sa.Column("request_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_withdrawal_requests_request_id"),
        "withdrawal_requests",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "uq_withdrawal_requests_player_request",
        "withdrawal_requests",
        ["player_id", "request_id"],
        unique=True,
        postgresql_where=sa.text("request_id IS NOT NULL"),
        sqlite_where=sa.text("request_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade не поддерживается (immutable-миграция)."""
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )