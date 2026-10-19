"""add run_entry_count to player_fallback_entitlements

Revision ID: 0d81aed8029c
Revises: 04d49c146899
Create Date: 2026-10-19 08:35:49.506243

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0d81aed8029c'
down_revision: Union[str, Sequence[str], None] = '04d49c146899'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Sprint 8.17 (шаг 8): run_entry_count на entitlement.

    Многоразовая миссия: каждый новый заход — новый шанс на ключ. Номер
    захода (PlayerMission.entry_count на момент выдачи/re-arm) пишется в
    run_entry_count: существующий exhausted-предложение прошлого захода
    переармируется (status=available, consumed_count=0), а reference_id
    покупки привязывается к заходу ({id}:{run}:{count}) — это сохраняет
    идемпотентность ledger при повторных покупках по разным заходам.

    SQLite: DDL — через batch_alter_table (rebuild с копированием данных);
    для PostgreSQL batch — обычный ALTER. server_default=0 удовлетворяет
    NOT NULL и для legacy-строк (обратная совместимость: старые entitlement'ы
    получают run_entry_count=0, что корректно переармируется при новом заходе).
    """
    with op.batch_alter_table("player_fallback_entitlements") as batch_op:
        batch_op.add_column(
            sa.Column(
                "run_entry_count",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )


def downgrade() -> None:
    """Данные не удаляем; откат — проверенным бэкапом или отдельной миграцией."""
    raise NotImplementedError(
        "Downgrade is intentionally unsupported: dropping run_entry_count "
        "would lose per-run reference identity and break re-arm tracking. "
        "Rollback uses a verified backup."
    )
