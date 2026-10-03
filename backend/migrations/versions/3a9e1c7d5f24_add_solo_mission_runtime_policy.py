"""add solo mission runtime policy

Revision ID: 3a9e1c7d5f24
Revises: 2f7a9c4e6d81
Create Date: 2026-10-02
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "3a9e1c7d5f24"
down_revision: Union[str, Sequence[str], None] = "2f7a9c4e6d81"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_player_item_quantity_guards() -> None:
    """Prevent negative inventory projections on supported dialects."""
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.create_check_constraint(
            "ck_player_items_quantity_nonnegative",
            "player_items",
            "quantity >= 0",
        )
        return

    if dialect == "sqlite":
        # SQLite cannot ALTER TABLE ADD CONSTRAINT directly. Batch mode rebuilds
        # the table data-preservingly and installs the same CHECK as PostgreSQL.
        with op.batch_alter_table("player_items") as batch_op:
            batch_op.create_check_constraint(
                "ck_player_items_quantity_nonnegative",
                "quantity >= 0",
            )
        return

    raise RuntimeError(
        "Mission runtime policy migration supports only SQLite and PostgreSQL."
    )


def upgrade() -> None:
    bind = op.get_bind()
    negative_quantity_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM player_items WHERE quantity < 0")
    ).scalar_one()

    if negative_quantity_count != 0:
        raise RuntimeError(
            "Cannot install non-negative inventory guard while player_items "
            "contains negative quantities."
        )

    op.create_table(
        "mission_runtime_policies",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("entry_root_atomic", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("attempt_deadline_seconds", sa.Integer(), nullable=False),
        sa.Column("repeatability_policy", sa.String(length=64), nullable=False),
        sa.Column("required_items_json", sa.JSON(), nullable=False),
        sa.Column("challenge_policy_json", sa.JSON(), nullable=False),
        sa.Column("reward_policy_json", sa.JSON(), nullable=False),
        sa.Column("fallback_policy_json", sa.JSON(), nullable=True),
        sa.Column("feature_flags_json", sa.JSON(), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_mission_runtime_policies_status",
        ),
        sa.CheckConstraint(
            "version >= 1",
            name="ck_mission_runtime_policies_version_positive",
        ),
        sa.CheckConstraint(
            "entry_root_atomic >= 0",
            name="ck_mission_runtime_policies_entry_root_nonnegative",
        ),
        sa.CheckConstraint(
            "max_attempts >= 1",
            name="ck_mission_runtime_policies_max_attempts_positive",
        ),
        sa.CheckConstraint(
            "attempt_deadline_seconds >= 1",
            name="ck_mission_runtime_policies_deadline_positive",
        ),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mission_id",
            "version",
            name="uq_mission_runtime_policies_mission_version",
        ),
    )
    op.create_index(
        "ix_mission_runtime_policies_mission_id",
        "mission_runtime_policies",
        ["mission_id"],
        unique=False,
    )
    op.create_index(
        "ix_mission_runtime_policies_status",
        "mission_runtime_policies",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_mission_runtime_policies_one_published_per_mission",
        "mission_runtime_policies",
        ["mission_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )

    dialect = bind.dialect.name

    if dialect == "sqlite":
        with op.batch_alter_table("mission_runs") as batch_op:
            batch_op.add_column(
                sa.Column("runtime_policy_id", sa.String(length=64), nullable=True)
            )
            batch_op.add_column(
                sa.Column("runtime_policy_version", sa.Integer(), nullable=True)
            )
            batch_op.add_column(
                sa.Column(
                    "start_idempotency_key",
                    sa.String(length=128),
                    nullable=True,
                )
            )
            batch_op.add_column(
                sa.Column(
                    "start_request_fingerprint",
                    sa.String(length=64),
                    nullable=True,
                )
            )
            batch_op.create_foreign_key(
                "fk_mission_runs_runtime_policy_id",
                "mission_runtime_policies",
                ["runtime_policy_id"],
                ["id"],
                ondelete="RESTRICT",
            )
            batch_op.create_check_constraint(
                "ck_mission_runs_runtime_policy_pair",
                "(runtime_policy_id IS NULL AND runtime_policy_version IS NULL) "
                "OR (runtime_policy_id IS NOT NULL AND runtime_policy_version IS NOT NULL)",
            )
    elif dialect == "postgresql":
        op.add_column(
            "mission_runs",
            sa.Column("runtime_policy_id", sa.String(length=64), nullable=True),
        )
        op.add_column(
            "mission_runs",
            sa.Column("runtime_policy_version", sa.Integer(), nullable=True),
        )
        op.add_column(
            "mission_runs",
            sa.Column(
                "start_idempotency_key",
                sa.String(length=128),
                nullable=True,
            ),
        )
        op.add_column(
            "mission_runs",
            sa.Column(
                "start_request_fingerprint",
                sa.String(length=64),
                nullable=True,
            ),
        )
        op.create_foreign_key(
            "fk_mission_runs_runtime_policy_id",
            "mission_runs",
            "mission_runtime_policies",
            ["runtime_policy_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            "ck_mission_runs_runtime_policy_pair",
            "mission_runs",
            "(runtime_policy_id IS NULL AND runtime_policy_version IS NULL) "
            "OR (runtime_policy_id IS NOT NULL AND runtime_policy_version IS NOT NULL)",
        )
    else:
        raise RuntimeError(
            "Mission runtime policy migration supports only SQLite and PostgreSQL."
        )

    op.create_index(
        "ix_mission_runs_runtime_policy_id",
        "mission_runs",
        ["runtime_policy_id"],
        unique=False,
    )
    op.create_index(
        "uq_mission_runs_player_start_idempotency",
        "mission_runs",
        ["player_id", "start_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("start_idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("start_idempotency_key IS NOT NULL"),
    )

    op.add_column(
        "mission_attempts",
        sa.Column("issue_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "mission_attempts",
        sa.Column("submit_idempotency_key", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "mission_attempts",
        sa.Column(
            "submit_request_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_mission_attempts_run_issue_idempotency",
        "mission_attempts",
        ["mission_run_id", "issue_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("issue_idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("issue_idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "uq_mission_attempts_submit_idempotency",
        "mission_attempts",
        ["submit_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("submit_idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("submit_idempotency_key IS NOT NULL"),
    )

    _create_player_item_quantity_guards()


def downgrade() -> None:
    """
    Deliberately unsupported.

    This revision introduces runtime policy references and idempotency history
    used by immutable run, settlement, wallet, and inventory records. Physical
    deletion or rewrite is prohibited. Rollback requires the verified backup
    created before migration or a separately approved data-preserving plan.
    """
    raise NotImplementedError(
        "Downgrade is intentionally unsupported: mission runtime history is immutable."
    )
