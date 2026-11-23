"""Модель PayoutBatch: барьер «один открытый батч» (11.x-external-payout).

Зачем именно так: планировщик APScheduler живёт в lifespan, то есть в каждом
из 3 воркеров gunicorn (deploy/root-game.service: -w 3). Ежедневная задача
«сформировать батч» запустится трижды одновременно. Защита в Python
(`if scheduler is not None`) работает внутри процесса и не спасает, поэтому
инвариант держит частичный unique-индекс в БД.

Проверяем на реальной схеме (alembic upgrade head), а не на моках: индекс —
это поведение конкретной СУБД, и мок такое не воспроизводит.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

INSERT_BATCH = (
    "INSERT INTO payout_batches (id, status, total_nano, opened_at, "
    "created_at, updated_at) VALUES (:id, :status, 0, "
    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
)


class PayoutBatchBarrierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="chimera-payout-batch-")
        cls.database_path = Path(cls._tmp.name) / "payout_batches.sqlite3"
        database_url = f"sqlite:///{cls.database_path}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url
        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND_ROOT / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        cls.engine = create_engine(database_url)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()
        cls._tmp.cleanup()

    def setUp(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(text("DELETE FROM payout_batches"))

    def _insert(self, conn, batch_id: str, status: str) -> None:
        conn.execute(text(INSERT_BATCH), {"id": batch_id, "status": status})

    def test_only_one_open_batch_survives_three_workers(self) -> None:
        """Три воркера создают батч одновременно — в БД остаётся один."""
        created = 0
        blocked = 0
        with self.engine.begin() as conn:
            for worker in (1, 2, 3):
                try:
                    self._insert(conn, f"batch-w{worker}", "ready")
                    created += 1
                except IntegrityError:
                    blocked += 1

            self.assertEqual(created, 1)
            self.assertEqual(blocked, 2)

            open_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM payout_batches "
                    "WHERE status IN ('ready','submitted')"
                )
            ).scalar()
            self.assertEqual(open_count, 1)

    def test_submitted_also_blocks_new_open_batch(self) -> None:
        """Батч в submitted (ждёт сверки) тоже не пускает второй открытый."""
        with self.engine.begin() as conn:
            self._insert(conn, "batch-a", "submitted")

        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                self._insert(conn, "batch-b", "ready")

    def test_new_batch_allowed_after_close(self) -> None:
        """После confirmed/rolled_back можно открыть новый батч."""
        with self.engine.begin() as conn:
            self._insert(conn, "batch-a", "ready")

        with self.engine.begin() as conn:
            conn.execute(
                text("UPDATE payout_batches SET status='confirmed' WHERE id='batch-a'")
            )
            self._insert(conn, "batch-b", "ready")

        with self.engine.begin() as conn:
            statuses = dict(
                conn.execute(
                    text("SELECT id, status FROM payout_batches")
                ).all()
            )
        self.assertEqual(statuses, {"batch-a": "confirmed", "batch-b": "ready"})

    def test_closed_batches_are_unlimited(self) -> None:
        """История не ограничена: сколько угодно закрытых батчей."""
        with self.engine.begin() as conn:
            for index in range(5):
                self._insert(conn, f"batch-h{index}", "confirmed")
            total = conn.execute(
                text("SELECT COUNT(*) FROM payout_batches")
            ).scalar()
        self.assertEqual(total, 5)

    def test_invalid_status_rejected(self) -> None:
        """CHECK-констрейнт не даёт записать неизвестный статус."""
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as conn:
                self._insert(conn, "batch-bad", "wat")

    def test_rolled_back_also_frees_the_slot(self) -> None:
        """Откат батча освобождает слот для нового."""
        with self.engine.begin() as conn:
            self._insert(conn, "batch-a", "ready")

        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE payout_batches SET status='rolled_back', "
                    "rollback_reason='test' WHERE id='batch-a'"
                )
            )
            self._insert(conn, "batch-b", "ready")

        with self.engine.begin() as conn:
            open_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM payout_batches "
                    "WHERE status IN ('ready','submitted')"
                )
            ).scalar()
        self.assertEqual(open_count, 1)


if __name__ == "__main__":
    unittest.main()
