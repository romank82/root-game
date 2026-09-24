"""add system settings foundation

Revision ID: e3a6f4b9c281
Revises: d19f7a3e8b62
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3a6f4b9c281"
down_revision: Union[str, Sequence[str], None] = "d19f7a3e8b62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = [
    (
        "system_settings.read",
        "Просмотр системных настроек",
        "Просмотр каталога и не секретных значений системных настроек.",
        "system_settings",
    ),
    (
        "system_settings.manage",
        "Управление системными настройками",
        "Изменение системных настроек в соответствии с approval-политикой.",
        "system_settings",
    ),
]

SETTINGS = [
    ("missions.max_active_solo", 1, "integer", "missions", "Лимит активных solo-миссий", "Максимальное число одновременно активных solo-миссий игрока.", False),
    ("missions.max_active_team", 1, "integer", "missions", "Лимит активных team-миссий", "Максимальное число одновременно активных team-миссий игрока.", False),
    ("missions.max_active_global", 1, "integer", "missions", "Лимит активных global-миссий", "Максимальное число одновременно активных global-миссий игрока.", False),
    ("missions.default_max_attempts", 3, "integer", "missions", "Число попыток по умолчанию", "Число попыток для новых миссий без индивидуальной настройки.", False),
    ("missions.default_attempt_reward_multipliers", [1.0, 0.5, 0.25], "json", "missions", "Множители награды за попытки", "Множители награды для последовательных попыток миссии.", False),
    ("approvals.default_expiry_seconds", 86400, "integer", "approvals", "Срок заявки по умолчанию", "Срок действия новых approval-заявок в секундах.", True),
    ("economy.transfer_minimum_earned_root", 50, "integer", "economy", "Порог заработанного ROOT для переводов", "Подтверждённый выигрыш ROOT, требуемый для доступа к переводам.", True),
    ("economy.transfer_min_amount", 1, "integer", "economy", "Минимальная сумма перевода", "Минимальная сумма внутреннего перевода ROOT.", True),
    ("economy.transfer_max_amount", 10000, "integer", "economy", "Максимальная сумма перевода", "Максимальная сумма одного внутреннего перевода ROOT.", True),
    ("economy.daily_transfer_limit", 50000, "integer", "economy", "Дневной лимит переводов", "Максимальная сумма внутренних переводов ROOT за сутки.", True),
    ("economy.manual_adjustment_approval_threshold", 1000, "integer", "economy", "Порог approval для ручной корректировки", "Сумма ROOT, с которой ручная корректировка требует approval.", True),
    ("features.demo_seed_enabled", False, "boolean", "features", "Demo seed enabled", "Зарезервированный флаг для ручного development demo seed.", True),
    ("features.demo_reset_enabled", False, "boolean", "features", "Demo reset enabled", "Зарезервированный флаг; публичный demo reset будет удалён отдельно.", True),
]


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False),
        sa.Column("value_type", sa.String(length=32), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_by_admin_id", sa.String(length=64), nullable=True),
        sa.Column("updated_by_admin_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["created_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("key"),
    )
    op.create_index("ix_system_settings_status", "system_settings", ["status"], unique=False)
    op.create_index("ix_system_settings_created_by_admin_id", "system_settings", ["created_by_admin_id"], unique=False)
    op.create_index("ix_system_settings_updated_by_admin_id", "system_settings", ["updated_by_admin_id"], unique=False)

    permission_table = sa.table(
        "admin_permissions",
        sa.column("code", sa.String()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("category", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "code": code,
                "title": title,
                "description": description,
                "category": category,
                "is_active": True,
            }
            for code, title, description, category in PERMISSIONS
        ],
    )

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
    op.bulk_insert(
        settings_table,
        [
            {
                "key": key,
                "value_json": value,
                "value_type": value_type,
                "category": category,
                "title": title,
                "description": description,
                "is_sensitive": sensitive,
                "status": "active",
            }
            for key, value, value_type, category, title, description, sensitive in SETTINGS
        ],
    )


def downgrade() -> None:
    op.drop_table("system_settings")
    op.execute(
        sa.text(
            "DELETE FROM admin_permissions "
            "WHERE code IN ('system_settings.read', 'system_settings.manage')"
        )
    )
