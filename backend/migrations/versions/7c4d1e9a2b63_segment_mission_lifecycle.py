"""make SegmentMission historical with active/archive lifecycle

Revision ID: 7c4d1e9a2b63
Revises: 6a1b2c_add_segments_missions
Create Date: 2026-09-28
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "7c4d1e9a2b63"
down_revision: Union[str, Sequence[str], None] = "6a1b2c_add_segments_missions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ACTIVE_STATUS = "active"
ARCHIVED_STATUS = "archived"


def _new_link_id() -> str:
    return f"segment-mission-{uuid4().hex}"



def _create_history_protection_triggers(dialect_name: str) -> None:
    """
    Preserve SegmentMission history at DB level.

    The application archives a link by transitioning active -> archived. Direct
    DELETE, changes to link identity, and any mutation of archived history are
    rejected for SQLite and PostgreSQL.
    """
    if dialect_name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_segment_mission_history_mutation()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'segments_missions rows cannot be deleted'
                        USING ERRCODE = '55000';
                END IF;

                IF OLD.id IS DISTINCT FROM NEW.id
                   OR OLD.segment_id IS DISTINCT FROM NEW.segment_id
                   OR OLD.mission_id IS DISTINCT FROM NEW.mission_id
                   OR OLD.created_at IS DISTINCT FROM NEW.created_at THEN
                    RAISE EXCEPTION 'SegmentMission identity is immutable'
                        USING ERRCODE = '55000';
                END IF;

                IF OLD.status = 'archived' THEN
                    RAISE EXCEPTION 'archived SegmentMission is immutable'
                        USING ERRCODE = '55000';
                END IF;

                RETURN NEW;
            END;
            $$;
            """
        )
        op.execute(
            """
            CREATE TRIGGER segments_missions_no_delete
            BEFORE DELETE ON segments_missions
            FOR EACH ROW
            EXECUTE FUNCTION prevent_segment_mission_history_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER segments_missions_history_guard
            BEFORE UPDATE ON segments_missions
            FOR EACH ROW
            EXECUTE FUNCTION prevent_segment_mission_history_mutation();
            """
        )
        return

    if dialect_name == "sqlite":
        op.execute(
            """
            CREATE TRIGGER segments_missions_no_delete
            BEFORE DELETE ON segments_missions
            FOR EACH ROW
            BEGIN
                SELECT RAISE(ABORT, 'segments_missions rows cannot be deleted');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER segments_missions_history_guard
            BEFORE UPDATE ON segments_missions
            FOR EACH ROW
            WHEN OLD.id IS NOT NEW.id
              OR OLD.segment_id IS NOT NEW.segment_id
              OR OLD.mission_id IS NOT NEW.mission_id
              OR OLD.created_at IS NOT NEW.created_at
              OR OLD.status = 'archived'
            BEGIN
                SELECT RAISE(ABORT, 'SegmentMission history is immutable');
            END;
            """
        )
        return

    raise RuntimeError(
        f"Unsupported database dialect for SegmentMission history protection: "
        f"{dialect_name}"
    )

def upgrade() -> None:
    """
    Replace the legacy composite-PK association table with a historical link table.

    Existing association rows are copied as active rows with generated immutable IDs.
    The operation is a controlled table replacement because SQLite cannot replace
    the composite primary key in place. A verified backup is required before use.
    """
    bind = op.get_bind()

    legacy_rows = bind.execute(
        sa.text(
            """
            SELECT segment_id, mission_id, sort_order
            FROM segments_missions
            ORDER BY segment_id, mission_id
            """
        )
    ).mappings().all()

    # The legacy table has no external FK dependants. Explicitly remove its
    # indexes before replacing it so both SQLite and PostgreSQL remain supported.
    op.drop_index(
        "ix_segments_missions_mission_id",
        table_name="segments_missions",
    )
    op.drop_index(
        "ix_segments_missions_segment_id",
        table_name="segments_missions",
    )
    op.drop_table("segments_missions")

    op.create_table(
        "segments_missions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("segment_id", sa.String(length=64), nullable=False),
        sa.Column("mission_id", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=ACTIVE_STATUS,
        ),
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_by_admin_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
        ),
        sa.CheckConstraint(
            (
                "(status = 'active' "
                "AND archived_at IS NULL "
                "AND archived_by_admin_id IS NULL) "
                "OR "
                "(status = 'archived' AND archived_at IS NOT NULL)"
            ),
            name="ck_segments_missions_lifecycle",
        ),
        sa.ForeignKeyConstraint(
            ["segment_id"],
            ["segments.id"],
            name="fk_segments_missions_segment_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["mission_id"],
            ["missions.id"],
            name="fk_segments_missions_mission_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["archived_by_admin_id"],
            ["admin_users.id"],
            name="fk_segments_missions_archived_by_admin_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_segments_missions"),
    )

    op.create_index(
        "ix_segments_missions_segment_id",
        "segments_missions",
        ["segment_id"],
        unique=False,
    )
    op.create_index(
        "ix_segments_missions_mission_id",
        "segments_missions",
        ["mission_id"],
        unique=False,
    )
    op.create_index(
        "ix_segments_missions_status",
        "segments_missions",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_segments_missions_archived_by_admin_id",
        "segments_missions",
        ["archived_by_admin_id"],
        unique=False,
    )
    op.create_index(
        "ix_segments_missions_active_segment_sort",
        "segments_missions",
        ["segment_id", "sort_order", "id"],
        unique=False,
    )
    op.create_index(
        "uq_segments_missions_active_pair",
        "segments_missions",
        ["segment_id", "mission_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )

    if legacy_rows:
        now = datetime.now(timezone.utc)
        op.bulk_insert(
            sa.table(
                "segments_missions",
                sa.column("id", sa.String()),
                sa.column("segment_id", sa.String()),
                sa.column("mission_id", sa.String()),
                sa.column("status", sa.String()),
                sa.column("sort_order", sa.Integer()),
                sa.column("created_at", sa.DateTime(timezone=True)),
                sa.column("updated_at", sa.DateTime(timezone=True)),
            ),
            [
                {
                    "id": _new_link_id(),
                    "segment_id": row["segment_id"],
                    "mission_id": row["mission_id"],
                    "status": ACTIVE_STATUS,
                    "sort_order": row["sort_order"],
                    "created_at": now,
                    "updated_at": now,
                }
                for row in legacy_rows
            ],
        )

    _create_history_protection_triggers(bind.dialect.name)


def downgrade() -> None:
    """
    Intentionally irreversible.

    Reverting to the former composite primary key would destroy archived-link
    history and may reject valid repeated links. Restore the verified backup
    instead of using an Alembic downgrade.
    """
    raise RuntimeError(
        "Irreversible migration: restoring the legacy SegmentMission schema "
        "would destroy historical archived links. Restore a verified backup instead."
    )
