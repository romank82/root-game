"""Admin API tests for MissionRuntimePolicy.

Covers Pydantic schema bounds, contract validation reuse, serialization and
lifecycle integration (version increments, publish/archive, PATCH restrictions,
idempotency, item-published checks) against an Alembic-created disposable SQLite
database.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.admin_mission_runtime_policies import (
    AdminMissionRuntimePolicyCreatePayload,
    AdminMissionRuntimePolicyUpdatePayload,
    MissionRuntimePolicyUpsertPayload,
    _policy_arguments,
    _serialize_policy,
    _validate_policy_via_contract,
    _validate_publish_dependencies,
    archive_admin_mission_runtime_policy,
    create_admin_mission_runtime_policy,
    get_admin_mission_runtime_policy,
    get_mission_runtime_policy,
    list_admin_mission_runtime_policies,
    publish_admin_mission_runtime_policy,
    unpublish_admin_mission_runtime_policy,
    update_admin_mission_runtime_policy,
    upsert_mission_runtime_policy,
)
from app.models import Item

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


def _policy_dict(**overrides):
    """A contract-valid policy payload; every scalar at its default bound."""
    policy = {
        "mission_id": "mission-1",
        "entry_root_atomic": 0,
        "max_attempts": 3,
        "repeatability_policy": "after_failure_only",
        "required_items_json": {
            "schemaVersion": 1,
            "items": [{"itemId": "key-1", "quantity": 2}],
        },
        "challenge_policy_json": {
            "schemaVersion": 1,
            "challengeType": "cipher",
            "drumCount": 4,
            "alphabet": ["A", "B", "C", "D"],
            "falseChoicesPerDrum": 2,
        },
        "reward_policy_json": {
            "schemaVersion": 1,
            "attemptMultipliers": [1.0, 0.5, 0.25],
            "rewards": [{"rewardType": "root", "amountAtomic": 100}],
        },
        "fallback_policy_json": None,
        "feature_flags_json": {},
    }
    policy.update(overrides)
    return policy


class _FakeSession:
    """Minimal session for publish-dependency checks (GET only)."""

    def __init__(self, items):
        self._items = items

    def get(self, model, entity_id):
        if model is Item:
            return self._items.get(entity_id)
        return None
class MissionRuntimePolicySchemaTests(unittest.TestCase):
    """Pydantic payload bounds: types, lengths, and numeric ranges."""

    def test_create_payload_valid_minimal_accepted(self):
        payload = AdminMissionRuntimePolicyCreatePayload(**_policy_dict())
        self.assertEqual(payload.mission_id, "mission-1")
        self.assertEqual(payload.max_attempts, 3)
        self.assertIsNone(payload.fallback_policy_json)
        self.assertEqual(payload.feature_flags_json, {})

    def test_create_payload_requires_mission_id(self):
        data = _policy_dict()
        data.pop("mission_id")
        with self.assertRaises(ValidationError):
            AdminMissionRuntimePolicyCreatePayload(**data)

    def test_create_payload_mission_id_over_max_length_rejected(self):
        with self.assertRaises(ValidationError):
            AdminMissionRuntimePolicyCreatePayload(**_policy_dict(mission_id="m" * 65))

    def test_create_payload_negative_entry_root_rejected(self):
        with self.assertRaises(ValidationError):
            AdminMissionRuntimePolicyCreatePayload(**_policy_dict(entry_root_atomic=-1))

    def test_create_payload_entry_root_over_max_rejected(self):
        with self.assertRaises(ValidationError):
            AdminMissionRuntimePolicyCreatePayload(
                **_policy_dict(entry_root_atomic=2_147_483_648)
            )

    def test_create_payload_zero_max_attempts_rejected(self):
        with self.assertRaises(ValidationError):
            AdminMissionRuntimePolicyCreatePayload(**_policy_dict(max_attempts=0))

    def test_create_payload_max_attempts_over_max_rejected(self):
        with self.assertRaises(ValidationError):
            AdminMissionRuntimePolicyCreatePayload(**_policy_dict(max_attempts=11))

    def test_create_payload_requires_json_policies(self):
        data = _policy_dict()
        data.pop("reward_policy_json")
        with self.assertRaises(ValidationError):
            AdminMissionRuntimePolicyCreatePayload(**data)

    def test_update_payload_allows_empty_body(self):
        payload = AdminMissionRuntimePolicyUpdatePayload()
        self.assertEqual(payload.model_dump(exclude_unset=True), {})

    def test_update_payload_valid_partial_body_accepted(self):
        payload = AdminMissionRuntimePolicyUpdatePayload(max_attempts=5)
        self.assertEqual(payload.max_attempts, 5)
        self.assertIsNone(payload.entry_root_atomic)


class ContractViaRouterValidationTests(unittest.TestCase):
    """The router delegates full structural validation to the contract."""

    def _validate(self, mission_category="solo", **overrides):
        mission = SimpleNamespace(id="mission-1", mission_category=mission_category)
        payload = _policy_dict(**overrides)
        return _validate_policy_via_contract(
            mission,
            **_policy_arguments(
                mission_id=payload["mission_id"],
                entry_root_atomic=payload["entry_root_atomic"],
                max_attempts=payload["max_attempts"],
                repeatability_policy=payload["repeatability_policy"],
                required_items_json=payload["required_items_json"],
                challenge_policy_json=payload["challenge_policy_json"],
                reward_policy_json=payload["reward_policy_json"],
                fallback_policy_json=payload["fallback_policy_json"],
                feature_flags_json=payload["feature_flags_json"],
            ),
        )

    def test_valid_policy_is_accepted_and_normalized(self):
        normalized = self._validate()
        self.assertEqual(normalized["missionType"], "solo")
        self.assertEqual(normalized["maxAttempts"], 3)

    def test_duplicate_required_item_ids_rejected(self):
        required = {
            "schemaVersion": 1,
            "items": [
                {"itemId": "key-1", "quantity": 1},
                {"itemId": "key-1", "quantity": 2},
            ],
        }
        with self.assertRaises(HTTPException) as context:
            self._validate(required_items_json=required)
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("unique", str(context.exception.detail))

    def test_negative_entry_root_rejected(self):
        with self.assertRaises(HTTPException) as context:
            self._validate(entry_root_atomic=-1)
        self.assertEqual(context.exception.status_code, 422)

    def test_unknown_repeatability_policy_rejected(self):
        with self.assertRaises(HTTPException) as context:
            self._validate(repeatability_policy="three_times")
        self.assertEqual(context.exception.status_code, 422)

    def test_multiplier_count_mismatch_rejected(self):
        reward = {
            "schemaVersion": 1,
            "attemptMultipliers": [1.0, 0.5],
            "rewards": [{"rewardType": "root", "amountAtomic": 100}],
        }
        with self.assertRaises(HTTPException) as context:
            self._validate(reward_policy_json=reward)
        self.assertEqual(context.exception.status_code, 422)

    def test_unknown_mission_category_rejected(self):
        with self.assertRaises(HTTPException) as context:
            self._validate(mission_category="unknown")
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("missionCategory", str(context.exception.detail))

    def test_team_category_policy_is_accepted(self):
        # A team-category mission may carry the same entry/challenge policy:
        # members complete the format individually. mission_type no longer gates.
        normalized = self._validate(mission_category="team")
        self.assertEqual(normalized["missionType"], "solo")
        self.assertEqual(normalized["maxAttempts"], 3)
class PublishDependencyValidationTests(unittest.TestCase):
    """Publish-time DB-backed item checks."""

    def _normalized(self):
        from app.runtime_policy_contract import validate_runtime_policy

        payload = _policy_dict()
        return validate_runtime_policy(
            mission_category="solo",
            entry_root_atomic=payload["entry_root_atomic"],
            max_attempts=payload["max_attempts"],
            repeatability_policy=payload["repeatability_policy"],
            required_items_json=payload["required_items_json"],
            challenge_policy_json=payload["challenge_policy_json"],
            reward_policy_json=payload["reward_policy_json"],
            fallback_policy_json=payload["fallback_policy_json"],
            feature_flags_json=payload["feature_flags_json"],
        )

    def test_missing_required_item_rejected(self):
        with self.assertRaises(HTTPException) as context:
            _validate_publish_dependencies(_FakeSession({}), self._normalized())
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("key-1", str(context.exception.detail))

    def test_unpublished_required_item_rejected(self):
        items = {"key-1": SimpleNamespace(status="draft")}
        with self.assertRaises(HTTPException) as context:
            _validate_publish_dependencies(_FakeSession(items), self._normalized())
        self.assertEqual(context.exception.status_code, 422)

    def test_all_published_items_accepted(self):
        items = {"key-1": SimpleNamespace(status="published")}
        result = _validate_publish_dependencies(_FakeSession(items), self._normalized())
        self.assertIsNone(result)


class SerializationTests(unittest.TestCase):
    def _policy(self):
        return SimpleNamespace(
            id="policy-1",
            mission_id="mission-1",
            version=2,
            status="draft",
            entry_root_atomic=0,
            max_attempts=3,
            repeatability_policy="after_failure_only",
            required_items_json={"schemaVersion": 1, "items": []},
            challenge_policy_json={"challengeType": "cipher"},
            reward_policy_json={"rewards": []},
            fallback_policy_json=None,
            feature_flags_json={},
            created_at=datetime(2026, 10, 6, 12, 0, 0, tzinfo=timezone.utc),
            updated_at=datetime(2026, 10, 6, 12, 5, 0, tzinfo=timezone.utc),
        )

    def test_serialize_policy_camel_case_with_iso_dates(self):
        serialized = _serialize_policy(self._policy())
        self.assertEqual(serialized["missionId"], "mission-1")
        self.assertEqual(serialized["entryRootAtomic"], 0)
        self.assertEqual(serialized["version"], 2)
        self.assertEqual(serialized["createdAt"], "2026-10-06T12:00:00+00:00")
        self.assertEqual(serialized["updatedAt"], "2026-10-06T12:05:00+00:00")

    def test_serialize_policy_preserves_json_fields(self):
        serialized = _serialize_policy(self._policy())
        self.assertEqual(
            serialized["requiredItemsJson"], {"schemaVersion": 1, "items": []}
        )
        self.assertEqual(serialized["challengePolicyJson"], {"challengeType": "cipher"})
        self.assertIsNone(serialized["fallbackPolicyJson"])
        self.assertEqual(serialized["featureFlagsJson"], {})
class MissionRuntimePolicyLifecycleIntegrationTests(unittest.TestCase):
    """Real endpoint functions against an Alembic-created disposable SQLite DB."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-policy-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "policy.sqlite3"
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

        cls.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(cls.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        import app.admin_mission_runtime_policies as router_module

        cls.router_module = router_module
        cls._session_local_patch = patch.object(
            router_module,
            "SessionLocal",
            cls.SessionLocal,
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def _fixture(
        self, *, mission_type="text_answer", mission_category="solo", item_status="published"
    ):
        from app.models import AdminUser, Chapter, Item, Mission, Season

        suffix = uuid.uuid4().hex
        ids = {
            "season": f"season-{suffix}",
            "chapter": f"chapter-{suffix}",
            "mission": f"mission-{suffix}",
            "item": f"key-{suffix}",
            "admin": f"admin-{suffix}",
        }

        with self.SessionLocal.begin() as session:
            session.add(
                Season(
                    id=ids["season"],
                    slug=f"season-{suffix}",
                    title="Policy season",
                    description="Isolated integration fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                Chapter(
                    id=ids["chapter"],
                    season_id=ids["season"],
                    slug=f"chapter-{suffix}",
                    title="Policy chapter",
                    description="Isolated integration fixture",
                    status="published",
                    sort_order=1,
                )
            )
            session.flush()
            session.add(
                Mission(
                    id=ids["mission"],
                    chapter_id=ids["chapter"],
                    slug=f"mission-{suffix}",
                    mission_type=mission_type,
                    mission_category=mission_category,
                    title="Solo mission",
                    description="Isolated integration fixture",
                    content={"schemaVersion": 1},
                    validation_config={},
                    status="published",
                    sort_order=1,
                )
            )
            session.add(
                Item(
                    id=ids["item"],
                    slug=f"item-{suffix}",
                    code=f"ITEM-{suffix[:12]}",
                    title="Key",
                    description="Isolated integration fixture",
                    symbol="◇",
                    category="key",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status=item_status,
                )
            )
            session.add(
                AdminUser(
                    id=ids["admin"],
                    username=f"policy-admin-{suffix}",
                    password_hash="not-a-real-hash",
                    role="super_admin",
                    is_super_admin=True,
                    is_active=True,
                )
            )
        return ids

    def _admin(self, admin_id: str):
        from app.models import AdminUser

        with self.SessionLocal.begin() as session:
            return session.get(AdminUser, admin_id)

    def _payload_for(self, ids: dict[str, str], **overrides):
        data = _policy_dict(**overrides)
        data["mission_id"] = ids["mission"]
        data["required_items_json"] = {
            "schemaVersion": 1,
            "items": [{"itemId": ids["item"], "quantity": 2}],
        }
        return data

    def test_integration_create_assigns_version_one(self):
        ids = self._fixture()
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))

        response = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )
        created = response["missionRuntimePolicy"]

        self.assertEqual(created["missionId"], ids["mission"])
        self.assertEqual(created["version"], 1)
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["repeatabilityPolicy"], "after_failure_only")

    def test_integration_second_policy_gets_next_version(self):
        ids = self._fixture()
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))

        first = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]
        second = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]

        self.assertEqual(first["version"], 1)
        self.assertEqual(second["version"], 2)

    def test_integration_publish_archives_previous_published_version(self):
        ids = self._fixture()
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))

        first = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]
        second = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]

        published_first = publish_admin_mission_runtime_policy(
            first["id"], request=None, admin=admin
        )["missionRuntimePolicy"]
        self.assertEqual(published_first["status"], "published")

        published_second = publish_admin_mission_runtime_policy(
            second["id"], request=None, admin=admin
        )["missionRuntimePolicy"]
        self.assertEqual(published_second["status"], "published")

        stored_first = get_admin_mission_runtime_policy(
            first["id"], _admin=None
        )["missionRuntimePolicy"]
        self.assertEqual(stored_first["status"], "archived")

    def test_integration_patch_published_policy_rejected(self):
        ids = self._fixture()
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))
        policy = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]
        publish_admin_mission_runtime_policy(policy["id"], request=None, admin=admin)

        with self.assertRaises(HTTPException) as context:
            update_admin_mission_runtime_policy(
                policy["id"],
                AdminMissionRuntimePolicyUpdatePayload(max_attempts=5),
                request=None,
                admin=admin,
            )
        self.assertEqual(context.exception.status_code, 409)

    def test_integration_patch_archived_policy_rejected(self):
        ids = self._fixture()
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))
        policy = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]
        archive_admin_mission_runtime_policy(policy["id"], request=None, admin=admin)

        with self.assertRaises(HTTPException) as context:
            update_admin_mission_runtime_policy(
                policy["id"],
                AdminMissionRuntimePolicyUpdatePayload(max_attempts=5),
                request=None,
                admin=admin,
            )
        self.assertEqual(context.exception.status_code, 409)

    def test_integration_publish_requires_published_items(self):
        ids = self._fixture(item_status="draft")
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))
        policy = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]

        with self.assertRaises(HTTPException) as context:
            publish_admin_mission_runtime_policy(
                policy["id"], request=None, admin=admin
            )
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn(ids["item"], str(context.exception.detail))

    def test_integration_publish_already_published_is_idempotent(self):
        ids = self._fixture()
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))
        policy = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]

        publish_admin_mission_runtime_policy(policy["id"], request=None, admin=admin)
        again = publish_admin_mission_runtime_policy(
            policy["id"], request=None, admin=admin
        )["missionRuntimePolicy"]
        self.assertEqual(again["status"], "published")

        with self.SessionLocal.begin() as session:
            from app.geo_team_runtime_models import MissionRuntimePolicy

            published = session.scalars(
                select(MissionRuntimePolicy).where(
                    MissionRuntimePolicy.mission_id == ids["mission"],
                    MissionRuntimePolicy.status == "published",
                )
            ).all()
        self.assertEqual(len(published), 1)

    def test_integration_create_succeeds_for_text_answer_mission(self):
        # mission_type no longer gates policy creation: a text-answer (solo)
        # mission carries the runtime policy for its entry flow.
        ids = self._fixture(mission_type="text_answer", mission_category="solo")
        admin = self._admin(ids["admin"])
        payload = AdminMissionRuntimePolicyCreatePayload(**self._payload_for(ids))

        created = create_admin_mission_runtime_policy(
            payload, request=None, admin=admin
        )["missionRuntimePolicy"]
        self.assertEqual(created["missionId"], ids["mission"])
        self.assertEqual(created["status"], "draft")
        self.assertEqual(created["version"], 1)

    def test_get_policy_returns_null_when_missing(self):
        ids = self._fixture(mission_type="text_answer", mission_category="solo")
        admin = self._admin(ids["admin"])
        result = get_mission_runtime_policy(ids["mission"], _actor=admin)
        self.assertEqual(result, {"runtimePolicy": None})

    def test_get_policy_404_for_unknown_mission(self):
        ids = self._fixture()
        admin = self._admin(ids["admin"])
        with self.assertRaises(HTTPException) as context:
            get_mission_runtime_policy("mission-does-not-exist", _actor=admin)
        self.assertEqual(context.exception.status_code, 404)

    def test_put_creates_policy_for_solo_mission(self):
        ids = self._fixture(mission_type="text_answer", mission_category="solo")
        admin = self._admin(ids["admin"])

        first = upsert_mission_runtime_policy(
            ids["mission"],
            MissionRuntimePolicyUpsertPayload(entry_root_atomic=50),
            request=None,
            actor=admin,
        )["runtimePolicy"]
        self.assertEqual(first["entryRootAtomic"], 50)
        self.assertEqual(first["version"], 1)
        self.assertEqual(first["status"], "draft")

        # Умный PUT: draft существует — обновляем его на месте, id и version
        # не меняются, содержимое меняется.
        second = upsert_mission_runtime_policy(
            ids["mission"],
            MissionRuntimePolicyUpsertPayload(entry_root_atomic=100),
            request=None,
            actor=admin,
        )["runtimePolicy"]
        self.assertEqual(second["id"], first["id"])
        self.assertEqual(second["version"], 1)
        self.assertEqual(second["status"], "draft")
        self.assertEqual(second["entryRootAtomic"], 100)

    def test_put_new_version_after_publish(self):
        ids = self._fixture(mission_type="text_answer", mission_category="solo")
        admin = self._admin(ids["admin"])

        first = upsert_mission_runtime_policy(
            ids["mission"],
            MissionRuntimePolicyUpsertPayload(entry_root_atomic=50),
            request=None,
            actor=admin,
        )["runtimePolicy"]
        published = publish_admin_mission_runtime_policy(
            first["id"], request=None, admin=admin
        )["missionRuntimePolicy"]
        self.assertEqual(published["status"], "published")

        # После публикации draft нет — PUT создаёт новую draft-версию,
        # опубликованная policy не трогается.
        second = upsert_mission_runtime_policy(
            ids["mission"],
            MissionRuntimePolicyUpsertPayload(entry_root_atomic=100),
            request=None,
            actor=admin,
        )["runtimePolicy"]
        self.assertEqual(second["version"], 2)
        self.assertEqual(second["status"], "draft")
        self.assertEqual(second["entryRootAtomic"], 100)
        self.assertNotEqual(second["id"], first["id"])

        # Старая published-версия на месте и по-прежнему обслуживается GET.
        stored = get_mission_runtime_policy(ids["mission"], _actor=admin)[
            "runtimePolicy"
        ]
        self.assertEqual(stored["id"], first["id"])
        self.assertEqual(stored["version"], 1)
        self.assertEqual(stored["status"], "published")
        self.assertEqual(stored["entryRootAtomic"], 50)

        # Всего две версии: published v1 и новая draft v2.
        with self.SessionLocal.begin() as session:
            from app.geo_team_runtime_models import MissionRuntimePolicy

            rows = session.scalars(
                select(MissionRuntimePolicy)
                .where(MissionRuntimePolicy.mission_id == ids["mission"])
                .order_by(MissionRuntimePolicy.version)
            ).all()
        self.assertEqual(
            [(row.version, row.status, row.entry_root_atomic) for row in rows],
            [(1, "published", 50), (2, "draft", 100)],
        )

    def test_put_validates_required_items(self):
        ids = self._fixture(mission_type="text_answer", mission_category="solo")
        admin = self._admin(ids["admin"])
        payload = MissionRuntimePolicyUpsertPayload(
            entry_root_atomic=50,
            required_items_json={"items": [{"itemId": "item-x", "quantity": 1}]},
        )
        with self.assertRaises(HTTPException) as context:
            upsert_mission_runtime_policy(
                ids["mission"], payload, request=None, actor=admin
            )
        self.assertEqual(context.exception.status_code, 422)

    def test_put_team_mission_requires_challenge(self):
        ids = self._fixture(mission_type="text_answer", mission_category="team")
        admin = self._admin(ids["admin"])
        payload = MissionRuntimePolicyUpsertPayload(entry_root_atomic=50)
        with self.assertRaises(HTTPException) as context:
            upsert_mission_runtime_policy(
                ids["mission"], payload, request=None, actor=admin
            )
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("challengePolicy", str(context.exception.detail))


if __name__ == "__main__":
    unittest.main()