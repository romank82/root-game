from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


EXPECTED_REVISION = "2f7a9c4e6d81"
EXPECTED_TABLES = {
    "location_proofs",
    "team_sessions",
    "mission_runs",
    "team_session_members",
    "mission_attempts",
    "wallet_reservations",
    "inventory_reservations",
    "inventory_events",
    "mission_settlements",
    "player_fallback_entitlements",
}
EXPECTED_TRIGGERS = {
    "trg_inventory_events_no_update",
    "trg_inventory_events_no_delete",
}


class ValidationError(RuntimeError):
    """Raised when the disposable migration validation contract is violated."""


def _expect_integrity_error(
    connection: sqlite3.Connection,
    statement: str,
    parameters: tuple[object, ...],
    expected_fragment: str,
) -> None:
    try:
        connection.execute(statement, parameters)
    except sqlite3.IntegrityError as error:
        if expected_fragment.casefold() not in str(error).casefold():
            raise ValidationError(
                "constraint rejection had an unexpected safe category"
            ) from error
        return

    raise ValidationError("expected database constraint rejection did not occur")


def _scalar(connection: sqlite3.Connection, statement: str) -> object:
    row = connection.execute(statement).fetchone()
    if row is None:
        raise ValidationError("expected scalar query result is absent")
    return row[0]


def _apply_migrations(repository_backend: Path, database_path: Path) -> None:
    environment = os.environ.copy()
    environment["DATABASE_URL"] = f"sqlite:///{database_path}"

    completed = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=repository_backend,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise ValidationError("Alembic upgrade failed in disposable SQLite database")


def _assert_schema(connection: sqlite3.Connection) -> None:
    revision = _scalar(connection, "SELECT version_num FROM alembic_version")
    if revision != EXPECTED_REVISION:
        raise ValidationError("disposable database revision differs from expected head")

    tables = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        )
    }
    missing_tables = EXPECTED_TABLES - tables
    if missing_tables:
        raise ValidationError("disposable database is missing runtime tables")

    triggers = {
        row[0]
        for row in connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'trigger'
              AND name LIKE 'trg_inventory_events_%'
            """
        )
    }
    if triggers != EXPECTED_TRIGGERS:
        raise ValidationError("inventory event immutability triggers differ")

    foreign_keys = {
        (row[3], row[2], row[4], row[6])
        for row in connection.execute('PRAGMA foreign_key_list("inventory_events")')
    }
    expected_foreign_keys = {
        ("player_item_id", "player_items", "id", "RESTRICT"),
        ("mission_run_id", "mission_runs", "id", "RESTRICT"),
    }
    if foreign_keys != expected_foreign_keys:
        raise ValidationError("inventory event foreign key policy differs")


def _insert_minimal_fixture(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO seasons (id, slug, title, status, sort_order)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("test-season", "test-season", "Test season", "published", 0),
    )
    connection.execute(
        """
        INSERT INTO chapters (id, season_id, slug, title, status, sort_order)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "test-chapter",
            "test-season",
            "test-chapter",
            "Test chapter",
            "published",
            0,
        ),
    )
    connection.execute(
        """
        INSERT INTO missions (
            id, chapter_id, slug, mission_type, title,
            content, validation_config, status, sort_order
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-mission",
            "test-chapter",
            "test-mission",
            "team",
            "Test mission",
            "{}",
            "{}",
            "published",
            0,
        ),
    )
    connection.execute(
        """
        INSERT INTO game_players (
            id, display_name, auth_provider, external_id, status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        ("test-player", "Test player", "test", "test-external-id", "active"),
    )
    connection.execute(
        """
        INSERT INTO items (
            id, slug, code, title, category, rarity,
            is_unique, content, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-item",
            "test-item",
            "TEST-ITEM",
            "Test item",
            "test",
            "common",
            0,
            "{}",
            "published",
        ),
    )
    connection.execute(
        """
        INSERT INTO player_items (
            id, player_id, item_id, quantity, obtained_from_type, obtained_from_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "test-player-item",
            "test-player",
            "test-item",
            5,
            "test",
            "fixture",
        ),
    )
    connection.execute(
        """
        INSERT INTO team_sessions (
            id, mission_id, status, effective_config_snapshot
        )
        VALUES (?, ?, ?, ?)
        """,
        ("test-team-session", "test-mission", "collecting", "{}"),
    )
    connection.execute(
        """
        INSERT INTO mission_runs (
            id, player_id, mission_id, team_session_id,
            status, effective_config_snapshot
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            "test-mission-run",
            "test-player",
            "test-mission",
            "test-team-session",
            "reserved",
            "{}",
        ),
    )


def _assert_runtime_guards(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO inventory_events (
            id, player_item_id, mission_run_id, event_type, quantity_delta,
            reference_type, reference_id, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-inventory-event",
            "test-player-item",
            "test-mission-run",
            "reserved",
            -1,
            "inventory_reservation",
            "test-reservation",
            "{}",
        ),
    )

    _expect_integrity_error(
        connection,
        """
        INSERT INTO inventory_events (
            id, player_item_id, mission_run_id, event_type, quantity_delta,
            reference_type, reference_id, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-zero-delta-event",
            "test-player-item",
            "test-mission-run",
            "reserved",
            0,
            "inventory_reservation",
            "test-zero-delta",
            "{}",
        ),
        "check constraint",
    )

    _expect_integrity_error(
        connection,
        """
        INSERT INTO inventory_events (
            id, player_item_id, mission_run_id, event_type, quantity_delta,
            reference_type, reference_id, metadata_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "test-duplicate-event",
            "test-player-item",
            "test-mission-run",
            "reserved",
            -1,
            "inventory_reservation",
            "test-reservation",
            "{}",
        ),
        "unique constraint",
    )

    _expect_integrity_error(
        connection,
        "UPDATE inventory_events SET quantity_delta = ? WHERE id = ?",
        (-2, "test-inventory-event"),
        "immutable",
    )

    _expect_integrity_error(
        connection,
        "DELETE FROM inventory_events WHERE id = ?",
        ("test-inventory-event",),
        "immutable",
    )

    _expect_integrity_error(
        connection,
        "DELETE FROM player_items WHERE id = ?",
        ("test-player-item",),
        "foreign key constraint",
    )


def _assert_database_health(connection: sqlite3.Connection) -> None:
    integrity = _scalar(connection, "PRAGMA integrity_check")
    if integrity != "ok":
        raise ValidationError("disposable SQLite integrity check failed")

    foreign_key_violations = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if foreign_key_violations:
        raise ValidationError("disposable SQLite foreign key check failed")


def main() -> int:
    backend_directory = Path(__file__).resolve().parent.parent
    repository_root = backend_directory.parent
    test_root = repository_root / ".local-migration-tests"

    test_root.mkdir(mode=0o700, exist_ok=True)
    disposable_directory = Path(
        tempfile.mkdtemp(prefix="geo-team-runtime-", dir=test_root)
    )
    database_path = disposable_directory / "runtime-validation.sqlite3"

    try:
        _apply_migrations(backend_directory, database_path)

        connection = sqlite3.connect(database_path)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            _assert_schema(connection)
            _insert_minimal_fixture(connection)
            _assert_runtime_guards(connection)
            _assert_database_health(connection)
            connection.commit()
        finally:
            connection.close()

        print("disposable_database: created_and_validated")
        print("migration_revision: 2f7a9c4e6d81")
        print("runtime_tables: 10")
        print("inventory_event_guards: update_delete_immutable")
        print("constraint_checks: zero_delta_unique_restrict")
        print("sqlite_integrity: ok")
        print("foreign_key_check: ok")
        return 0
    finally:
        shutil.rmtree(disposable_directory, ignore_errors=True)
        print("disposable_database: removed")


if __name__ == "__main__":
    raise SystemExit(main())
