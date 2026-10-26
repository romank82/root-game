"""add ton_wallets, withdrawal_requests (вывод ROOT в TON)

Этап 11 (11.1 + 11.2): TON-адреса игроков и заявки на вывод
ROOT → TON (testnet). Фактическая логика вывода — отдельно (11.5).

ton_wallets:
- id String(64) PK, генерация как 'ton-wallet-<uuid4-hex>'.
- player_id FK game_players.id ON DELETE RESTRICT — один игрок = один
  TON-адрес; unique uq_ton_wallets_player_id.
- address String(128) NOT NULL — TON-адрес строкой;
  unique uq_ton_wallets_address.
- status String(32) NOT NULL default 'active' — check ('active','removed');
  физическое удаление записей запрещено.
- created_at/updated_at — server_default=now() (как TimestampMixin).

withdrawal_requests:
- id String(64) PK, генерация как 'withdrawal-<uuid4-hex>'.
- player_id FK game_players.id ON DELETE RESTRICT, индекс
  ix_withdrawal_requests_player_id.
- amount_root BigInteger NOT NULL — ПОМЕТКА 11.8: сейчас целый ROOT
  (1:1), позже — NanoROOT (10^8); тип BigInteger, чтобы не менять
  схему при переходе на дробный ROOT.
- to_address String(128) NOT NULL — TON-адрес назначения на момент
  заявки (снимок из ton_wallets).
- status String(32) NOT NULL default 'pending' — check
  ('pending','approved','rejected','processing','confirmed','failed');
  индекс ix_withdrawal_requests_status.
- ton_tx_hash String(128) nullable — хэш транзакции TON после отправки;
  индекс ix_withdrawal_requests_ton_tx_hash.
- batch_id String(64) nullable — пакетный вывод (11.5);
  индекс ix_withdrawal_requests_batch_id.
- admin_id FK admin_users.id ON DELETE RESTRICT nullable — админ,
  подтвердивший/исполнивший заявку (11.6).
- reason String(255) nullable — причина подтверждения/отклонения.
- created_at/updated_at — server_default=now() (как TimestampMixin).
- CheckConstraint amount_root > 0.

Физическое удаление финансовой/статусной истории запрещено
(immutable-журнал). downgrade не поддерживается — откат только через
проверенный backup базы данных.

Revision ID: 3a1eaf8079e4
Revises: 50178ee857c8
Create Date: 2026-10-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3a1eaf8079e4'
down_revision: Union[str, Sequence[str], None] = '50178ee857c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицы ton_wallets и withdrawal_requests (11.1+11.2)."""
    op.create_table(
        "ton_wallets",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("address", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
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
            name="fk_ton_wallets_player",
        ),
        sa.UniqueConstraint(
            "player_id",
            name="uq_ton_wallets_player_id",
        ),
        sa.UniqueConstraint(
            "address",
            name="uq_ton_wallets_address",
        ),
        sa.CheckConstraint(
            "status IN ('active','removed')",
            name="ck_ton_wallets_status",
        ),
    )
    op.create_table(
        "withdrawal_requests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("amount_root", sa.BigInteger(), nullable=False),
        sa.Column("to_address", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("ton_tx_hash", sa.String(length=128), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("admin_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
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
            name="fk_withdrawal_requests_player",
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["admin_users.id"],
            ondelete="RESTRICT",
            name="fk_withdrawal_requests_admin",
        ),
        sa.CheckConstraint(
            "amount_root > 0",
            name="ck_withdrawal_requests_amount_root_positive",
        ),
        sa.CheckConstraint(
            "status IN "
            "('pending','approved','rejected','processing','confirmed','failed')",
            name="ck_withdrawal_requests_status",
        ),
    )

    op.create_index(
        "ix_withdrawal_requests_player_id",
        "withdrawal_requests",
        ["player_id"],
    )
    op.create_index(
        "ix_withdrawal_requests_status",
        "withdrawal_requests",
        ["status"],
    )
    op.create_index(
        "ix_withdrawal_requests_ton_tx_hash",
        "withdrawal_requests",
        ["ton_tx_hash"],
    )
    op.create_index(
        "ix_withdrawal_requests_batch_id",
        "withdrawal_requests",
        ["batch_id"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается (immutable-журнал).

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )

