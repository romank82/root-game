"""add player_events

PlayerEvent (13.3): журнал действий игроков для модерации/антифрода/
аналитики. Сейчас — только структура + хелпер записи; вызовы в точках
входа (auth/mission/transfer/gas) — отдельным шагом 13.3-b.

- id String(64) PK, генерация as uuid4-hex (как в проекте).
- player_id FK game_players.id ON DELETE RESTRICT — событие без игрока
  невозможно; RESTRICT запрещает удаление игрока с событиями (immutable).
  Индекс ix_player_events_player_id — фильтры «все действия игрока».
- event_type String(64) NOT NULL — строковый тип события ('auth.login',
  'mission.accepted', 'mission.completed', 'transfer.completed',
  'gas.purchased'); словарь и валидация — на вызывающей стороне (13.3-b),
  не в БД. Индекс ix_player_events_event_type.
- payload_json JSON nullable — безопасный контекст события (redacted);
  в журнал запрещены секреты (см. security-and-audit).
- correlation_id String(64) nullable — связь события с ошибкой/заявкой.
  Индекс ix_player_events_correlation_id.
- created_at/updated_at — server_default=now() (как TimestampMixin).
- Retention 30 дней — отдельным шагом (cron), не здесь.

Revision ID: 6b6ae360eebc
Revises: 0c18f7c8ed6a
Create Date: 2026-10-24 16:12:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b6ae360eebc'
down_revision: Union[str, Sequence[str], None] = '0c18f7c8ed6a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицу player_events (13.3)."""
    op.create_table(
        "player_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
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
            ["player_id"],
            ["game_players.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_player_events_player_id",
        "player_events",
        ["player_id"],
    )
    op.create_index(
        "ix_player_events_event_type",
        "player_events",
        ["event_type"],
    )
    op.create_index(
        "ix_player_events_correlation_id",
        "player_events",
        ["correlation_id"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается (immutable-журнал).

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )