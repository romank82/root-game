"""add attempt_deadline_at to player_missions

Revision ID: dcc8fb912a89
Revises: a7e4c1d9b830
Create Date: 2026-11-08

Sprint 8.x-attempt-deadline (шаг 3A-1): серверный дедлайн на ОДНУ попытку
мини-игры.

Зачем: клиентский таймер попытки (MinigameProfile.settings.timeLimitSeconds →
CipherGame/MemoryGame) целиком живёт на фронте, поэтому кнопка «ЗАНОВО» и
повторный вход в экран перезапускали отсчёт без обращения к серверу — игрок
получал неограниченное время внутри одной попытки (attempt_count не растёт,
попытки не сгорают). Новое поле хранит абсолютный момент окончания текущей
попытки; проверка в submit и выдача нового дедлайна при провале — шаг 3A-2
(backend/app/mission_engine.py, отдельная правка).

Колонка nullable: у legacy-миссий и у миссий без лимита в MinigameProfile
таймера попытки нет (NULL = без ограничения), существующее поведение не
меняется; backfill не нужен.

Пустая nullable-колонка добавляется простым op.add_column: ALTER TABLE ADD
COLUMN без server_default поддержан и SQLite, и PostgreSQL, пересборка
таблицы (batch_alter_table) не требуется. Тот же приём уже применён в этой
таблице для cancel_deadline_at (f9a4c27e3d18) и entry_count (a444d52459f9).

Только DDL: данные не читаются и не изменяются.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'dcc8fb912a89'
down_revision: Union[str, Sequence[str], None] = 'a7e4c1d9b830'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить nullable attempt_deadline_at (дедлайн текущей попытки)."""
    op.add_column(
        "player_missions",
        sa.Column(
            "attempt_deadline_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    raise NotImplementedError("Schema extension; downgrade not supported.")
