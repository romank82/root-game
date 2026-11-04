"""add mission translations

Sprint Trans-2a: поля ручного перевода контента миссии.

- missions.translations — JSON-карта переводов по языкам (nullable, default NULL).
  Формат и валидацию вводит API-слой в Trans-2b; текущие роуты поле не читают
  и не пишут, поэтому nullable без server_default — обратная совместимость
  полная, существующие строки не меняются.
- missions.translation_status — статус перевода (none/partial/complete),
  nullable со server_default 'none' (существующие строки сразу получают 'none',
  а старый код, который ничего не знает о поле, ничего не ломает).

Миграция append-only и dialect-aware: обычный ADD COLUMN с константным
server_default корректно работает и на SQLite, и на PostgreSQL. batch_alter_table
используется как универсальный безопасный способ добавления колонок (на SQLite
это data-preserving rebuild таблицы, на PG — прямой ALTER TABLE). Данные не
переписываются; downgrade намеренно не реализован.

Revision ID: c5d8e2f14a7b
Revises: a7c9e1f3b5d2
Create Date: 2026-11-04

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c5d8e2f14a7b"
down_revision: Union[str, Sequence[str], None] = "a7c9e1f3b5d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Добавить translations и translation_status (append-only, nullable)."""
    with op.batch_alter_table("missions") as batch_op:
        batch_op.add_column(
            sa.Column("translations", sa.JSON(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "translation_status",
                sa.String(length=16),
                nullable=True,
                server_default="none",
            )
        )


def downgrade() -> None:
    """Deliberately not implemented: mission translation columns are append-only."""
    raise NotImplementedError(
        "Mission translation columns cannot be dropped (append-only migration)."
    )
