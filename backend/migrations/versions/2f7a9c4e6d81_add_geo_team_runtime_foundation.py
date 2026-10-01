"""add geo team runtime foundation

Revision ID: 2f7a9c4e6d81
Revises: 1a6d4c8e2b75
Create Date: 2026-10-01
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "2f7a9c4e6d81"
down_revision: Union[str, Sequence[str], None] = "1a6d4c8e2b75"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_inventory_event_immutability_guards() -> None:
    """Install dialect-aware immutable-ledger guards for inventory_events."""
    dialect = op.get_bind().dialect.name

    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_inventory_events_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'inventory_events are immutable';
            END;
            $$;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_inventory_events_no_update
            BEFORE UPDATE ON inventory_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_inventory_events_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_inventory_events_no_delete
            BEFORE DELETE ON inventory_events
            FOR EACH ROW
            EXECUTE FUNCTION prevent_inventory_events_mutation();
            """
        )
        return

    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER trg_inventory_events_no_update
            BEFORE UPDATE ON inventory_events
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'inventory_events are immutable');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER trg_inventory_events_no_delete
            BEFORE DELETE ON inventory_events
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'inventory_events are immutable');
            END;
            """
        )
        return

    raise RuntimeError(
        "Unsupported database dialect for inventory_events immutability guards."
    )


def upgrade() -> None:
    op.create_table(
        "location_proofs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("zone_id", sa.String(length=128), nullable=True),
        sa.Column("verifier_reference", sa.String(length=255), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
            "status IN ('verified', 'rejected', 'expired')",
            name="ck_location_proofs_status",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["game_players.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_location_proofs_player_id", "location_proofs", ["player_id"], unique=False
    )
    op.create_index(
        "ix_location_proofs_status", "location_proofs", ["status"], unique=False
    )
    op.create_index(
        "ix_location_proofs_zone_id", "location_proofs", ["zone_id"], unique=False
    )
    op.create_index(
        "ix_location_proofs_expires_at",
        "location_proofs",
        ["expires_at"],
        unique=False,
    )

    op.create_table(
        "team_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("effective_config_snapshot", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ("
            "'collecting', 'ready_to_start', 'active', 'succeeded', 'failed', "
            "'expired', 'cancelled_before_start'"
            ")",
            name="ck_team_sessions_status",
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_team_sessions_mission_id", "team_sessions", ["mission_id"], unique=False
    )
    op.create_index(
        "ix_team_sessions_status", "team_sessions", ["status"], unique=False
    )

    op.create_table(
        "mission_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("team_session_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("effective_config_snapshot", sa.JSON(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terminal_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ("
            "'reserved', 'accepted', 'active', 'succeeded', 'failed', "
            "'timeout', 'abandoned', 'cancelled_before_start'"
            ")",
            name="ck_mission_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["game_players.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["team_session_id"], ["team_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_mission_runs_player_id", "mission_runs", ["player_id"], unique=False
    )
    op.create_index(
        "ix_mission_runs_mission_id", "mission_runs", ["mission_id"], unique=False
    )
    op.create_index(
        "ix_mission_runs_team_session_id",
        "mission_runs",
        ["team_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_mission_runs_status", "mission_runs", ["status"], unique=False
    )

    op.create_table(
        "team_session_members",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("team_session_id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("mission_run_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('joined', 'ready', 'left', 'removed', 'settled')",
            name="ck_team_session_members_status",
        ),
        sa.ForeignKeyConstraint(
            ["team_session_id"], ["team_sessions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["game_players.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["mission_run_id"], ["mission_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "team_session_id",
            "player_id",
            name="uq_team_session_members_session_player",
        ),
        sa.UniqueConstraint(
            "mission_run_id",
            name="uq_team_session_members_mission_run",
        ),
    )
    op.create_index(
        "ix_team_session_members_team_session_id",
        "team_session_members",
        ["team_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_team_session_members_player_id",
        "team_session_members",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_team_session_members_status",
        "team_session_members",
        ["status"],
        unique=False,
    )

    op.create_table(
        "mission_attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("mission_run_id", sa.String(length=64), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("challenge_type", sa.String(length=64), nullable=False),
        sa.Column("protected_challenge_snapshot", sa.JSON(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
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
            "sequence_number >= 1",
            name="ck_mission_attempts_sequence_positive",
        ),
        sa.CheckConstraint(
            "status IN ('issued', 'submitted', 'succeeded', 'failed', 'timed_out')",
            name="ck_mission_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["mission_run_id"], ["mission_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mission_run_id",
            "sequence_number",
            name="uq_mission_attempts_run_sequence",
        ),
    )
    op.create_index(
        "ix_mission_attempts_mission_run_id",
        "mission_attempts",
        ["mission_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_mission_attempts_status", "mission_attempts", ["status"], unique=False
    )
    op.create_index(
        "ix_mission_attempts_deadline_at",
        "mission_attempts",
        ["deadline_at"],
        unique=False,
    )

    op.create_table(
        "wallet_reservations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("wallet_id", sa.String(length=64), nullable=False),
        sa.Column("mission_run_id", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
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
            "amount >= 0",
            name="ck_wallet_reservations_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'charged', 'released')",
            name="ck_wallet_reservations_status",
        ),
        sa.ForeignKeyConstraint(["wallet_id"], ["wallets.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["mission_run_id"], ["mission_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "wallet_id",
            "mission_run_id",
            name="uq_wallet_reservations_wallet_run",
        ),
    )
    op.create_index(
        "ix_wallet_reservations_wallet_id",
        "wallet_reservations",
        ["wallet_id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_reservations_mission_run_id",
        "wallet_reservations",
        ["mission_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_wallet_reservations_status",
        "wallet_reservations",
        ["status"],
        unique=False,
    )

    op.create_table(
        "inventory_reservations",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_item_id", sa.String(length=64), nullable=False),
        sa.Column("mission_run_id", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
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
            "quantity > 0",
            name="ck_inventory_reservations_quantity_positive",
        ),
        sa.CheckConstraint(
            "status IN ('reserved', 'consumed', 'released')",
            name="ck_inventory_reservations_status",
        ),
        sa.ForeignKeyConstraint(
            ["player_item_id"], ["player_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["mission_run_id"], ["mission_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_item_id",
            "mission_run_id",
            name="uq_inventory_reservations_item_run",
        ),
    )
    op.create_index(
        "ix_inventory_reservations_player_item_id",
        "inventory_reservations",
        ["player_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_reservations_mission_run_id",
        "inventory_reservations",
        ["mission_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_reservations_status",
        "inventory_reservations",
        ["status"],
        unique=False,
    )

    op.create_table(
        "inventory_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_item_id", sa.String(length=64), nullable=False),
        sa.Column("mission_run_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("quantity_delta", sa.Integer(), nullable=False),
        sa.Column("reference_type", sa.String(length=64), nullable=False),
        sa.Column("reference_id", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "quantity_delta <> 0",
            name="ck_inventory_events_quantity_delta_nonzero",
        ),
        sa.CheckConstraint(
            "event_type IN ('reserved', 'released', 'consumed', 'credited')",
            name="ck_inventory_events_type",
        ),
        sa.ForeignKeyConstraint(
            ["player_item_id"], ["player_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["mission_run_id"], ["mission_runs.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_item_id",
            "event_type",
            "reference_type",
            "reference_id",
            name="uq_inventory_events_item_event_reference",
        ),
    )
    op.create_index(
        "ix_inventory_events_player_item_id",
        "inventory_events",
        ["player_item_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_events_mission_run_id",
        "inventory_events",
        ["mission_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_inventory_events_event_type",
        "inventory_events",
        ["event_type"],
        unique=False,
    )
    _create_inventory_event_immutability_guards()

    op.create_table(
        "mission_settlements",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("mission_run_id", sa.String(length=64), nullable=False),
        sa.Column("team_session_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settlement_snapshot", sa.JSON(), nullable=False),
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
            "outcome IN ('succeeded', 'failed', 'timeout', 'abandoned')",
            name="ck_mission_settlements_outcome",
        ),
        sa.ForeignKeyConstraint(
            ["mission_run_id"], ["mission_runs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["team_session_id"], ["team_sessions.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mission_run_id",
            name="uq_mission_settlements_mission_run",
        ),
    )
    op.create_index(
        "ix_mission_settlements_team_session_id",
        "mission_settlements",
        ["team_session_id"],
        unique=False,
    )
    op.create_index(
        "ix_mission_settlements_outcome",
        "mission_settlements",
        ["outcome"],
        unique=False,
    )

    op.create_table(
        "player_fallback_entitlements",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column("offer_id", sa.String(length=64), nullable=False),
        sa.Column("quota_limit", sa.Integer(), nullable=False),
        sa.Column(
            "consumed_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
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
            "quota_limit >= 0",
            name="ck_player_fallback_entitlements_quota_nonnegative",
        ),
        sa.CheckConstraint(
            "consumed_count >= 0 AND consumed_count <= quota_limit",
            name="ck_player_fallback_entitlements_consumed_bounds",
        ),
        sa.CheckConstraint(
            "status IN ('available', 'exhausted', 'disabled')",
            name="ck_player_fallback_entitlements_status",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"], ["game_players.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["mission_id"], ["missions.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "player_id",
            "mission_id",
            name="uq_player_fallback_entitlements_player_mission",
        ),
    )
    op.create_index(
        "ix_player_fallback_entitlements_player_id",
        "player_fallback_entitlements",
        ["player_id"],
        unique=False,
    )
    op.create_index(
        "ix_player_fallback_entitlements_mission_id",
        "player_fallback_entitlements",
        ["mission_id"],
        unique=False,
    )
    op.create_index(
        "ix_player_fallback_entitlements_status",
        "player_fallback_entitlements",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    """
    Deliberately unsupported.

    These tables contain runtime, reservation, settlement, and immutable ledger
    history. Physical deletion is prohibited. Rollback uses a verified backup
    or a separately approved data-preserving migration plan.
    """
    raise NotImplementedError(
        "Downgrade is intentionally unsupported: geo/team runtime history is immutable."
    )
