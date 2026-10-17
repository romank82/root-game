"""enable shop catalog by default

Revision ID: 46acb135d92a
Revises: 6b9f3e7d2a15
Create Date: 2026-10-17 14:22:06.738733

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '46acb135d92a'
down_revision: Union[str, Sequence[str], None] = '6b9f3e7d2a15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Sprint 8.16: shop.catalog.enabled = True по умолчанию.

    Согласует БД с system_settings_catalog.py (default_value=True).
    value_json хранится как JSON-текст 'true' (как у shop.fallback.enabled).
    UPDATE — стандартный SQL, работает и в SQLite, и в PostgreSQL.
    """
    op.execute(
        "UPDATE system_settings SET value_json='true' "
        "WHERE key='shop.catalog.enabled'"
    )


def downgrade() -> None:
    """Data migration; downgrade not supported (сеед не меняем назад)."""
    raise NotImplementedError(
        "Data migration; downgrade not supported."
    )
