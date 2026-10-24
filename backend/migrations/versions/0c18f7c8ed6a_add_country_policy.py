"""add country_policies

CountryPolicy (13.1): политики по странам для модерации.
Применение — в 13.2 (CRUD + проверки в auth/функционале); сейчас —
только структура.

- одна запись на страну: country_code String(2) ISO-2, уникальность —
  UniqueConstraint uq_country_policies_country_code (имя совпадает
  с моделью в PG и SQLite).
- policy: allowed (default, всё разрешено) | restricted (вход можно,
  функционал из restricted_features — нельзя) | blocked (вход нельзя).
  CheckConstraint ck_country_policies_policy.
- restricted_features JSON nullable: список 'transfer'/'mission'/'team';
  NULL/пусто = ничего не ограничено (семантика — в 13.2).
- reason String(255) nullable — комментарий оператора.
- ISO-2 валидация — на бэке (13.2), не в модели (по образцу country
  в GamePlayer).
- created_at/updated_at — server_default=now() (как TimestampMixin).
- отдельный индекс ix_country_policies_country_code для фильтров
  (помимо unique-constraint) — как просит спецификация 13.1.

Revision ID: 0c18f7c8ed6a
Revises: 39b50b607533
Create Date: 2026-10-24 13:53:44.258960

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0c18f7c8ed6a'
down_revision: Union[str, Sequence[str], None] = '39b50b607533'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Создать таблицу country_policies (13.1)."""
    op.create_table(
        "country_policies",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column(
            "policy",
            sa.String(length=16),
            nullable=False,
            server_default="allowed",
        ),
        sa.Column("restricted_features", sa.JSON(), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=True),
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
        sa.UniqueConstraint(
            "country_code",
            name="uq_country_policies_country_code",
        ),
        sa.CheckConstraint(
            "policy IN ('allowed','restricted','blocked')",
            name="ck_country_policies_policy",
        ),
    )
    op.create_index(
        "ix_country_policies_country_code",
        "country_policies",
        ["country_code"],
    )


def downgrade() -> None:
    """Downgrade не поддерживается (структурная миграция).

    Проект использует политику immutable-миграций: откат только через
    проверенный backup базы данных.
    """
    raise NotImplementedError(
        "Downgrade не поддерживается. Откат только через backup базы данных."
    )
