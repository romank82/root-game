"""add super-admin permissions and approval requests

Revision ID: b91a7c4d2e10
Revises: a4f2c9e8b731
Create Date: 2026-09-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b91a7c4d2e10"
down_revision: Union[str, Sequence[str], None] = "a4f2c9e8b731"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


PERMISSIONS = [
    (
        "admins.read",
        "Просмотр администраторов",
        "Просмотр списка и карточек администраторов.",
        "administration",
    ),
    (
        "admins.manage",
        "Управление администраторами",
        "Создание, изменение, деактивация и удаление администраторов.",
        "administration",
    ),
    (
        "admin_permissions.manage",
        "Управление полномочиями",
        "Выдача, изменение режима и отзыв индивидуальных полномочий.",
        "administration",
    ),
    (
        "admin_approvals.read",
        "Просмотр заявок",
        "Просмотр заявок, требующих одобрения супер-админа.",
        "administration",
    ),
    (
        "admin_approvals.review",
        "Рассмотрение заявок",
        "Одобрение или отклонение заявок администраторов.",
        "administration",
    ),
    (
        "audit.read",
        "Просмотр аудита",
        "Просмотр неизменяемого журнала административных действий.",
        "administration",
    ),
]


def upgrade() -> None:
    # Existing owner accounts keep their password and identity, but become
    # super-admins. This preserves access for roman_admin and any other owner.
    with op.batch_alter_table("admin_users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_super_admin",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "is_deleted",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column("created_by_admin_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("deactivation_reason", sa.Text(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_admin_users_created_by_admin_id",
            "admin_users",
            ["created_by_admin_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_admin_users_is_super_admin",
            ["is_super_admin"],
            unique=False,
        )
        batch_op.create_index(
            "ix_admin_users_is_deleted",
            ["is_deleted"],
            unique=False,
        )

    op.execute(
        sa.text(
            "UPDATE admin_users "
            "SET is_super_admin = TRUE, role = 'super_admin' "
            "WHERE role = 'owner'"
        )
    )

    op.create_table(
        "admin_permissions",
        sa.Column("code", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "category",
            sa.String(length=64),
            nullable=False,
            server_default="general",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("code"),
    )

    permission_table = sa.table(
        "admin_permissions",
        sa.column("code", sa.String()),
        sa.column("title", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("category", sa.String()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        permission_table,
        [
            {
                "code": code,
                "title": title,
                "description": description,
                "category": category,
                "is_active": True,
            }
            for code, title, description, category in PERMISSIONS
        ],
    )

    op.create_table(
        "admin_user_permissions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("admin_user_id", sa.String(length=64), nullable=False),
        sa.Column("permission_code", sa.String(length=128), nullable=False),
        sa.Column(
            "execution_mode",
            sa.String(length=64),
            nullable=False,
            server_default="direct",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("granted_by_admin_id", sa.String(length=64), nullable=True),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("revoked_by_admin_id", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"], ["admin_users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["permission_code"], ["admin_permissions.code"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "admin_user_id",
            "permission_code",
            name="uq_admin_user_permissions_user_permission",
        ),
    )
    op.create_index(
        "ix_admin_user_permissions_admin_user_id",
        "admin_user_permissions",
        ["admin_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_user_permissions_permission_code",
        "admin_user_permissions",
        ["permission_code"],
        unique=False,
    )
    op.create_index(
        "ix_admin_user_permissions_granted_by_admin_id",
        "admin_user_permissions",
        ["granted_by_admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_user_permissions_revoked_by_admin_id",
        "admin_user_permissions",
        ["revoked_by_admin_id"],
        unique=False,
    )

    op.create_table(
        "admin_approval_requests",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("requested_by_admin_id", sa.String(length=64), nullable=False),
        sa.Column("required_permission_code", sa.String(length=128), nullable=False),
        sa.Column("action_type", sa.String(length=128), nullable=False),
        sa.Column("target_entity_type", sa.String(length=64), nullable=False),
        sa.Column("target_entity_id", sa.String(length=64), nullable=True),
        sa.Column("payload_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("request_ip_address", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_admin_id", sa.String(length=64), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approval_comment", sa.Text(), nullable=True),
        sa.Column("rejected_by_admin_id", sa.String(length=64), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_comment", sa.Text(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "execution_result",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("execution_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_admin_id"], ["admin_users.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["required_permission_code"],
            ["admin_permissions.code"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["rejected_by_admin_id"], ["admin_users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_approval_requests_status",
        "admin_approval_requests",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_admin_approval_requests_requested_by_admin_id",
        "admin_approval_requests",
        ["requested_by_admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_approval_requests_required_permission_code",
        "admin_approval_requests",
        ["required_permission_code"],
        unique=False,
    )
    op.create_index(
        "ix_admin_approval_requests_action_type",
        "admin_approval_requests",
        ["action_type"],
        unique=False,
    )
    op.create_index(
        "ix_admin_approval_requests_request_id",
        "admin_approval_requests",
        ["request_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_approval_requests_expires_at",
        "admin_approval_requests",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_admin_approval_requests_approved_by_admin_id",
        "admin_approval_requests",
        ["approved_by_admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_approval_requests_rejected_by_admin_id",
        "admin_approval_requests",
        ["rejected_by_admin_id"],
        unique=False,
    )

    with op.batch_alter_table("admin_audit_log") as batch_op:
        batch_op.add_column(
            sa.Column("permission_code", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("approval_request_id", sa.String(length=64), nullable=True)
        )
        batch_op.add_column(
            sa.Column("request_id", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(sa.Column("reason", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "before_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "after_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "outcome",
                sa.String(length=32),
                nullable=False,
                server_default="success",
            )
        )
        batch_op.create_index(
            "ix_admin_audit_log_approval_request_id",
            ["approval_request_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_admin_audit_log_request_id",
            ["request_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("admin_audit_log") as batch_op:
        batch_op.drop_index("ix_admin_audit_log_request_id")
        batch_op.drop_index("ix_admin_audit_log_approval_request_id")
        batch_op.drop_column("outcome")
        batch_op.drop_column("after_json")
        batch_op.drop_column("before_json")
        batch_op.drop_column("reason")
        batch_op.drop_column("request_id")
        batch_op.drop_column("approval_request_id")
        batch_op.drop_column("permission_code")

    for index_name in [
        "ix_admin_approval_requests_rejected_by_admin_id",
        "ix_admin_approval_requests_approved_by_admin_id",
        "ix_admin_approval_requests_expires_at",
        "ix_admin_approval_requests_request_id",
        "ix_admin_approval_requests_action_type",
        "ix_admin_approval_requests_required_permission_code",
        "ix_admin_approval_requests_requested_by_admin_id",
        "ix_admin_approval_requests_status",
    ]:
        op.drop_index(index_name, table_name="admin_approval_requests")
    op.drop_table("admin_approval_requests")

    for index_name in [
        "ix_admin_user_permissions_revoked_by_admin_id",
        "ix_admin_user_permissions_granted_by_admin_id",
        "ix_admin_user_permissions_permission_code",
        "ix_admin_user_permissions_admin_user_id",
    ]:
        op.drop_index(index_name, table_name="admin_user_permissions")
    op.drop_table("admin_user_permissions")
    op.drop_table("admin_permissions")

    with op.batch_alter_table("admin_users") as batch_op:
        batch_op.drop_index("ix_admin_users_is_deleted")
        batch_op.drop_index("ix_admin_users_is_super_admin")
        batch_op.drop_constraint(
            "fk_admin_users_created_by_admin_id", type_="foreignkey"
        )
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("deactivation_reason")
        batch_op.drop_column("deactivated_at")
        batch_op.drop_column("created_by_admin_id")
        batch_op.drop_column("is_deleted")
        batch_op.drop_column("is_super_admin")
