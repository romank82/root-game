"""risk_access_grants + seed risk.* system settings

Инфраструктура раздела «Риск» (docs/risk-section-contract.md).
Сами мини-игры не входят в этот шаг: только контейнер, разблокировка газом
и админ-настройки.

Что делает миграция:
1. Создаёт таблицу risk_access_grants — постоянный доступ игрока к разделу.
   Одна запись на игрока (unique player_id), газ уже списан immutable-проводкой
   GasTransaction с reference_type='risk_unlock'.
2. Засевает два ключа system_settings: risk.access_mode и risk.unlock_gas_cost.
   Без data-seed validate_catalog_values() отдавал бы 422 на любой PUT
   /api/v1/admin/system-settings/{key}, потому что каталог требует наличия всех
   ключей в БД.

Миграция append-only и идемпотентная: существующая строка настроек НЕ
перезаписывается (значение, выставленное админом, сохраняется). Только
SQLAlchemy Core — работает и на SQLite, и на PostgreSQL.

Revision ID: c4f8a2e71d93
Revises: b7d4e1c8f2a3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4f8a2e71d93"
down_revision: Union[str, Sequence[str], None] = "b7d4e1c8f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SETTINGS = (
    {
        "key": "risk.access_mode",
        "value_json": "hidden",
        "value_type": "string",
        "category": "risk",
        "title": "Режим доступа к разделу «Риск»",
        "description": (
            "hidden — раздел скрыт от всех; locked — виден, но требует "
            "разовой оплаты газом; open — доступен всем без оплаты."
        ),
        "is_sensitive": False,
    },
    {
        "key": "risk.unlock_gas_cost",
        "value_json": 100,
        "value_type": "integer",
        "category": "risk",
        "title": "Стоимость разблокировки раздела «Риск»",
        "description": (
            "Сколько газа списывается один раз с игрока за постоянный "
            "доступ к разделу «Риск»."
        ),
        "is_sensitive": False,
    },
)


def _settings_table() -> sa.TableClause:
    return sa.table(
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


def upgrade() -> None:
    # 1. Таблица постоянного доступа к разделу «Риск».
    op.create_table(
        "risk_access_grants",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("gas_cost_paid", sa.Numeric(18, 4), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id", name="uq_risk_access_grants_player_id"
        ),
        sa.CheckConstraint(
            "gas_cost_paid >= 0",
            name="ck_risk_access_grants_cost_nonnegative",
        ),
    )
    op.create_index(
        "ix_risk_access_grants_player_id",
        "risk_access_grants",
        ["player_id"],
        unique=False,
    )

    # 2. Seed настроек (append-only: существующие строки не трогаем).
    bind = op.get_bind()
    settings_table = _settings_table()
    for row in SETTINGS:
        existing = bind.execute(
            sa.select(settings_table.c.key).where(
                settings_table.c.key == row["key"]
            )
        ).scalar_one_or_none()
        if existing is None:
            bind.execute(
                settings_table.insert().values(
                    key=row["key"],
                    value_json=row["value_json"],
                    value_type=row["value_type"],
                    category=row["category"],
                    title=row["title"],
                    description=row["description"],
                    is_sensitive=row["is_sensitive"],
                    status="active",
                )
            )


def downgrade() -> None:
    op.drop_index(
        "ix_risk_access_grants_player_id",
        table_name="risk_access_grants",
    )
    op.drop_table("risk_access_grants")

    bind = op.get_bind()
    settings_table = _settings_table()
    for row in SETTINGS:
        bind.execute(
            sa.delete(settings_table).where(
                settings_table.c.key == row["key"]
            )
        )