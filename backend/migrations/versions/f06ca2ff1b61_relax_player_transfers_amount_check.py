"""relax player_transfers amount check

Sprint 8.x-fractional-transfer (A2-5a): разрешить дробные переводы < 1 ROOT.

Legacy-поле ``player_transfers.amount`` — целые ROOT (floor от amount_nano).
При сумме < 1 ROOT floor даёт 0, поэтому старый CHECK ``amount > 0``
(74d3bb612729) не давал зафиксировать такой перевод. Меняем условие на
``amount >= 0`` под новым именем ``ck_player_transfers_amount_non_negative``.

Только DDL: логика ``transfer_service`` (``max(1, ...)``) меняется отдельно
(A2-5b). Историю не переписываем: append-only, downgrade не поддерживается.

Dialect-aware:
- PostgreSQL — DROP CONSTRAINT + ADD CONSTRAINT (named CHECK, тип ``check``);
- SQLite — прямой ALTER TABLE ... DROP/ADD CONSTRAINT невозможен, поэтому
  ``batch_alter_table`` пересоздаёт таблицу с сохранением данных; остальные
  constraints (PK, оба FK, uq_player_transfers_from_reference,
  ck_player_transfers_status) и индексы переносятся reflection'ом.

Revision ID: f06ca2ff1b61
Revises: b7a1c9d4e2f6
Create Date: 2026-11-11

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f06ca2ff1b61"
down_revision: Union[str, Sequence[str], None] = "b7a1c9d4e2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Старое условие (74d3bb612729) и новое — именованные CHECK-и.
_OLD_CONSTRAINT = "ck_player_transfers_amount_positive"
_NEW_CONSTRAINT = "ck_player_transfers_amount_non_negative"
_TABLE = "player_transfers"


def upgrade() -> None:
    """amount > 0 -> amount >= 0 (drop old CHECK, create new)."""
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.drop_constraint(_OLD_CONSTRAINT, _TABLE, type_="check")
        op.create_check_constraint(_NEW_CONSTRAINT, _TABLE, "amount >= 0")
        return

    if dialect == "sqlite":
        # SQLite не умеет ALTER TABLE DROP/ADD CONSTRAINT: batch пересоздаёт
        # таблицу data-preservingly (drop + create — один rebuild).
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.drop_constraint(_OLD_CONSTRAINT, type_="check")
            batch_op.create_check_constraint(_NEW_CONSTRAINT, "amount >= 0")
        return

    raise RuntimeError(
        "Relax player_transfers.amount check supports only SQLite and PostgreSQL."
    )


def downgrade() -> None:
    """Downgrade не поддерживается (append-only / immutable-политика).

    Откат только через проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
