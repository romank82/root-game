from __future__ import annotations

import unittest

from app.geo_team_contract import (
    GeoTeamConfigurationError,
    validate_team_mission_validation_config,
)


def valid_team_config() -> dict:
    return {
        "schemaVersion": 1,
        "team": {
            "matchmakingMode": "local_matchmaking",
            "minMembers": 2,
            "maxMembers": 4,
        },
        "economy": {
            "entryFeeRootAtomic": 25,
            "requiredItems": [
                {"itemId": "item-team-key", "quantity": 1},
            ],
        },
        "attempts": {
            "maxAttempts": 3,
            "rewardMultipliers": [1.0, 0.5, 0.25],
        },
        "geo": {
            "zoneId": "zone-central-park",
            "proofFreshnessSeconds": 120,
            "pairwiseProximityMeters": 40,
            "periodicCheckPolicy": {
                "mode": "none",
                "intervalSeconds": 0,
            },
        },
        "activation": {
            "challengeType": "cipher",
            "deadlineSeconds": 300,
            "qrMode": "protected_qr_v1",
        },
        "fallback": {
            "enabled": False,
            "quotaPerPlayer": 0,
        },
    }


class GeoTeamMissionConfigurationTests(unittest.TestCase):
    def test_accepts_complete_valid_configuration_and_returns_copy(self) -> None:
        config = valid_team_config()

        result = validate_team_mission_validation_config(config)

        self.assertEqual(result, config)
        self.assertIsNot(result, config)
        self.assertIsNot(result["team"], config["team"])

    def test_rejects_unknown_and_missing_structure(self) -> None:
        config = valid_team_config()
        config["unexpected"] = "not allowed"

        with self.assertRaises(GeoTeamConfigurationError):
            validate_team_mission_validation_config(config)

        config = valid_team_config()
        del config["geo"]

        with self.assertRaises(GeoTeamConfigurationError):
            validate_team_mission_validation_config(config)

    def test_rejects_duplicate_required_items(self) -> None:
        config = valid_team_config()
        config["economy"]["requiredItems"].append(
            {"itemId": "item-team-key", "quantity": 2}
        )

        with self.assertRaises(GeoTeamConfigurationError):
            validate_team_mission_validation_config(config)

    def test_rejects_increasing_attempt_reward_multipliers(self) -> None:
        config = valid_team_config()
        config["attempts"]["rewardMultipliers"] = [1.0, 0.6, 0.8]

        with self.assertRaises(GeoTeamConfigurationError):
            validate_team_mission_validation_config(config)

    def test_join_proximity_meters_is_optional_and_validated_when_present(self) -> None:
        # Без ключа — ок (optional, runtime-фолбэк 50000).
        config = valid_team_config()
        self.assertNotIn("joinProximityMeters", config["geo"])
        result = validate_team_mission_validation_config(config)
        self.assertNotIn("joinProximityMeters", result["geo"])

        # С корректным ключом — ок, значение сохранено.
        config = valid_team_config()
        config["geo"]["joinProximityMeters"] = 10_000
        result = validate_team_mission_validation_config(config)
        self.assertEqual(result["geo"]["joinProximityMeters"], 10_000)

        # Границы диапазона.
        for edge in (1, 100_000):
            config = valid_team_config()
            config["geo"]["joinProximityMeters"] = edge
            validate_team_mission_validation_config(config)

        # Некорректные значения — ошибка (0, отрицательное, вне диапазона,
        # нецелое, не число).
        for bad in (0, -1, 100_001, "50000", 1.5, True, None):
            config = valid_team_config()
            config["geo"]["joinProximityMeters"] = bad
            with self.assertRaises(GeoTeamConfigurationError):
                validate_team_mission_validation_config(config)

    def test_rejects_invalid_periodic_policy_combination(self) -> None:
        config = valid_team_config()
        config["geo"]["periodicCheckPolicy"] = {
            "mode": "required",
            "intervalSeconds": 0,
        }

        with self.assertRaises(GeoTeamConfigurationError):
            validate_team_mission_validation_config(config)

    def test_rejects_inconsistent_disabled_fallback(self) -> None:
        config = valid_team_config()
        config["fallback"]["offerId"] = "offer-fallback-1"

        with self.assertRaises(GeoTeamConfigurationError):
            validate_team_mission_validation_config(config)

    def test_rejects_invalid_config_without_echoing_sensitive_value(self) -> None:
        config = valid_team_config()
        config["activation"]["qrMode"] = "secret-qr-material-must-not-echo"

        # qrMode is allowed text, so make the configuration invalid elsewhere.
        config["activation"]["challengeType"] = "wrong"
        with self.assertRaises(GeoTeamConfigurationError) as captured:
            validate_team_mission_validation_config(config)

        self.assertEqual(
            str(captured.exception),
            "Protected geo/team mission configuration is invalid.",
        )
        self.assertNotIn(
            "secret-qr-material-must-not-echo",
            str(captured.exception),
        )


if __name__ == "__main__":
    unittest.main()
