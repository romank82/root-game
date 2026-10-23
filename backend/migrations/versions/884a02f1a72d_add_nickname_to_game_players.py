"""add nickname to game_players

Ник игрока (roadmap 10.0, часть 1): уникальный читаемый латинский адрес
(формат основа#123-456-789) — для переводов (Этап 10) и поиска (10.0.1).

Дизайн согласован с модельным слоем: две колонки
- nickname       — как есть (витрина, формат base#123-456-789);
- nickname_lower — lowercase-копия для case-insensitive uniqueness/search
  (латиница: lower() идентичен на SQLite и PostgreSQL).

Колонки nullable: генерация при регистрации (main.py, 34-B2) + backfill
существующих записей в этой миграции. Partial unique index
uq_game_players_nickname_lower (IS NOT NULL на обоих диалектах) — NULL-ы
(игроки без ника) не конфликтуют.

Revision ID: 884a02f1a72d
Revises: ec7a5b3f1984
Create Date: 2026-10-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.slug_utils import generate_nickname


# revision identifiers, used by Alembic.
revision: str = "884a02f1a72d"
down_revision: Union[str, Sequence[str], None] = "ec7a5b3f1984"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _nickname_taken(bind, nickname_lower: str) -> bool:
    """Занят ли ник (по nickname_lower) в текущей транзакции миграции."""
    row = bind.execute(
        sa.text(
            "SELECT 1 FROM game_players "
            "WHERE nickname_lower = :nickname_lower LIMIT 1"
        ),
        {"nickname_lower": nickname_lower},
    ).first()
    return row is not None


def upgrade() -> None:
    """Добавить колонки nickname/nickname_lower + backfill + unique index.

    Backfill генерирует ники для ВСЕХ существующих записей (demo-player,
    реальных Telegram-игроков, тестовых) через generate_nickname():
    транслит display_name (при NULL — base "player") + суффикс #123-456-789.
    При коллизии суффикс перегенерируется; обновление — в той же
    транзакции, что и последующий create_index, поэтому дублей не будет.
    """
    op.add_column(
        "game_players",
        sa.Column("nickname", sa.String(64), nullable=True),
    )
    op.add_column(
        "game_players",
        sa.Column("nickname_lower", sa.String(64), nullable=True),
    )

    bind = op.get_bind()

    rows = bind.execute(
        sa.text(
            "SELECT id, display_name FROM game_players ORDER BY id"
        )
    ).mappings().all()

    for row in rows:
        base = row["display_name"] or "player"

        # is_taken проверяет текущее состояние БД внутри той же транзакции:
        # уже сгенерированные ники (этой миграцией) видны следующим SELECT'ам.
        nickname = generate_nickname(base, lambda candidate: _nickname_taken(
            bind, candidate
        ))

        bind.execute(
            sa.text(
                "UPDATE game_players "
                "SET nickname = :nickname, nickname_lower = :nickname_lower "
                "WHERE id = :id"
            ),
            {
                "nickname": nickname,
                "nickname_lower": nickname.lower(),
                "id": row["id"],
            },
        )

    op.create_index(
        "uq_game_players_nickname_lower",
        "game_players",
        ["nickname_lower"],
        unique=True,
        postgresql_where=sa.text("nickname_lower IS NOT NULL"),
        sqlite_where=sa.text("nickname_lower IS NOT NULL"),
    )


def downgrade() -> None:
    """Откат: снять unique index и удалить колонки ника.

    Данные ника теряются (это обратимый backfill-артефакт, не игровая
    история): колонки были добавлены этой миграцией.
    """
    op.drop_index("uq_game_players_nickname_lower", table_name="game_players")
    op.drop_column("game_players", "nickname_lower")
    op.drop_column("game_players", "nickname")