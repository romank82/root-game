"""add Telegram player fields

Revision ID: 9d7a12b8c541
Revises: 68c404c6ace4
Create Date: 2026-09-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9d7a12b8c541"
down_revision: Union[str, Sequence[str], None] = "68c404c6ace4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "game_players",
        sa.Column("telegram_username", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "game_players",
        sa.Column(
            "telegram_username_normalized",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "game_players",
        sa.Column("telegram_first_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "game_players",
        sa.Column("telegram_last_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "game_players",
        sa.Column("telegram_photo_url", sa.String(length=2048), nullable=True),
    )

    # Username may be NULL, because Telegram users are not required to have one.
    # A non-NULL username can belong to only one active game profile.
    op.create_index(
        "uq_game_players_telegram_username_normalized",
        "game_players",
        ["telegram_username_normalized"],
        unique=True,
        postgresql_where=sa.text("telegram_username_normalized IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_game_players_telegram_username_normalized",
        table_name="game_players",
    )
    op.drop_column("game_players", "telegram_photo_url")
    op.drop_column("game_players", "telegram_last_name")
    op.drop_column("game_players", "telegram_first_name")
    op.drop_column("game_players", "telegram_username_normalized")
    op.drop_column("game_players", "telegram_username")
