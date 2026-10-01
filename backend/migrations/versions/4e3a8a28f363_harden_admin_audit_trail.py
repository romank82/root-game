"""harden admin audit trail

Revision ID: 4e3a8a28f363
Revises: f7b2c9d4e613
Create Date: 2026-09-24 10:33:12.341175
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "4e3a8a28f363"
down_revision: Union[str, Sequence[str], None] = "f7b2c9d4e613"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_immutable_triggers(dialect_name: str) -> None:
    """Protect audit history after legacy-row backfill is complete."""
    if dialect_name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_admin_audit_log_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'admin_audit_log is immutable'
                    USING ERRCODE = '55000';
                RETURN NULL;
            END;
            $$;
            """
        )
        op.execute(
            """
            CREATE TRIGGER admin_audit_log_no_update
            BEFORE UPDATE ON admin_audit_log
            FOR EACH ROW
            EXECUTE FUNCTION prevent_admin_audit_log_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER admin_audit_log_no_delete
            BEFORE DELETE ON admin_audit_log
            FOR EACH ROW
            EXECUTE FUNCTION prevent_admin_audit_log_mutation();
            """
        )
        return

    if dialect_name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER admin_audit_log_no_update
            BEFORE UPDATE ON admin_audit_log
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'admin_audit_log is immutable');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER admin_audit_log_no_delete
            BEFORE DELETE ON admin_audit_log
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'admin_audit_log is immutable');
            END;
            """
        )
        return

    raise RuntimeError(
        f"Unsupported database dialect for audit immutability: {dialect_name}"
    )


def _drop_immutable_triggers(dialect_name: str) -> None:
    op.execute("DROP TRIGGER IF EXISTS admin_audit_log_no_delete;")
    op.execute("DROP TRIGGER IF EXISTS admin_audit_log_no_update;")

    if dialect_name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS prevent_admin_audit_log_mutation();")


def upgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    error_context_default = (
        sa.text("'{}'::json")
        if dialect_name == "postgresql"
        else sa.text("'{}'")
    )

    # Legacy rows must be backfilled before correlation_id becomes NOT NULL.
    op.add_column(
        "admin_audit_log",
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "admin_audit_log",
        sa.Column("admin_username_snapshot", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "admin_audit_log",
        sa.Column("user_agent", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "admin_audit_log",
        sa.Column(
            "error_context_json",
            sa.JSON(),
            nullable=False,
            server_default=error_context_default,
        ),
    )

    # Keep pre-migration history traceable without inventing request identifiers.
    op.execute(
        """
        UPDATE admin_audit_log
        SET correlation_id = 'legacy:' || id
        WHERE correlation_id IS NULL
        """
    )

    # Snapshot current username only if the original actor still exists.
    # This correlated form is compatible with PostgreSQL and SQLite.
    op.execute(
        """
        UPDATE admin_audit_log
        SET admin_username_snapshot = (
            SELECT admin.username
            FROM admin_users AS admin
            WHERE admin.id = admin_audit_log.admin_user_id
        )
        WHERE admin_username_snapshot IS NULL
          AND EXISTS (
              SELECT 1
              FROM admin_users AS admin
              WHERE admin.id = admin_audit_log.admin_user_id
          )
        """
    )

    # batch_alter_table is required by SQLite and remains safe on PostgreSQL.
    with op.batch_alter_table("admin_audit_log") as batch_op:
        batch_op.alter_column(
            "correlation_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )

    op.create_index(
        "ix_admin_audit_log_correlation_id",
        "admin_audit_log",
        ["correlation_id"],
        unique=False,
    )

    # INSERT remains allowed. Application-level UPDATE/DELETE is forbidden.
    _create_immutable_triggers(dialect_name)


def downgrade() -> None:
    dialect_name = op.get_bind().dialect.name
    _drop_immutable_triggers(dialect_name)

    op.drop_index("ix_admin_audit_log_correlation_id", table_name="admin_audit_log")
    op.drop_column("admin_audit_log", "error_context_json")
    op.drop_column("admin_audit_log", "user_agent")
    op.drop_column("admin_audit_log", "admin_username_snapshot")
    op.drop_column("admin_audit_log", "correlation_id")
