"""seed mission force complete approval threshold

Revision ID: 2d9d53912eb9
Revises: 92aa64e01b1a
Create Date: 2026-10-07 18:39:00.675665

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2d9d53912eb9'
down_revision: Union[str, Sequence[str], None] = '92aa64e01b1a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Adds the economy.mission_force_complete_approval_threshold system setting.

    Append-only data migration (CMS-first): the row must exist so that
    force-complete approval gating is configurable through System Settings
    instead of hardcoded rules. created_at/updated_at are filled by server
    defaults (CURRENT_TIMESTAMP); status relies on the row default 'active'.
    """
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
    op.bulk_insert(
        settings_table,
        [
            {
                "key": "economy.mission_force_complete_approval_threshold",
                "value_json": 5000,
                "value_type": "integer",
                "category": "economy",
                "title": "Порог approval для принудительного завершения миссии",
                "description": (
                    "Сумма ROOT-наград миссии, начиная с которой "
                    "mission-force-complete создаёт approval-заявку."
                ),
                "is_sensitive": True,
                "status": "active",
            }
        ],
    )


def downgrade() -> None:
    """Deliberately not implemented: system_settings data is append-only."""
    raise NotImplementedError(
        "SystemSettings seed data migrations cannot be downgraded (append-only)."
    )
