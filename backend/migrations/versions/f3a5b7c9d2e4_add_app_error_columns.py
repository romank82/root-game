"""add app error columns

Sprint M-2b: расширение app_errors (13.4) колонками endpoint,
status_code, player_id, stack — структурированный поиск ошибок
(M-3 аналитика) без парсинга safe_context JSON.

- endpoint String(512) nullable, index ix_app_errors_endpoint — путь
  запроса (без query); вынесен из safe_context в отдельную колонку.
- status_code Integer nullable — HTTP-статус (500 в middleware).
- player_id String(64) nullable, index ix_app_errors_player_id —
  БЕЗ FK (immutable-журнал; ошибки возможны до/без авторизации).
  Заполнение — отдельным шагом M-2c (player_id = None сейчас).
- stack Text nullable — traceback.format_exc()[:4000] (обрезка,
  чтобы не раздувать журнал).
- Индексы: ix_app_errors_error_type (группировка по типу ошибки),
  ix_app_errors_created_at (retention/выборка по времени).
- created_at индекс — ТОЛЬКО для app_errors (op.create_index),
  TimestampMixin не трогается (общий для всех моделей).

Append-only: только add_column + create_index, все колонки nullable
(старые строки остаются NULL), существующие строки НЕ изменяются.
batch_alter_table — dialect-aware (SQLite пересоздание, PG plain
ALTER), безопасно для обоих окружений (локальный dev и Docker PG).

Revision ID: f3a5b7c9d2e4
Revises: 8b1c7d4e6f20
Create Date: 2026-11-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3a5b7c9d2e4'
down_revision: Union[str, Sequence[str], None] = '8b1c7d4e6f20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить 4 nullable-колонки + 4 индекса (append-only)."""
    with op.batch_alter_table("app_errors") as batch_op:
        batch_op.add_column(
            sa.Column("endpoint", sa.String(length=512), nullable=True)
        )
        batch_op.add_column(
            sa.Column("status_code", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("player_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(sa.Column("stack", sa.Text(), nullable=True))
        batch_op.create_index("ix_app_errors_endpoint", ["endpoint"])
        batch_op.create_index("ix_app_errors_player_id", ["player_id"])
        batch_op.create_index("ix_app_errors_error_type", ["error_type"])
        batch_op.create_index("ix_app_errors_created_at", ["created_at"])


def downgrade() -> None:
    """Downgrade не поддерживается (immutable-журнал).

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
