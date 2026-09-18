#!/usr/bin/env python3
"""
Import canonical player state from a SQLite source database into PostgreSQL.

Default behavior is dry-run. Use --apply to write data.

Example inside the backend Docker image:
  python /work/scripts/import_sqlite_player_state.py \
    --sqlite /work/chimera.db \
    --player-id demo-player \
    --apply
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text


USER_STATE_TABLES = (
    "game_players",
    "player_missions",
    "wallets",
    "wallet_transactions",
    "player_items",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Import one canonical SQLite player state into PostgreSQL."
    )
    parser.add_argument(
        "--sqlite",
        required=True,
        type=Path,
        help="Path to the source SQLite database.",
    )
    parser.add_argument(
        "--player-id",
        default="demo-player",
        help="Internal game_players.id to migrate (default: demo-player).",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually modify PostgreSQL. Without it, performs dry-run only.",
    )
    parser.add_argument(
        "--backup",
        type=Path,
        default=None,
        help="Destination for PostgreSQL pre-import JSON backup.",
    )
    return parser.parse_args()


def json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list, int, float, bool)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def to_json_text(value: Any) -> str:
    return json.dumps(json_value(value), ensure_ascii=False, separators=(",", ":"))


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(raw)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def sqlite_rows(conn: sqlite3.Connection, table: str, player_id: str) -> list[dict]:
    if table == "game_players":
        query = "SELECT * FROM game_players WHERE id = ?"
        params = (player_id,)
    elif table in ("player_missions", "wallets", "player_items"):
        query = f"SELECT * FROM {table} WHERE player_id = ? ORDER BY id"
        params = (player_id,)
    elif table == "wallet_transactions":
        query = """
            SELECT wt.*
            FROM wallet_transactions AS wt
            JOIN wallets AS w ON w.id = wt.wallet_id
            WHERE w.player_id = ?
            ORDER BY wt.created_at, wt.id
        """
        params = (player_id,)
    else:
        raise ValueError(f"Unsupported source table: {table}")

    return [dict(row) for row in conn.execute(query, params).fetchall()]


def read_sqlite_state(path: Path, player_id: str) -> dict[str, list[dict]]:
    if not path.is_file():
        raise SystemExit(f"SQLite database not found: {path}")

    source_uri = f"file:{path.resolve()}?mode=ro"
    conn = sqlite3.connect(source_uri, uri=True)
    conn.row_factory = sqlite3.Row

    try:
        available = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        missing = set(USER_STATE_TABLES) - available
        if missing:
            raise SystemExit(
                "SQLite source does not contain required tables: "
                + ", ".join(sorted(missing))
            )

        state = {
            table: sqlite_rows(conn, table, player_id)
            for table in USER_STATE_TABLES
        }
    finally:
        conn.close()

    if len(state["game_players"]) != 1:
        raise SystemExit(
            f"Expected exactly one game_players row for {player_id!r}; "
            f"found {len(state['game_players'])}."
        )

    return state


def fetch_destination_state(connection, player_id: str) -> dict[str, list[dict]]:
    return {
        "game_players": connection.execute(
            text("SELECT * FROM game_players WHERE id = :player_id"),
            {"player_id": player_id},
        ).mappings().all(),
        "player_missions": connection.execute(
            text(
                "SELECT * FROM player_missions "
                "WHERE player_id = :player_id ORDER BY id"
            ),
            {"player_id": player_id},
        ).mappings().all(),
        "wallets": connection.execute(
            text("SELECT * FROM wallets WHERE player_id = :player_id ORDER BY id"),
            {"player_id": player_id},
        ).mappings().all(),
        "wallet_transactions": connection.execute(
            text(
                """
                SELECT wt.*
                FROM wallet_transactions AS wt
                JOIN wallets AS w ON w.id = wt.wallet_id
                WHERE w.player_id = :player_id
                ORDER BY wt.created_at, wt.id
                """
            ),
            {"player_id": player_id},
        ).mappings().all(),
        "player_items": connection.execute(
            text(
                "SELECT * FROM player_items "
                "WHERE player_id = :player_id ORDER BY id"
            ),
            {"player_id": player_id},
        ).mappings().all(),
    }


def report(label: str, state: dict[str, list[dict]]) -> None:
    print(f"\n{label}")
    for table in USER_STATE_TABLES:
        print(f"  {table}: {len(state[table])}")


def validate_references(connection, state: dict[str, list[dict]]) -> None:
    mission_ids = sorted({row["mission_id"] for row in state["player_missions"]})
    item_ids = sorted({row["item_id"] for row in state["player_items"]})

    if mission_ids:
        found = set(
            connection.execute(
                text("SELECT id FROM missions WHERE id = ANY(:ids)"),
                {"ids": mission_ids},
            ).scalars()
        )
        missing = sorted(set(mission_ids) - found)
        if missing:
            raise SystemExit(
                "PostgreSQL is missing source mission IDs: " + ", ".join(missing)
            )

    if item_ids:
        found = set(
            connection.execute(
                text("SELECT id FROM items WHERE id = ANY(:ids)"),
                {"ids": item_ids},
            ).scalars()
        )
        missing = sorted(set(item_ids) - found)
        if missing:
            raise SystemExit(
                "PostgreSQL is missing source item IDs: " + ", ".join(missing)
            )


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_backup(path: Path, destination: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "PostgreSQL player-state backup before SQLite canonical import",
        "state": {
            table: [dict(row) for row in rows]
            for table, rows in destination.items()
        },
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )
    print(f"✓ PostgreSQL backup written: {path}")


def replace_player_state(connection, state: dict[str, list[dict]], player_id: str) -> None:
    player = state["game_players"][0]

    # First remove dependent state for this player only.
    connection.execute(
        text(
            """
            DELETE FROM wallet_transactions
            WHERE wallet_id IN (
                SELECT id FROM wallets WHERE player_id = :player_id
            )
            """
        ),
        {"player_id": player_id},
    )
    connection.execute(
        text("DELETE FROM player_items WHERE player_id = :player_id"),
        {"player_id": player_id},
    )
    connection.execute(
        text("DELETE FROM player_missions WHERE player_id = :player_id"),
        {"player_id": player_id},
    )
    connection.execute(
        text("DELETE FROM wallets WHERE player_id = :player_id"),
        {"player_id": player_id},
    )

    # Keep the same internal player ID while restoring source identity attributes.
    connection.execute(
        text(
            """
            INSERT INTO game_players (
                id, display_name, auth_provider, external_id, status,
                created_at, updated_at
            )
            VALUES (
                :id, :display_name, :auth_provider, :external_id, :status,
                :created_at, :updated_at
            )
            ON CONFLICT (id) DO UPDATE SET
                display_name = EXCLUDED.display_name,
                auth_provider = EXCLUDED.auth_provider,
                external_id = EXCLUDED.external_id,
                status = EXCLUDED.status,
                updated_at = EXCLUDED.updated_at
            """
        ),
        {
            **player,
            "created_at": parse_timestamp(player["created_at"]),
            "updated_at": parse_timestamp(player["updated_at"]),
        },
    )

    for row in state["wallets"]:
        connection.execute(
            text(
                """
                INSERT INTO wallets (
                    id, player_id, currency, available_balance, locked_balance,
                    created_at, updated_at
                )
                VALUES (
                    :id, :player_id, :currency, :available_balance, :locked_balance,
                    :created_at, :updated_at
                )
                """
            ),
            {
                **row,
                "created_at": parse_timestamp(row["created_at"]),
                "updated_at": parse_timestamp(row["updated_at"]),
            },
        )

    for row in state["player_missions"]:
        connection.execute(
            text(
                """
                INSERT INTO player_missions (
                    id, player_id, mission_id, status, attempt_count, progress,
                    started_at, completed_at, created_at, updated_at
                )
                VALUES (
                    :id, :player_id, :mission_id, :status, :attempt_count,
                    CAST(:progress AS json),
                    :started_at, :completed_at, :created_at, :updated_at
                )
                """
            ),
            {
                **row,
                "progress": to_json_text(row["progress"]),
                "started_at": parse_timestamp(row["started_at"]),
                "completed_at": parse_timestamp(row["completed_at"]),
                "created_at": parse_timestamp(row["created_at"]),
                "updated_at": parse_timestamp(row["updated_at"]),
            },
        )

    for row in state["player_items"]:
        connection.execute(
            text(
                """
                INSERT INTO player_items (
                    id, player_id, item_id, quantity, obtained_from_type,
                    obtained_from_id, created_at, updated_at
                )
                VALUES (
                    :id, :player_id, :item_id, :quantity, :obtained_from_type,
                    :obtained_from_id, :created_at, :updated_at
                )
                """
            ),
            {
                **row,
                "created_at": parse_timestamp(row["created_at"]),
                "updated_at": parse_timestamp(row["updated_at"]),
            },
        )

    for row in state["wallet_transactions"]:
        connection.execute(
            text(
                """
                INSERT INTO wallet_transactions (
                    id, wallet_id, amount, balance_after, transaction_type, reason,
                    reference_type, reference_id, metadata_json,
                    created_at, updated_at
                )
                VALUES (
                    :id, :wallet_id, :amount, :balance_after, :transaction_type,
                    :reason, :reference_type, :reference_id,
                    CAST(:metadata_json AS json),
                    :created_at, :updated_at
                )
                """
            ),
            {
                **row,
                "metadata_json": to_json_text(row["metadata_json"]),
                "created_at": parse_timestamp(row["created_at"]),
                "updated_at": parse_timestamp(row["updated_at"]),
            },
        )


def main() -> int:
    args = parse_args()
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required.")

    source = read_sqlite_state(args.sqlite, args.player_id)

    engine = create_engine(database_url, future=True)
    with engine.connect() as connection:
        validate_references(connection, source)
        destination = fetch_destination_state(connection, args.player_id)

    report("SQLite canonical source:", source)
    report("Current PostgreSQL destination:", destination)

    if not args.apply:
        print("\nDRY RUN ONLY — PostgreSQL was not modified.")
        print("Run again with --apply to replace this player's PostgreSQL state.")
        return 0

    default_backup = (
        Path("/work/backups")
        / f"postgres-{args.player_id}-before-import-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    backup_path = args.backup or default_backup

    with engine.begin() as connection:
        # Re-read inside the write transaction, then persist the backup before changes.
        destination = fetch_destination_state(connection, args.player_id)
        write_backup(backup_path, destination)
        validate_references(connection, source)
        replace_player_state(connection, source, args.player_id)

    print("\n✓ Import committed successfully.")
    report("PostgreSQL imported state:", source)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"\nIMPORT FAILED: {error}", file=sys.stderr)
        raise
