"""add stars_payments (покупка газа за Telegram Stars)

Stars (10.4-g-1): журнал покупок газа. Одна запись = один инвойс.

- stars_payments: id, player_id (FK game_players RESTRICT), gas_amount
  (Numeric(18,4) — сколько газа начислить), amount_stars (Integer —
  сколько звёзд заплатил), telegram_payment_charge_id (String(255),
  nullable — заполняется после successful_payment, нужен для refund),
  status (String(16), default 'pending'),
  reference_id (String(64), уникальный — идемпотентность/связь с
  инвойсом), payload (String(255) — payload инвойса для сопоставления),
  created_at/updated_at (server_default=now(), как TimestampMixin).
- UniqueConstraint reference_id (uq_stars_payments_reference_id);
  CheckConstraint amount_stars > 0, gas_amount > 0,
  status IN ('pending','completed','refunded').
- ondelete RESTRICT: финансовая история не должна пропадать при удалении
  игрока.

Revision ID: 274519482c7d
Revises: 7f2f8baa1358
Create Date: 2026-10-23 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '274519482c7d'
down_revision: Union[str, Sequence[str], None] = '7f2f8baa1358'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицу stars_payments (10.4-g-1)."""
    op.create_table(
        "stars_payments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("gas_amount", sa.Numeric(18, 4), nullable=False),
        sa.Column("amount_stars", sa.Integer(), nullable=False),
        sa.Column(
            "telegram_payment_charge_id",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reference_id", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.String(length=255), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
            name="fk_stars_payments_player",
        ),
        sa.UniqueConstraint(
            "reference_id",
            name="uq_stars_payments_reference_id",
        ),
        sa.CheckConstraint(
            "amount_stars > 0",
            name="ck_stars_payments_amount_stars_positive",
        ),
        sa.CheckConstraint(
            "gas_amount > 0",
            name="ck_stars_payments_gas_amount_positive",
        ),
        sa.CheckConstraint(
            "status IN ('pending','completed','refunded')",
            name="ck_stars_payments_status",
        ),
    )
    op.create_index(
        "ix_stars_payments_player_id",
        "stars_payments",
        ["player_id"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
