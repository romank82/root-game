"""add referral_rewards + game_players.referred_by_player_id

Revision ID: c3d9a71f4b62
Revises: d8b3f5c72a91
Create Date: 2026-11-06

Sprint Referral R-1: только схема реферальной программы (механика, CMS и
начисление — R-2…R-6).

- game_players.referred_by_player_id — nullable FK на game_players.id
  (ondelete RESTRICT): кто пригласил игрока. Backfill не делаем — игроки до
  фичи остаются NULL (как country_source/last_seen_at в 1dd561da2c34 и
  39b50b607533). Индекс ix_game_players_referred_by_player_id — под выборки
  «кого привёл игрок»/«есть ли реферер».

- referral_rewards — immutable-история наград: одна пара
  «пригласивший → приглашённый», amount_root фиксируется в момент создания
  записи (значение CMS referral.reward_root на тот момент).
  * uq_referral_rewards_referred — один приглашённый игрок = одна запись;
  * ck_referral_rewards_self — нельзя пригласить самого себя;
  * ck_referral_rewards_amount_positive — amount_root строго > 0;
  * ck_referral_rewards_status — 'pending' | 'credited' | 'cancelled';
  * ondelete RESTRICT у обоих FK на game_players.id — история приглашений
    не пропадает при удалении игрока.

Имена индексов — дефолтные SQLAlchemy (ix_<table>_<column>), имена FK —
явные, в стиле 74d3bb612729 (fk_player_transfers_*) и 2c14ba97fae3.
batch_alter_table даёт dialect-aware DDL: на PostgreSQL — обычный ALTER
TABLE, на SQLite — пересоздание таблицы с копированием данных (в SQLite
ADD CONSTRAINT/FK иначе невозможны). Миграции Alembic исполняются engine'ом
из migrations/env.py, а не app.db.engine, поэтому PRAGMA foreign_keys на
соединении миграции остаётся OFF — rebuild game_players не каскадит по
ссылающимся таблицам.

downgrade не реализован: политика immutable-миграций, откат — только через
проверенный backup (backend/chimera.pre-referral.db).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d9a71f4b62'
down_revision: Union[str, Sequence[str], None] = 'd8b3f5c72a91'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить game_players.referred_by_player_id и таблицу referral_rewards."""
    with op.batch_alter_table("game_players") as batch_op:
        batch_op.add_column(
            sa.Column(
                "referred_by_player_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.create_index(
            "ix_game_players_referred_by_player_id",
            ["referred_by_player_id"],
        )
        batch_op.create_foreign_key(
            "fk_game_players_referred_by",
            "game_players",
            ["referred_by_player_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("referrer_player_id", sa.String(length=64), nullable=False),
        sa.Column("referred_player_id", sa.String(length=64), nullable=False),
        sa.Column("amount_root", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="pending",
            nullable=False,
        ),
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
            ["referrer_player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
            name="fk_referral_rewards_referrer",
        ),
        sa.ForeignKeyConstraint(
            ["referred_player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
            name="fk_referral_rewards_referred",
        ),
        sa.UniqueConstraint(
            "referred_player_id",
            name="uq_referral_rewards_referred",
        ),
        sa.CheckConstraint(
            "amount_root > 0",
            name="ck_referral_rewards_amount_positive",
        ),
        sa.CheckConstraint(
            "status IN ('pending','credited','cancelled')",
            name="ck_referral_rewards_status",
        ),
        sa.CheckConstraint(
            "referrer_player_id <> referred_player_id",
            name="ck_referral_rewards_self",
        ),
    )
    # Дефолтные имена индексов SQLAlchemy (index=True в модели) — чтобы схема
    # Alembic совпадала с Base.metadata.create_all (тесты).
    op.create_index(
        "ix_referral_rewards_referrer_player_id",
        "referral_rewards",
        ["referrer_player_id"],
    )
    op.create_index(
        "ix_referral_rewards_referred_player_id",
        "referral_rewards",
        ["referred_player_id"],
    )
    op.create_index(
        "ix_referral_rewards_status",
        "referral_rewards",
        ["status"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается.

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных (backend/chimera.pre-referral.db).
    Физическое удаление данных реферальной истории запрещено.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
