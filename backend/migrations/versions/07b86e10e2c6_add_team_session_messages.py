"""add team_session_messages (чат командной сессии, 6.6-a)

Revision ID: 07b86e10e2c6
Revises: dde2038a44d9
Create Date: 2026-10-31 12:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '07b86e10e2c6'
down_revision: Union[str, Sequence[str], None] = 'dde2038a44d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицу чата командной сессии.

    create_table работает одинаково на SQLite и PostgreSQL
    (dialect-aware не требуется). RESTRICT на FK — как у
    team_session_members: физическое удаление игровых сущностей
    запрещено, сессии не удаляются.
    """
    op.create_table(
        'team_session_messages',
        sa.Column('id', sa.String(length=64), nullable=False),
        sa.Column('team_session_id', sa.String(length=64), nullable=False),
        sa.Column('player_id', sa.String(length=64), nullable=False),
        sa.Column('text', sa.String(length=1000), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('visible', 'hidden')",
            name='ck_team_session_messages_status',
        ),
        sa.ForeignKeyConstraint(
            ['team_session_id'], ['team_sessions.id'], ondelete='RESTRICT'
        ),
        sa.ForeignKeyConstraint(['player_id'], ['game_players.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_team_session_messages_team_session_id'),
        'team_session_messages',
        ['team_session_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_team_session_messages_player_id'),
        'team_session_messages',
        ['player_id'],
        unique=False,
    )
    op.create_index(
        'ix_team_session_messages_session_created',
        'team_session_messages',
        ['team_session_id', 'created_at'],
        unique=False,
    )


def downgrade() -> None:
    """Симметричный откат: удалить таблицу и её индексы.

    Это structural-миграция новой (пустой) таблицы: drop_table
    диалект-независим. Не data-миграция — историю/ledger не трогает.
    """
    op.drop_index(
        'ix_team_session_messages_session_created', table_name='team_session_messages'
    )
    op.drop_index(
        op.f('ix_team_session_messages_player_id'), table_name='team_session_messages'
    )
    op.drop_index(
        op.f('ix_team_session_messages_team_session_id'),
        table_name='team_session_messages',
    )
    op.drop_table('team_session_messages')
