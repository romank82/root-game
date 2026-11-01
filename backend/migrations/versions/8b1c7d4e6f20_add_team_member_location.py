"""add join location fields to team_session_members

Sprint 8.x-4-join-proximity: при create/join запрашивается GPS игрока.
В team_session_members сохраняются координаты на момент вступления,
определённая по ним страна (geo_intel_offline) и ближайший город
(reverse_geocoder). По этим данным до списания entry fee проверяются
правила «одна страна» и «рядом (≤ 50 км до всех участников)».

Append-only: все поля nullable без server_default — старые строки и
сессии, созданные без GPS (legacy team-accept путь), получают NULL.

Revision ID: 8b1c7d4e6f20
Revises: 07b86e10e2c6
Create Date: 2026-11-01 16:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b1c7d4e6f20'
down_revision: Union[str, Sequence[str], None] = '07b86e10e2c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("join_latitude", sa.Float()),
    ("join_longitude", sa.Float()),
    ("join_country", sa.String(length=2)),
    ("join_city", sa.String(length=128)),
    ("join_location_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    """Добавить join_* (nullable) в team_session_members.

    Dialect-aware: PostgreSQL — plain ALTER ADD COLUMN; SQLite — batch
    (пересоздание таблицы с копированием данных, как в d4f0a1b2c3e7).
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name, column_type in _COLUMNS:
            op.add_column(
                "team_session_members",
                sa.Column(name, column_type, nullable=True),
            )
    else:
        with op.batch_alter_table("team_session_members") as batch_op:
            for name, column_type in _COLUMNS:
                batch_op.add_column(
                    sa.Column(name, column_type, nullable=True)
                )


def downgrade() -> None:
    """Откатить: удалить join_* (append-only, данные не восстанавливаются)."""
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for name, _ in _COLUMNS:
            op.drop_column("team_session_members", name)
    else:
        with op.batch_alter_table("team_session_members") as batch_op:
            for name, _ in _COLUMNS:
                batch_op.drop_column(name)
