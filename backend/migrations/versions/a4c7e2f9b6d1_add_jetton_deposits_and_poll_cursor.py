"""add jetton_deposits and ton_poll_cursor + seed ton.deposit_* settings

Sprint 1.1 (депозит ROOT-jetton): входящие переводы на сейф и курсор поллинга.

jetton_deposits:
- id String(64) PK ('jetton-deposit-<uuid4-hex>').
- tx_hash String(64) NOT NULL, unique uq_jetton_deposits_tx_hash — идемпотентность.
- lt BigInteger NOT NULL — logical time транзакции TonCenter.
- query_id String(64) nullable — query_id TEP-74 перевода.
- from_address / to_address / jetton_master String(128) NOT NULL.
- amount_nano BigInteger NOT NULL — сумма в наноROOT (1 ROOT = 10^8).
- player_id FK game_players.id ON DELETE RESTRICT nullable — null => pending
  (перевод не сопоставлен с игроком, ручной разбор).
- status String(32) NOT NULL — check ('pending','confirmed','rejected');
  индекс ix_jetton_deposits_status.
- raw_payload JSON nullable — сырой payload транзакции для разбора.
- confirmed_at DateTime(timezone=True) nullable.
- created_at/updated_at — server_default=now() (как TimestampMixin).

ton_poll_cursor:
- id String(64) PK — singleton (фиксированный id 'ton_poll_cursor').
- last_lt BigInteger NOT NULL — последний обработанный lt.
- last_hash String(64) NOT NULL — последний обработанный hash.
- created_at/updated_at — server_default=now().

Сид: ton.deposit_enabled (boolean, False) и ton.min_deposit_root (integer, 1)
добавляются в system_settings — иначе validate_catalog_values() (строгий
инвариант каталога) падал бы на любом PUT /admin/system-settings.

Физическое удаление записей запрещено (immutable-журнал депозитов).

Revision ID: a4c7e2f9b6d1
Revises: d1f5e8b3c7a2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c7e2f9b6d1'
down_revision: Union[str, Sequence[str], None] = 'd1f5e8b3c7a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (key, value_json, value_type, category, title, description, is_sensitive)
DEPOSIT_SETTINGS = [
    (
        "ton.deposit_enabled",
        False,
        "boolean",
        "ton",
        "Депозит ROOT-jetton включён",
        "Рубильник депозита ROOT-jetton (входящие).",
        False,
    ),
    (
        "ton.min_deposit_root",
        1,
        "integer",
        "ton",
        "Минимум депозита ROOT",
        "Минимальная сумма депозита ROOT-jetton (в ROOT).",
        False,
    ),
]


def upgrade() -> None:
    """Создать таблицы депозита и курсора + сид ton.deposit_*."""
    op.create_table(
        "ton_poll_cursor",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("last_lt", sa.BigInteger(), nullable=False),
        sa.Column("last_hash", sa.String(length=64), nullable=False),
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
    )
    op.create_table(
        "jetton_deposits",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tx_hash", sa.String(length=64), nullable=False),
        sa.Column("lt", sa.BigInteger(), nullable=False),
        sa.Column("query_id", sa.String(length=64), nullable=True),
        sa.Column("from_address", sa.String(length=128), nullable=False),
        sa.Column("to_address", sa.String(length=128), nullable=False),
        sa.Column("jetton_master", sa.String(length=128), nullable=False),
        sa.Column("amount_nano", sa.BigInteger(), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
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
            name="fk_jetton_deposits_player",
        ),
        sa.UniqueConstraint("tx_hash", name="uq_jetton_deposits_tx_hash"),
        sa.CheckConstraint(
            "status IN ('pending','confirmed','rejected')",
            name="ck_jetton_deposits_status",
        ),
    )
    op.create_index(
        "ix_jetton_deposits_player_id", "jetton_deposits", ["player_id"]
    )
    op.create_index(
        "ix_jetton_deposits_status", "jetton_deposits", ["status"]
    )

    # Сид (идемпотентный): validate_catalog_values() требует присутствия
    # всех ключей каталога в БД — без них любой PUT system-settings = 422.
    bind = op.get_bind()
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
    existing_keys = set(
        bind.execute(sa.select(settings_table.c.key)).scalars().all()
    )
    for (
        key,
        value,
        value_type,
        category,
        title,
        description,
        sensitive,
    ) in DEPOSIT_SETTINGS:
        if key in existing_keys:
            continue
        bind.execute(
            settings_table.insert().values(
                key=key,
                value_json=value,
                value_type=value_type,
                category=category,
                title=title,
                description=description,
                is_sensitive=sensitive,
                status="active",
            )
        )


def downgrade() -> None:
    """Откат: убрать сид ton.deposit_* и дропнуть таблицы."""
    bind = op.get_bind()
    settings_table = sa.table(
        "system_settings",
        sa.column("key", sa.String()),
    )
    for key, *_ in DEPOSIT_SETTINGS:
        bind.execute(
            sa.delete(settings_table).where(settings_table.c.key == key)
        )
    op.drop_table("jetton_deposits")
    op.drop_table("ton_poll_cursor")

