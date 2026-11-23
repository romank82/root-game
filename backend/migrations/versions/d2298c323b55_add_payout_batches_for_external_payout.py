"""add payout batches for external payout

Вывод ROOT через внешний кошелёк (Tonkeeper Multisend) вместо отправки с
сервера: 11.x-external-payout. План — docs/withdrawal-external-payout-plan.md.

Создаёт таблицу payout_batches со статусами ready -> submitted -> confirmed
(либо rolled_back) и **частичный unique-индекс на «один открытый батч»**.

Зачем индекс: планировщик APScheduler живёт в lifespan, то есть в КАЖДОМ из
3 воркеров gunicorn (deploy/root-game.service: -w 3). Ежедневная задача
«сформировать батч» запустится трижды одновременно. Защита в Python
(`if scheduler is not None`) работает внутри процесса и не спасает, поэтому
барьер держит БД: второй и третий INSERT падают с IntegrityError, и дублей
не возникает.

Миграция append-only: downgrade удаляет только созданную таблицу (данных
выплат в ней ещё нет на момент внедрения).

Revision ID: d2298c323b55
Revises: b5e3d8a4c2f6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2298c323b55"
down_revision: Union[str, Sequence[str], None] = "b5e3d8a4c2f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать payout_batches + частичный unique-индекс на открытый батч."""
    op.create_table(
        "payout_batches",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "admin_id",
            sa.String(length=64),
            sa.ForeignKey(
                "admin_users.id",
                ondelete="SET NULL",
                name="fk_payout_batches_admin_id_admin_users",
            ),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="ready",
        ),
        sa.Column(
            "total_nano",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("payload_text", sa.Text(), nullable=True),
        sa.Column("tx_hash", sa.String(length=256), nullable=True),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'submitted', 'confirmed', 'rolled_back')",
            name="ck_payout_batches_status",
        ),
    )

    op.create_index(
        "ix_payout_batches_status",
        "payout_batches",
        ["status"],
        unique=False,
    )

    # Один открытый батч на всю систему. Диалект-специфичные частичные
    # индексы создаём явным DDL: Alembic не умеет их через create_index
    # одинаково для SQLite и PostgreSQL.
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute(
            "CREATE UNIQUE INDEX uq_payout_batches_one_open "
            "ON payout_batches ((1)) "
            "WHERE status IN ('ready', 'submitted')"
        )
    elif dialect == "sqlite":
        op.execute(
            "CREATE UNIQUE INDEX uq_payout_batches_one_open "
            "ON payout_batches ((1)) "
            "WHERE status IN ('ready', 'submitted')"
        )


def downgrade() -> None:
    """Удалить таблицу payout_batches (append-only: только новая схема)."""
    dialect = op.get_bind().dialect.name
    if dialect in ("postgresql", "sqlite"):
        op.execute("DROP INDEX IF EXISTS uq_payout_batches_one_open")
    op.drop_index("ix_payout_batches_status", table_name="payout_batches")
    op.drop_table("payout_batches")
