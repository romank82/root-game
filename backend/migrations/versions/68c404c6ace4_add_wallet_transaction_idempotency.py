"""add wallet transaction idempotency

Revision ID: 68c404c6ace4
Revises: 343e08dd77aa
Create Date: 2026-09-16
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "68c404c6ace4"
down_revision: Union[str, Sequence[str], None] = "343e08dd77aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Не позволять одной и той же операции-источнику дважды начислить
    средства в один и тот же кошелёк.

    Для награды за миссию:
    (wallet_id, "mission_reward", mission_id) должен существовать
    не более одного раза.
    """
    op.create_index(
        "uq_wallet_transactions_wallet_reference",
        "wallet_transactions",
        ["wallet_id", "reference_type", "reference_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_wallet_transactions_wallet_reference",
        table_name="wallet_transactions",
    )
