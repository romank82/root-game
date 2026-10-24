"""add_app_error

AppError (13.4): сбор ошибок приложения (5xx) с correlation_id,
severity, error_type, message и safe_context (без секретов).
Сейчас — только структура + хелпер записи; middleware-перехват 5xx
в main.py — отдельным шагом 13.4-b.

- id String(64) PK, генерация как 'app-error-<uuid4-hex>' (как в проекте).
- correlation_id String(64) NOT NULL — сквозной id из
  request.state.audit_context (как в AdminAuditLog / PlayerEvent).
  Индекс ix_app_errors_correlation_id — выборка «все ошибки запроса».
- severity String(16) NOT NULL + CheckConstraint 'error'|'critical' —
  словарь уровней задан в БД. Индекс ix_app_errors_severity.
- error_type String(128) NOT NULL — имя класса исключения.
- message String(512) NOT NULL — краткое сообщение БЕЗ stack trace.
- safe_context JSON nullable — безопасный контекст (path, method,
  status, user_id); ЗАПРЕЩЕНЫ секреты (redact — вызывающий, 13.4-b).
- created_at/updated_at — server_default=now() (как TimestampMixin).
- Retention 30 дней — отдельным шагом (cron), не здесь.

Revision ID: 50178ee857c8
Revises: 6b6ae360eebc
Create Date: 2026-10-24 15:32:15.482344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50178ee857c8'
down_revision: Union[str, Sequence[str], None] = '6b6ae360eebc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицу app_errors (13.4)."""
    op.create_table(
        "app_errors",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("error_type", sa.String(length=128), nullable=False),
        sa.Column("message", sa.String(length=512), nullable=False),
        sa.Column("safe_context", sa.JSON(), nullable=True),
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
        sa.CheckConstraint(
            "severity IN ('error','critical')",
            name="ck_app_errors_severity",
        ),
    )
    op.create_index(
        "ix_app_errors_correlation_id",
        "app_errors",
        ["correlation_id"],
    )
    op.create_index(
        "ix_app_errors_severity",
        "app_errors",
        ["severity"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается (immutable-журнал).

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
