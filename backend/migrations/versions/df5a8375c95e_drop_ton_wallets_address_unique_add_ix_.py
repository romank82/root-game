"""drop ton_wallets address unique, add ix (11.0-a)

Убрать uq_ton_wallets_address из ton_wallets (11.0-a): unique по address
даёт 500, если другой игрок сохраняет адрес, занятый (даже 'removed')
первым. uq_ton_wallets_player_id ОСТАЁТСЯ (одна строка на игрока), как и
CK/FK. Вместо autoindex'а unique добавляется обычный индекс
ix_ton_wallets_address — поиск по адресу не теряется.

Поведение по СУБД:
- PostgreSQL: op.drop_constraint("uq_ton_wallets_address", type_="unique")
  работает (named constraint), индекс создаётся op.create_index.
- SQLite: ALTER TABLE ... DROP CONSTRAINT не поддерживается; в CREATE
  TABLE unique реализован autoindex'ом без явного имени. Alembic
  batch_alter_table пересоздаёт таблицу (temporary + copy + rename),
  сохраняя данные и остальные constraints/indexes; в batch контексте
  drop_constraint + create_index выполняются над recreate-ом.

downgrade не поддерживается — immutable policy (откат только через
проверенный backup, как и в parent-миграции).

Revision ID: df5a8375c95e
Revises: 3a1eaf8079e4
Create Date: 2026-10-26 11:44:49.838237

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'df5a8375c95e'
down_revision: Union[str, Sequence[str], None] = '3a1eaf8079e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Убрать uq_ton_wallets_address, добавить обычный индекс по address."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite не умеет DROP CONSTRAINT: batch_alter_table пересоздаёт
        # таблицу (данные сохраняются, остальные constraints — да).
        with op.batch_alter_table("ton_wallets") as batch_op:
            batch_op.create_index("ix_ton_wallets_address", ["address"])
            batch_op.drop_constraint(
                "uq_ton_wallets_address", type_="unique"
            )
    else:
        # PostgreSQL: named unique constraint, drop напрямую.
        op.create_index("ix_ton_wallets_address", "ton_wallets", ["address"])
        op.drop_constraint(
            "uq_ton_wallets_address",
            "ton_wallets",
            type_="unique",
        )


def downgrade() -> None:
    """Downgrade не поддерживается (immutable policy).

    Откат только через проверенный backup базы данных
    (backend/chimera.pre-drop-ton-address-unique.db).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
