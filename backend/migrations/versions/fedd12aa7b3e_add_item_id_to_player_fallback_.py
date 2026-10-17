"""add item_id to player_fallback_entitlements

Revision ID: fedd12aa7b3e
Revises: 46acb135d92a
Create Date: 2026-10-17 21:09:00.337437

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fedd12aa7b3e'
down_revision: Union[str, Sequence[str], None] = '46acb135d92a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_UNIQUE_NAME = "uq_player_fallback_entitlements_player_mission"
NEW_UNIQUE_NAME = "uq_pfe_player_mission_item"


def upgrade() -> None:
    """Sprint 8.16: item_id на entitlement + unique (player, mission, item).

    Правило: при провале первой попытки в магазин попадает КАЖДЫЙ
    ключ-награда миссии отдельным entitlement'ом. item_id указывает, на
    какой item выдан entitlement; unique переходит с (player_id, mission_id)
    на (player_id, mission_id, item_id).

    SQLite: DDL/constraints — только через batch_alter_table (rebuild таблицы
    с копированием данных и переносом индексов/checks); для PostgreSQL
    batch — обычный ALTER.
    """
    with op.batch_alter_table("player_fallback_entitlements") as batch_op:
        batch_op.add_column(sa.Column("item_id", sa.String(length=64), nullable=True))

    # Backfill legacy-строк: до Sprint 8.16 на миссию существовал ровно один
    # entitlement, и offer_id хранил id предмета-ключа. Новые строки пишут
    # item_id всегда; старым проставляем item_id = offer_id.
    op.execute(
        "UPDATE player_fallback_entitlements SET item_id = offer_id "
        "WHERE item_id IS NULL"
    )

    with op.batch_alter_table("player_fallback_entitlements") as batch_op:
        batch_op.drop_constraint(OLD_UNIQUE_NAME, type_="unique")
        batch_op.create_unique_constraint(
            NEW_UNIQUE_NAME,
            ["player_id", "mission_id", "item_id"],
        )


def downgrade() -> None:
    """Данные не удаляем; откат — проверенным бэкапом или отдельной миграцией."""
    raise NotImplementedError(
        "Downgrade is intentionally unsupported: subdivision of entitlement "
        "per (player, mission, item) is irreversible without data loss. "
        "Rollback uses a verified backup."
    )
