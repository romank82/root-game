"""add minigame_profiles + fk in missions

Revision ID: 2c14ba97fae3
Revises: fedd12aa7b3e
Create Date: 2026-10-18 09:13:17.570850

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2c14ba97fae3'
down_revision: Union[str, Sequence[str], None] = 'fedd12aa7b3e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Sprint 8.17 шаг 2: таблица minigame_profiles + опциональный FK
    missions.minigame_profile_id (SET NULL).

    Имена индексов — дефолтные SQLAlchemy (ix_<table>_<column>), имя FK —
    явное, в стиле 30116c3d9ae6 (fk_missions_geo_zone_id). batch_alter_table
    даёт dialect-aware DDL для SQLite (пересоздание таблицы) и PostgreSQL.
    """
    op.create_table(
        "minigame_profiles",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("game_type", sa.String(length=64), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_minigame_profiles_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index(
        op.f("ix_minigame_profiles_game_type"),
        "minigame_profiles",
        ["game_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_minigame_profiles_status"),
        "minigame_profiles",
        ["status"],
        unique=False,
    )

    with op.batch_alter_table("missions") as batch_op:
        batch_op.add_column(
            sa.Column("minigame_profile_id", sa.String(length=64), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_missions_minigame_profile_id",
            "minigame_profiles",
            ["minigame_profile_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_missions_minigame_profile_id", ["minigame_profile_id"]
        )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных. См. AGENTS.md и head-миграции
    (30116c3d9ae6, a1d2aafc3d3b, 0b9e7c6d5a41).
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
