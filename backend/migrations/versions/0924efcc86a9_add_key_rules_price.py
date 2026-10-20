"""add key_rules price

Revision ID: 0924efcc86a9
Revises: 0d81aed8029c
Create Date: 2026-10-20 15:11:19.727098

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0924efcc86a9'
down_revision: Union[str, Sequence[str], None] = '0d81aed8029c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Sprint 8.20: per-key цена ключа (fallback/каталог).

    Append-only: колонка price в key_rules — NULL = использовать глобальную
    настройку shop.*.default_price_root (фолбэк остаётся как раньше).
    server_default намеренно НЕ ставится: пустое значение означает «не задана».
    stack_limit НЕ трогаем (dead column в БД остаётся).
    """
    op.add_column('key_rules', sa.Column('price', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    raise NotImplementedError("Schema extension; downgrade not supported.")
