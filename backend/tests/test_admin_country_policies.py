"""Тесты CRUD админ-роутера политик стран (13.2-a).

Реальный SQLite + alembic upgrade head, SessionLocal модуля патчится
(тот же паттерн, что в test_admin_players.AdminPlayerListSearchTests):
каждый тест получает свежую disposable БД.

Покрытие:
- create -> политика создана (country_code нормализуется в upper),
  аудит country_policy.created;
- create duplicate country_code (в т.ч. через нижний регистр) -> 409;
- update policy/restricted_features/reason -> обновлено, аудит
  country_policy.updated (before/after); смена country_code ->
  422 (pydantic extra="forbid");
- delete -> политика удалена, аудит country_policy.deleted с before;
- list -> 2 политики, total=2, сортировка по country_code.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_country_policies import (
    CountryPolicyPayload,
    CountryPolicyUpdatePayload,
    create_country_policy,
    delete_country_policy,
    list_country_policies,
    update_country_policy,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


class AdminCountryPoliciesCrudTests(unittest.TestCase):
    """CRUD CountryPolicy на реальной SQLite (alembic upgrade head)."""

    @classmethod
    def setUpClass(cls) -> None:
        from app import admin_country_policies

        cls.admin_country_policies = admin_country_policies
        cls._session_local_patch = None
        cls._temporary_directory = None
        cls.engine = None

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-country-policies-"
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
        self._session_local_patch = patch.object(
            self.admin_country_policies, "SessionLocal", self.SessionLocal
        )
        self._session_local_patch.start()

    def tearDown(self) -> None:
        if self._session_local_patch is not None:
            self._session_local_patch.stop()
        if self.engine is not None:
            self.engine.dispose()
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы ---------------------------------------------

    def _make_admin(self):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                    is_deleted=False,
                )
            )
        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _get_policy(self, policy_id: str):
        from app.models import CountryPolicy

        with self.SessionLocal() as session:
            return session.get(CountryPolicy, policy_id)

    def _find_audits(self, action: str):
        from app.models import AdminAuditLog

        with self.SessionLocal() as session:
            return session.scalars(
                select(AdminAuditLog).where(AdminAuditLog.action == action)
            ).all()



# ---- Тесты ----------------------------------------------------------

    def test_create_country_policy(self) -> None:
        admin = self._make_admin()
        payload = CountryPolicyPayload(
            country_code="ru",
            policy="restricted",
            restricted_features=["transfer"],
            reason="Тестовая политика",
        )

        result = create_country_policy(payload, request=None, admin=admin)
        policy = result["policy"]

        # country_code нормализуется в upper; созданная политика в БД.
        self.assertEqual(policy["countryCode"], "RU")
        self.assertEqual(policy["policy"], "restricted")
        self.assertEqual(policy["restrictedFeatures"], ["transfer"])
        self.assertEqual(policy["reason"], "Тестовая политика")
        self.assertIsNotNone(policy["id"])
        self.assertIsNotNone(policy["createdAt"])
        self.assertIsNotNone(policy["updatedAt"])

        db_policy = self._get_policy(policy["id"])
        self.assertIsNotNone(db_policy)
        self.assertEqual(db_policy.country_code, "RU")

        # Аудит country_policy.created с after-снапшотом.
        audits = self._find_audits("country_policy.created")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].entity_type, "country_policy")
        self.assertEqual(audits[0].entity_id, policy["id"])
        self.assertEqual(audits[0].after_json["countryCode"], "RU")
        self.assertEqual(audits[0].after_json["policy"], "restricted")

    def test_create_duplicate_country_code_conflict(self) -> None:
        admin = self._make_admin()
        create_country_policy(
            CountryPolicyPayload(country_code="DE", policy="blocked"),
            request=None,
            admin=admin,
        )

        # Дубль (даже в нижнем регистре — нормализация DE идёт до проверки).
        with self.assertRaises(HTTPException) as ctx:
            create_country_policy(
                CountryPolicyPayload(country_code="de", policy="allowed"),
                request=None,
                admin=admin,
            )
        self.assertEqual(ctx.exception.status_code, 409)

        # Ровно одна политика и ровно один created-аудит.
        from app.models import CountryPolicy

        with self.SessionLocal.begin() as session:
            rows = session.scalars(select(CountryPolicy)).all()
            self.assertEqual(len(rows), 1)
        self.assertEqual(len(self._find_audits("country_policy.created")), 1)

    def test_update_country_policy_and_cannot_change_country_code(self) -> None:
        admin = self._make_admin()
        created = create_country_policy(
            CountryPolicyPayload(country_code="US", policy="allowed"),
            request=None,
            admin=admin,
        )["policy"]
        policy_id = created["id"]

        result = update_country_policy(
            policy_id,
            CountryPolicyUpdatePayload(
                policy="restricted",
                restricted_features=["mission", "team"],
                reason="Обновлённая причина",
            ),
            request=None,
            admin=admin,
        )
        updated = result["policy"]
        self.assertEqual(updated["countryCode"], "US")
        self.assertEqual(updated["policy"], "restricted")
        self.assertEqual(sorted(updated["restrictedFeatures"]), ["mission", "team"])
        self.assertEqual(updated["reason"], "Обновлённая причина")

        # Аудит country_policy.updated с before/after.
        audits = self._find_audits("country_policy.updated")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].entity_id, policy_id)
        self.assertEqual(audits[0].before_json["policy"], "allowed")
        self.assertEqual(audits[0].after_json["policy"], "restricted")
        self.assertEqual(audits[0].after_json["reason"], "Обновлённая причина")

        # country_code менять нельзя: поля нет в update-палетке,
        # extra="forbid" -> ValidationError (в API — 422).
        with self.assertRaises(ValidationError):
            CountryPolicyUpdatePayload(country_code="CA", policy="allowed")


    def test_delete_country_policy(self) -> None:
        admin = self._make_admin()
        created = create_country_policy(
            CountryPolicyPayload(country_code="GB", policy="blocked", reason="r"),
            request=None,
            admin=admin,
        )["policy"]
        policy_id = created["id"]

        result = delete_country_policy(policy_id, request=None, admin=admin)
        self.assertEqual(result, {"deleted": True})
        self.assertIsNone(self._get_policy(policy_id))

        # Аудит country_policy.deleted с before-снапшотом (аудит переживает
        # hard delete: entity_id — строка без FK на таблицу политики).
        audits = self._find_audits("country_policy.deleted")
        self.assertEqual(len(audits), 1)
        self.assertEqual(audits[0].entity_id, policy_id)
        self.assertEqual(audits[0].before_json["countryCode"], "GB")
        self.assertEqual(audits[0].before_json["policy"], "blocked")

    def test_list_country_policies(self) -> None:
        admin = self._make_admin()
        create_country_policy(
            CountryPolicyPayload(country_code="FR", policy="allowed"),
            request=None,
            admin=admin,
        )
        create_country_policy(
            CountryPolicyPayload(
                country_code="CN",
                policy="restricted",
                restricted_features=["transfer"],
                reason="Китай",
            ),
            request=None,
            admin=admin,
        )

        result = list_country_policies(_admin=admin)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["policies"]), 2)
        self.assertEqual(result["limit"], 20)
        self.assertEqual(result["offset"], 0)
        # Сортировка по country_code.
        self.assertEqual(
            [p["countryCode"] for p in result["policies"]], ["CN", "FR"]
        )
        self.assertEqual(
            result["policies"][0]["restrictedFeatures"], ["transfer"]
        )