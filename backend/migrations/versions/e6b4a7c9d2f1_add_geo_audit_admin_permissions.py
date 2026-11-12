"""add geo_audit admin permissions

Sprint 8.9.e-5: отдельные права для раздела «Гео-аудит» (флаги античита).
geo_audit.read — просмотр списка/карточки флагов и истории review;
geo_audit.manage — снятие/подтверждение флагов (anticheat.review).

До 8.9.e-6 раздел был защищён v1-правами players.read/players.manage;
после переключения констант GEO_AUDIT_* на geo_audit.* эти записи обязаны
существовать в admin_permissions, иначе require_permission вернёт 403 для
всех не-супер-админов (admin_access.get_permission_execution_mode требует
активную запись каталога).

Идемпотентная append-only data-миграция (select-then-insert, как
b8f2c4d6e9a1): каждая запись вставляется только если code ещё нет — повторная
накатка безопасна (op.bulk_insert упал бы на PK при ручных строках на dev).
Только SQLAlchemy Core (sa.table + select/insert), без диалект-специфичного
SQL — работает и на SQLite, и на PostgreSQL. created_at/updated_at заполняются
TimestampMixin server default.

Revision ID: e6b4a7c9d2f1
Revises: d4e7a1c93b52
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e6b4a7c9d2f1"
down_revision: Union[str, Sequence[str], None] = "d4e7a1c93b52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (code, title, description, category, is_active)
PERMISSIONS = (
    (
        "geo_audit.read",
        "Просмотр гео-аудита",
        "Просмотр флагов античита и истории review.",
        "geo",
        True,
    ),
    (
        "geo_audit.manage",
        "Рассмотрение флагов гео-аудита",
        "Снятие или подтверждение флагов античита (anticheat.review).",
        "geo",
        True,
    ),
)


def upgrade() -> None:
    """Идемпотентно добавить 2 права geo_audit.* (append-only)."""
    bind = op.get_bind()

    permission_table = sa.table(
        "admin_permissions",
        sa.column("code", sa.String()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("category", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )

    for code, title, description, category, is_active in PERMISSIONS:
        existing = bind.execute(
            sa.select(permission_table.c.code).where(
                permission_table.c.code == code
            )
        ).first()
        if existing is not None:
            continue

        bind.execute(
            permission_table.insert().values(
                code=code,
                title=title,
                description=description,
                category=category,
                is_active=is_active,
            )
        )


def downgrade() -> None:
    """Deliberately not implemented: permissions catalog is append-only."""
    raise NotImplementedError(
        "Admin permissions data migrations cannot be downgraded (append-only)."
    )