"""Тесты хелперов политик по странам (13.2-b): is_blocked /
is_feature_restricted / get_country_policy.

Реальная SQLite + alembic upgrade head (как в test_admin_country_policies),
но без patch SessionLocal: country_policy.py НЕ импортирует SessionLocal —
хелперы принимают готовую сессию, поэтому сессия передаётся напрямую.

Покрытие:
- is_blocked: blocked -> True; allowed/restricted/нет записи/NULL -> False;
- is_feature_restricted: restricted + feature в restricted_features -> True,
  feature вне списка -> False; allowed/blocked/NULL -> False;
- get_country_policy: существующая -> объект (в т.ч. по нижнему регистру
  country_code — нормализация upper); нет записи/NULL -> None.

Интеграция гейтов во вход/transfer/mission/team — отдельно (13.2-b-3-b).
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.country_policy import (
    get_country_policy,
    is_blocked,
    is_feature_restricted,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


class CountryPolicyHelpersTests(unittest.TestCase):
    """Хелперы CountryPolicy на реальной SQLite (alembic upgrade head)."""

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-country-policy-helpers-"
        )
        self.database_path = (
            Path(self._temporary_directory.name) / "country.sqlite3"
        )
        database_url = f"sqlite:///{self.database_path}"

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

        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    def tearDown(self) -> None:
        if self.engine is not None:
            self.engine.dispose()
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы ---------------------------------------------

    def _make_policy(
        self,
        country_code: str,
        policy: str,
        restricted_features: list[str] | None = None,
    ) -> None:
        """Создать запись CountryPolicy (commit) для последующих проверок."""
        from app.models import CountryPolicy

        with self.SessionLocal.begin() as session:
            session.add(
                CountryPolicy(
                    id=f"country-policy-{uuid.uuid4().hex[:24]}",
                    country_code=country_code,
                    policy=policy,
                    restricted_features=restricted_features,
                    reason=None,
                )
            )

    # ---- Тесты ----------------------------------------------------------

    def test_is_blocked(self) -> None:
        self._make_policy("RU", "blocked")
        self._make_policy("US", "allowed")
        self._make_policy("FR", "restricted", restricted_features=["transfer"])

        with self.SessionLocal() as session:
            # blocked -> True.
            self.assertTrue(is_blocked(session, "RU"))
            # allowed / restricted -> False.
            self.assertFalse(is_blocked(session, "US"))
            self.assertFalse(is_blocked(session, "FR"))
            # Нет записи / NULL -> False (allowed по умолчанию).
            self.assertFalse(is_blocked(session, "XX"))
            self.assertFalse(is_blocked(session, None))

    def test_is_feature_restricted(self) -> None:
        self._make_policy("RU", "restricted", restricted_features=["transfer"])
        self._make_policy("DE", "restricted", restricted_features=["transfer", "mission", "team"])
        self._make_policy("US", "allowed")
        self._make_policy("CN", "blocked")

        with self.SessionLocal() as session:
            # restricted + feature в списке -> True; вне списка -> False.
            self.assertTrue(is_feature_restricted(session, "RU", "transfer"))
            self.assertFalse(is_feature_restricted(session, "RU", "mission"))
            self.assertFalse(is_feature_restricted(session, "RU", "team"))

            # Все три фичи в списке -> все True.
            self.assertTrue(is_feature_restricted(session, "DE", "transfer"))
            self.assertTrue(is_feature_restricted(session, "DE", "mission"))
            self.assertTrue(is_feature_restricted(session, "DE", "team"))

            # allowed / blocked -> False для всех фич.
            for feature in ("transfer", "mission", "team"):
                self.assertFalse(is_feature_restricted(session, "US", feature))
                self.assertFalse(is_feature_restricted(session, "CN", feature))

            # NULL -> False.
            self.assertFalse(is_feature_restricted(session, None, "transfer"))

    def test_get_country_policy(self) -> None:
        self._make_policy("PL", "restricted", restricted_features=["team"])

        with self.SessionLocal() as session:
            # Существующая -> объект; регистр не важен (upper-нормализация).
            policy = get_country_policy(session, "PL")
            self.assertIsNotNone(policy)
            self.assertEqual(policy.country_code, "PL")
            self.assertEqual(policy.policy, "restricted")

            by_lowercase = get_country_policy(session, "pl")
            self.assertIsNotNone(by_lowercase)
            self.assertEqual(by_lowercase.id, policy.id)

            # Нет записи / NULL -> None.
            self.assertIsNone(get_country_policy(session, "ZZ"))
            self.assertIsNone(get_country_policy(session, None))
            self.assertIsNone(get_country_policy(session, ""))