"""add TeamSession wave fields

Sprint 8.x-2a: add TeamSession wave fields.

Только схема — логика волн командной мини-игры реализуется отдельно (8.x-2b+).
Поля добавляются с server_default для обратной совместимости с существующими
строками team_sessions (append-only, CheckConstraint намеренно нет).

Revision ID: c8a4e2b6f9d3
Revises: f9a4c27e3d18
Create Date: 2026-10-29 10:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8a4e2b6f9d3'
down_revision: Union[str, Sequence[str], None] = 'f9a4c27e3d18'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить 5 wave-полей в team_sessions.

    SQLite: DDL через batch_alter_table (rebuild с копированием данных).
    PostgreSQL: batch — обычный ALTER ADD COLUMN.
    JSON default dialect-aware: SQLite хранит JSON как текст (DEFAULT '[]'),
    PostgreSQL требует каст '[]'::json.
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        played_members_default = sa.text("'[]'::json")
    else:
        played_members_default = sa.text("'[]'")

    with op.batch_alter_table("team_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "current_wave",
                sa.Integer(),
                nullable=False,
                server_default="1",
            )
        )
        batch_op.add_column(
            sa.Column(
                "max_waves",
                sa.Integer(),
                nullable=False,
                server_default="3",
            )
        )
        batch_op.add_column(
            sa.Column(
                "wave_status",
                sa.String(length=16),
                nullable=False,
                server_default="playing",
            )
        )
        batch_op.add_column(
            sa.Column(
                "wave_played_members",
                sa.JSON(),
                nullable=False,
                server_default=played_members_default,
            )
        )
        batch_op.add_column(
            sa.Column(
                "current_cipher_session",
                sa.JSON(),
                nullable=True,
            )
        )


def downgrade() -> None:
    """Откатить: удалить 5 wave-полей.

    Dialect-aware: PostgreSQL поддерживает DROP COLUMN через ALTER;
    SQLite — через batch_alter_table (пересоздание таблицы).
    """
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_column("team_sessions", "current_cipher_session")
        op.drop_column("team_sessions", "wave_played_members")
        op.drop_column("team_sessions", "wave_status")
        op.drop_column("team_sessions", "max_waves")
        op.drop_column("team_sessions", "current_wave")
    else:
        with op.batch_alter_table("team_sessions") as batch_op:
            batch_op.drop_column("current_cipher_session")
            batch_op.drop_column("wave_played_members")
            batch_op.drop_column("wave_status")
            batch_op.drop_column("max_waves")
            batch_op.drop_column("current_wave")
