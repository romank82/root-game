"""Contract tests for app.runtime_policy_contract.

Pure tests: no database, no HTTP client, no fixtures. They pin the shape and
bounds declared in docs/solo-mission-runtime-policy-contract.md and guard the
invariant that a normalized policy can be validated again when it is read back.
"""

from __future__ import annotations

import copy
import unittest
from decimal import Decimal

from app.runtime_policy_contract import (
    RuntimePolicyValidationError,
    multiplier_scale_factor,
    scaled_attempt_multipliers,
    validate_challenge_policy,
    validate_fallback_policy,
    validate_feature_flags,
    validate_required_items,
    validate_reward_policy,
    validate_runtime_policy,
)


def _policy(**overrides):
    policy = {
        "mission_category": "solo",
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
            "rewards": [
                {"rewardType": "root", "amountAtomic": 100},
                {"rewardType": "item", "itemId": "item-1", "quantity": 1},
            ],
        },
        "fallback_policy_json": None,
        "feature_flags_json": {},
    }
    policy.update(overrides)
    return policy


def _reward_policy(multipliers, rewards=None):
    return {
        "schemaVersion": 1,
        "attemptMultipliers": multipliers,
        "rewards": [] if rewards is None else rewards,
    }


class RuntimePolicyContractTests(unittest.TestCase):
    def test_baseline_policy_is_accepted(self):
        snapshot = validate_runtime_policy(**_policy())
        self.assertEqual(snapshot["missionType"], "solo")
        self.assertEqual(snapshot["maxAttempts"], 3)
        self.assertEqual(snapshot["fallbackPolicy"], None)
        self.assertEqual(snapshot["featureFlags"], {})

    def test_all_known_mission_categories_accepted(self):
        for category in ("solo", "team", "race", "co-op"):
            with self.subTest(mission_category=category):
                snapshot = validate_runtime_policy(**_policy(mission_category=category))
                self.assertEqual(snapshot["missionType"], "solo")
                self.assertEqual(snapshot["maxAttempts"], 3)

    def test_missing_mission_category_is_legacy_allowed(self):
        # Callers that predate the participation category do not pass it; the
        # policy is still validated (mission_type no longer gates anything).
        snapshot = validate_runtime_policy(**_policy(mission_category=None))
        self.assertEqual(snapshot["missionType"], "solo")

    def test_validation_does_not_mutate_input(self):
        policy = _policy()
        original = copy.deepcopy(policy)
        validate_runtime_policy(**policy)
        self.assertEqual(policy, original)

    def test_scalar_bounds(self):
        accepted = (
            {"entry_root_atomic": 2_147_483_647},
            {"max_attempts": 1, "reward_policy_json": _reward_policy([1.0])},
            {
                "max_attempts": 10,
                "reward_policy_json": _reward_policy([1.0] + [0.5] * 9),
            },
        )
        for overrides in accepted:
            with self.subTest(overrides=overrides):
                validate_runtime_policy(**_policy(**overrides))

        rejected = (
            {"mission_category": "unknown"},
            {"mission_category": 5},
            {"entry_root_atomic": -1},
            {"entry_root_atomic": 2_147_483_648},
            {"entry_root_atomic": True},
            {"max_attempts": 0},
            {"max_attempts": 11},
            {"repeatability_policy": "after_success"},
            {"repeatability_policy": "one-time"},
        )
        for overrides in rejected:
            with self.subTest(overrides=overrides):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_runtime_policy(**_policy(**overrides))

    def test_required_items(self):
        validate_required_items(
            {
                "schemaVersion": 1,
                "items": [
                    {"itemId": "key-%d" % index, "quantity": 1}
                    for index in range(100)
                ],
            }
        )
        validate_required_items(
            {
                "schemaVersion": 1,
                "items": [{"itemId": "key-1", "quantity": 2_147_483_647}],
            }
        )

        rejected = (
            {
                "schemaVersion": 1,
                "items": [
                    {"itemId": "k", "quantity": 1},
                    {"itemId": "k", "quantity": 1},
                ],
            },
            {"schemaVersion": 1, "items": [{"itemId": "k", "quantity": 0}]},
            {
                "schemaVersion": 1,
                "items": [{"itemId": "k", "quantity": 2_147_483_648}],
            },
            {"schemaVersion": 1, "items": {}},
            {"schemaVersion": 1, "items": [{"itemId": "", "quantity": 1}]},
            {
                "schemaVersion": 1,
                "items": [{"itemId": "k", "quantity": 1, "extra": 1}],
            },
            {"schemaVersion": 2, "items": []},
            {"items": []},
            {
                "schemaVersion": 1,
                "items": [
                    {"itemId": "key-%d" % index, "quantity": 1}
                    for index in range(101)
                ],
            },
        )
        for value in rejected:
            with self.subTest(value=str(value)[:48]):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_required_items(value)

    def test_challenge_policy(self):
        validate_challenge_policy(
            {
                "schemaVersion": 1,
                "challengeType": "cipher",
                "drumCount": 12,
                "alphabet": ["S%d" % index for index in range(64)],
                "falseChoicesPerDrum": 16,
            }
        )
        validate_challenge_policy(
            {
                "schemaVersion": 1,
                "challengeType": "cipher",
                "drumCount": 1,
                "alphabet": ["A", "B"],
                "falseChoicesPerDrum": 0,
            }
        )

        def config(**overrides):
            value = {
                "schemaVersion": 1,
                "challengeType": "cipher",
                "drumCount": 1,
                "alphabet": ["A", "B"],
                "falseChoicesPerDrum": 0,
            }
            value.update(overrides)
            return value

        rejected = (
            config(challengeType="text"),
            config(drumCount=0),
            config(drumCount=13),
            config(alphabet=["A"]),
            config(alphabet=["S%d" % index for index in range(65)]),
            config(alphabet=["A", "a"]),
            config(alphabet=["A", "\uff21"]),
            config(alphabet=["A", " A"]),
            config(alphabet=["A", "B" * 9]),
            config(alphabet=["A", 1]),
            config(falseChoicesPerDrum=17),
            config(extra=1),
        )
        for value in rejected:
            with self.subTest(value=str(value)[:48]):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_challenge_policy(value)

    def test_multiplier_accepted_forms(self):
        accepted = (
            [1.0, 0.5, 0.25],
            [1, 0.5, "0.25"],
            ["1", "0.5", "0.25"],
            ["1.0", "0.50", "0.250"],
        )
        for multipliers in accepted:
            with self.subTest(multipliers=multipliers):
                result = validate_reward_policy(
                    _reward_policy(multipliers),
                    max_attempts=3,
                )
                self.assertEqual(
                    result["attemptMultipliers"],
                    ["1", "0.5", "0.25"],
                )

    def test_multiplier_rejections(self):
        rejected = (
            [1.0, 0.5],
            [1.0, 0.5, 0.25, 0.1],
            [0.5, 0.5, 0.25],
            [1.0, 0.25, 0.5],
            [1.0, 0.5, 0.1234567],
            [True, 0.5, 0.25],
            [1.0, 0.5, "1e-1"],
            [1.0, 0.5, " 0.25"],
            [1.0, 0.5, "0.25 "],
            [1.0, 0.5, "+0.25"],
            [1.0, 0.5, "-1"],
            [1.0, 0.5, "\u0661"],
            [1.0, 0.5, None],
        )
        for multipliers in rejected:
            with self.subTest(multipliers=multipliers):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_reward_policy(
                        _reward_policy(multipliers),
                        max_attempts=3,
                    )

    def test_reward_entries(self):
        validate_reward_policy(
            _reward_policy(
                [1.0, 0.5, 0.25],
                [{"rewardType": "root", "amountAtomic": 2_147_483_647}],
            ),
            max_attempts=3,
        )
        validate_reward_policy(_reward_policy([1.0, 0.5, 0.25]), max_attempts=3)

        rejected = (
            [
                {"rewardType": "root", "amountAtomic": 1},
                {"rewardType": "root", "amountAtomic": 2},
            ],
            [{"rewardType": "root", "amountAtomic": 0}],
            [{"rewardType": "root", "amountAtomic": 2_147_483_648}],
            [{"rewardType": "root"}],
            [{"rewardType": "story_node", "storyNodeId": "node-1"}],
            [{"rewardType": "currency", "amountAtomic": 5}],
            [{"rewardType": "item", "quantity": 1}],
            [{"rewardType": "item", "itemId": "item-1", "quantity": 0}],
            [
                {"rewardType": "item", "itemId": "item-1", "quantity": 1},
                {"rewardType": "item", "itemId": "item-1", "quantity": 1},
            ],
            [
                {
                    "rewardType": "item",
                    "itemId": "item-1",
                    "quantity": 1,
                    "amountAtomic": 5,
                }
            ],
        )
        for rewards in rejected:
            with self.subTest(rewards=str(rewards)[:48]):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_reward_policy(
                        _reward_policy([1.0, 0.5, 0.25], rewards),
                        max_attempts=3,
                    )

        with self.assertRaises(RuntimePolicyValidationError):
            validate_reward_policy(
                {
                    "schemaVersion": 1,
                    "attemptMultipliers": [1.0, 0.5, 0.25],
                    "rewards": [],
                    "extra": 1,
                },
                max_attempts=3,
            )

    def test_fallback_and_feature_flags(self):
        validate_fallback_policy(None)
        for value in ({}, {"enabled": False}, "none", 0):
            with self.subTest(value=value):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_fallback_policy(value)

        self.assertEqual(validate_feature_flags({}), {})
        for value in (
            {"demo": True},
            {"features.demo_seed_enabled": True},
            [],
            None,
        ):
            with self.subTest(value=value):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_feature_flags(value)

    def test_normalized_policy_can_be_validated_again(self):
        snapshot = validate_runtime_policy(**_policy())
        stored = _policy(
            required_items_json=snapshot["requiredItems"],
            challenge_policy_json=snapshot["challengePolicy"],
            reward_policy_json=snapshot["rewardPolicy"],
            feature_flags_json=snapshot["featureFlags"],
        )
        self.assertEqual(validate_runtime_policy(**stored), snapshot)

        repeated = validate_runtime_policy(**stored)
        self.assertEqual(repeated, snapshot)
        self.assertEqual(repeated["rewardPolicy"]["attemptMultipliers"], ["1", "0.5", "0.25"])

    def test_scaled_attempt_multipliers(self):
        snapshot = validate_runtime_policy(**_policy())
        self.assertEqual(
            scaled_attempt_multipliers(snapshot["rewardPolicy"]),
            [1_000_000, 500_000, 250_000],
        )
        self.assertEqual(multiplier_scale_factor(Decimal("0.333333")), 333_333)
        with self.assertRaises(RuntimePolicyValidationError):
            multiplier_scale_factor(Decimal("0.1234567"))

    def test_challenge_optional_for_solo(self):
        # Solo / race / co-op missions may omit the cipher challenge entirely;
        # the normalized snapshot then stores challengePolicy: None.
        for category in ("solo", "race", "co-op"):
            with self.subTest(mission_category=category):
                snapshot = validate_runtime_policy(
                    **_policy(mission_category=category, challenge_policy_json=None)
                )
                self.assertIsNone(snapshot["challengePolicy"])
                self.assertIsNone(
                    validate_runtime_policy(
                        **_policy(
                            mission_category=category,
                            challenge_policy_json={},
                        )
                    )["challengePolicy"]
                )

    def test_challenge_required_for_team(self):
        for value in (None, {}):
            with self.subTest(challenge_policy_json=value):
                with self.assertRaises(RuntimePolicyValidationError):
                    validate_runtime_policy(
                        **_policy(
                            mission_category="team",
                            challenge_policy_json=value,
                        )
                    )

        # A non-empty challenge for a team mission is still validated normally.
        snapshot = validate_runtime_policy(
            **_policy(mission_category="team")
        )
        self.assertEqual(snapshot["challengePolicy"]["challengeType"], "cipher")


if __name__ == "__main__":
    unittest.main()
