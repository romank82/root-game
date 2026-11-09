"""add nano root columns (Sprint 11.8 NanoROOT, этап 1, шаг 1.1)

Additive-миграция перехода от целого ROOT к дробному NanoROOT
(10^8 нано = 1 ROOT — совпадает с TEP-74 jetton decimals и с уже
существующей конвертацией withdrawal_service: amount_root * 10**8).

Что делает:
- Добавляет nullable BigInteger *_nano колонки во все таблицы, где
  хранится ROOT. Старые целые поля (Integer ROOT) НЕ трогаем —
  append-only, dual-write; сервисы/фронт переключаются на *_nano
  отдельным шагом (этап 2).
- Backfill: <field>_nano = <field> * 100000000 для строк, где новая
  колонка ещё NULL (идемпотентно). Умножение — через CAST(... AS BIGINT),
  чтобы избежать int4 overflow в PostgreSQL (amount Integer * 1e8 легко
  превышает 2^31-1).

Колонки (nullable, BigInteger):
- wallets.available_balance_nano, wallets.locked_balance_nano
- wallet_transactions.amount_nano, wallet_transactions.balance_after_nano
- player_transfers.amount_nano
- referral_rewards.amount_root_nano
- mission_rewards.amount_nano
- wallet_reservations.amount_nano
- withdrawal_requests.amount_root_nano (amount_root уже BigInteger)

ВАЖНО (immutable ledger):
- На wallet_transactions стоит BEFORE UPDATE триггер, запрещающий
  UPDATE (migration 0b9e7c6d5a41): SQLite wallet_transactions_no_update,
  PostgreSQL wallet_transactions_no_mutation → prevent_wallet_transaction_mutation().
  Прямой UPDATE для backfill упал бы. Поэтому backfill wallet_transactions
  выполняется trigger-safe: в рамках ОДНОЙ транзакции триггер временно
  DROP'ается, выполняется UPDATE, затем триггер пересоздаётся с
  ИДЕНТИЧНЫМ определением. DDL в SQLite и PostgreSQL транзакционен:
  если что-то упадёт — DROP откатится и защита ledger не теряется.
  Исторические значения (amount/balance_after/transaction_type) не
  меняются — заполняется только новая производная колонка.

Остальные таблицы (wallets, player_transfers, referral_rewards,
mission_rewards, wallet_reservations, withdrawal_requests) immutability-
триггеров на UPDATE не имеют — обычный UPDATE.

downgrade не поддерживается (append-only / immutable-политика):
откат только через проверенный backup базы данных.

Revision ID: b7a1c9d4e2f6
Revises: 2f8b4c1a6e0d
Create Date: 2026-11-09

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7a1c9d4e2f6"
down_revision: Union[str, Sequence[str], None] = "2f8b4c1a6e0d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Множитель NanoROOT: 10^8 нано = 1 ROOT (см. withdrawal_service / TEP-74).
_NANO_FACTOR = 100000000

# Определения immutability-триггеров на wallet_transactions — должны
# ТОЧНО совпадать с migration 0b9e7c6d5a41 (там они создавались).
_SQLITE_UPDATE_TRIGGER = "wallet_transactions_no_update"
_SQLITE_CREATE_UPDATE_TRIGGER = """
CREATE TRIGGER wallet_transactions_no_update
BEFORE UPDATE ON wallet_transactions
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'wallet_transactions are immutable');
END
"""
_POSTGRES_TRIGGER = "wallet_transactions_no_mutation"
_POSTGRES_CREATE_TRIGGER = """
CREATE TRIGGER wallet_transactions_no_mutation
BEFORE UPDATE OR DELETE ON wallet_transactions
FOR EACH ROW
EXECUTE FUNCTION prevent_wallet_transaction_mutation()
"""

# Таблицы с ROOT и их новые *_nano колонки. Добавляем отдельно через
# op.add_column (нативный ALTER TABLE ADD COLUMN — не пересобирает
# SQLite-таблицу и не теряет триггеры).
_NANO_COLUMNS: list[tuple[str, list[str]]] = [
    ("wallets", ["available_balance_nano", "locked_balance_nano"]),
    ("wallet_transactions", ["amount_nano", "balance_after_nano"]),
    ("player_transfers", ["amount_nano"]),
    ("referral_rewards", ["amount_root_nano"]),
    ("mission_rewards", ["amount_nano"]),
    ("wallet_reservations", ["amount_nano"]),
    ("withdrawal_requests", ["amount_root_nano"]),
]


def _add_columns() -> None:
    """Добавить nullable BigInteger *_nano колонки (append-only)."""
    for table, columns in _NANO_COLUMNS:
        for column in columns:
            op.add_column(table, sa.Column(column, sa.BigInteger(), nullable=True))


def _backfill_plain(table: str, assignments: list[tuple[str, str]]) -> None:
    """Идемпотентный backfill: <new> = CAST(<old> AS BIGINT) * factor.

    ``assignments`` — список пар (old_field, new_field). ``WHERE new IS NULL``
    защищает от повторного умножения; ``old IS NOT NULL`` — для nullable
    старых полей (например, mission_rewards.amount).
    """
    set_clause = ", ".join(
        f"{new} = CAST({old} AS BIGINT) * {_NANO_FACTOR}" for old, new in assignments
    )
    where_clause = " AND ".join(
        f"{new} IS NULL AND {old} IS NOT NULL" for old, new in assignments
    )
    op.execute(f"UPDATE {table} SET {set_clause} WHERE {where_clause}")


def _backfill_wallet_transactions() -> None:
    """Trigger-safe backfill ledger-таблицы wallet_transactions.

    Immutability-триггер (0b9e7c6d5a41) блокирует UPDATE. Временно снимаем
    ТОЛЬКО UPDATE-защиту, бэкфиллим, затем пересоздаём триггер идентично.
    Всё в одной транзакции миграции: при сбое DROP откатится.
    delete-триггер (SQLite wallet_transactions_no_delete) не трогаем.
    """
    dialect_name = op.get_bind().dialect.name

    if dialect_name == "sqlite":
        op.execute(f"DROP TRIGGER IF EXISTS {_SQLITE_UPDATE_TRIGGER}")
        _backfill_plain(
            "wallet_transactions",
            [("amount", "amount_nano"), ("balance_after", "balance_after_nano")],
        )
        op.execute(_SQLITE_CREATE_UPDATE_TRIGGER)
        return

    if dialect_name == "postgresql":
        op.execute(
            f"DROP TRIGGER IF EXISTS {_POSTGRES_TRIGGER} ON wallet_transactions"
        )
        _backfill_plain(
            "wallet_transactions",
            [("amount", "amount_nano"), ("balance_after", "balance_after_nano")],
        )
        # Функция prevent_wallet_transaction_mutation() осталась — только
        # пересоздаём триггер, который на неё ссылается.
        op.execute(_POSTGRES_CREATE_TRIGGER)
        return

    raise RuntimeError(
        "Sprint 11.8 NanoROOT backfill supports only SQLite and PostgreSQL."
    )


def upgrade() -> None:
    """Add *_nano BIGINT columns and backfill them (ROOT * 10^8)."""
    # 1. Схема: nullable BigInteger-колонки (native ADD COLUMN, триггеры целы).
    _add_columns()

    # 2. Backfill обычных таблиц (без immutability-триггеров на UPDATE).
    _backfill_plain(
        "wallets",
        [
            ("available_balance", "available_balance_nano"),
            ("locked_balance", "locked_balance_nano"),
        ],
    )
    _backfill_plain("player_transfers", [("amount", "amount_nano")])
    _backfill_plain("referral_rewards", [("amount_root", "amount_root_nano")])
    _backfill_plain("mission_rewards", [("amount", "amount_nano")])
    _backfill_plain("wallet_reservations", [("amount", "amount_nano")])
    _backfill_plain("withdrawal_requests", [("amount_root", "amount_root_nano")])

    # 3. Backfill ledger-таблицы — trigger-safe.
    _backfill_wallet_transactions()


def downgrade() -> None:
    """Downgrade не поддерживается (append-only / immutable-политика).

    Откат только через проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
