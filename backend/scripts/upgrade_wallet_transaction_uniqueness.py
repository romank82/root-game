from __future__ import annotations

import sqlite3
from pathlib import Path

DATABASE_PATH = Path(__file__).resolve().parent.parent / "chimera.db"
INDEX_NAME = "uq_wallet_transactions_wallet_reference"

DUPLICATES_QUERY = """
SELECT
    wallet_id,
    reference_type,
    reference_id,
    COUNT(*) AS duplicate_count
FROM wallet_transactions
WHERE reference_type IS NOT NULL
  AND reference_id IS NOT NULL
GROUP BY wallet_id, reference_type, reference_id
HAVING COUNT(*) > 1
"""

CREATE_INDEX_QUERY = f"""
CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME}
ON wallet_transactions (
    wallet_id,
    reference_type,
    reference_id
)
"""


def main() -> None:
    if not DATABASE_PATH.exists():
        raise SystemExit(f"Database not found: {DATABASE_PATH}")

    with sqlite3.connect(DATABASE_PATH) as connection:
        duplicates = connection.execute(DUPLICATES_QUERY).fetchall()

        if duplicates:
            print("ERROR: duplicate wallet transaction references found.")
            for wallet_id, reference_type, reference_id, count in duplicates:
                print(
                    f"  wallet={wallet_id}; type={reference_type}; "
                    f"reference={reference_id}; count={count}"
                )
            raise SystemExit(
                "Migration stopped. Resolve duplicates before creating the index."
            )

        connection.execute(CREATE_INDEX_QUERY)
        connection.commit()

        indexes = connection.execute(
            "PRAGMA index_list('wallet_transactions')"
        ).fetchall()

    print("✓ Wallet transaction uniqueness upgrade completed.")
    print(f"✓ Ensured index: {INDEX_NAME}")
    print("Current indexes:")
    for index in indexes:
        print(f"  - {index}")


if __name__ == "__main__":
    main()
