import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.admin_missions import (
    _validate_for_publish,
    _validate_public_mission_content,
    _validate_team_mission_config,
)
from app.geo_team_contract import validate_team_mission_validation_config
from app.admin_segments import _validate_public_segment_content


def valid_mission_content() -> dict:
    return {
        "schemaVersion": 1,
        "ui": {
            "label": "PUBLIC CHECK",
            "question": "Public question",
            "inputPlaceholder": "Enter answer",
        },
    }


def valid_segment_content() -> dict:
    return {
        "schemaVersion": 1,
        "presentation": {
            "code": "TEST-SEGMENT",
            "type": "ARCHIVE_SEGMENT",
        },
        "location": {
            "searchRadiusMeters": 250,
            "safeScanRadiusMeters": 15,
            "safeScanPoint": {
                "latitude": 54.0,
                "longitude": 82.0,
            },
        },
        "arScene": {
            "scenePreset": "archive_cube_v1",
            "scanHoldDurationMs": 1800,
        },
    }


def invalid_team_validation_config() -> dict:
    return {
        "schemaVersion": 1,
        "team": {"matchmakingMode": "unsupported", "minMembers": 2, "maxMembers": 4},
    }


def valid_team_validation_config() -> dict:
    return {
        "schemaVersion": 1,
        "team": {
            "matchmakingMode": "local_matchmaking",
            "minMembers": 2,
            "maxMembers": 4,
        },
        "economy": {
            "entryFeeRootAtomic": 0,
            "requiredItems": [],
        },
        "attempts": {
            "maxAttempts": 1,
            "rewardMultipliers": [1.0],
        },
        "geo": {
            "zoneId": "zone-test",
            "proofFreshnessSeconds": 60,
            "pairwiseProximityMeters": 20,
            "periodicCheckPolicy": {
                "mode": "none",
                "intervalSeconds": 0,
            },
        },
        "activation": {
            "challengeType": "cipher",
            "deadlineSeconds": 120,
            "qrMode": "protected_qr_v1",
        },
        "fallback": {
            "enabled": False,
            "quotaPerPlayer": 0,
        },
    }


class AdminPublicContentValidationTests(unittest.TestCase):
    def test_accepts_valid_mission_content(self) -> None:
        _validate_public_mission_content("text_answer", valid_mission_content())

    def test_rejects_mission_content_without_echoing_sensitive_value(self) -> None:
        content = valid_mission_content()
        content["ui"]["acceptedAnswers"] = ["sensitive-answer"]

        with self.assertRaises(HTTPException) as captured:
            _validate_public_mission_content("text_answer", content)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Публичный content Mission не соответствует опубликованному контракту.",
        )
        self.assertNotIn("sensitive-answer", captured.exception.detail)

    def test_rejects_invalid_team_config_without_echoing_value(self) -> None:
        config = invalid_team_validation_config()
        config["team"]["matchmakingMode"] = "secret-value-must-not-echo"

        with self.assertRaises(HTTPException) as captured:
            _validate_team_mission_config(config)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Защищённая конфигурация team Mission не соответствует контракту.",
        )
        self.assertNotIn("secret-value-must-not-echo", captured.exception.detail)

    def test_publish_validation_accepts_complete_team_configuration(self) -> None:
        mission = SimpleNamespace(
            mission_type="team",
            content={
                "schemaVersion": 1,
                "ui": {"label": "TEAM", "instruction": "Join nearby players."},
            },
            validation_config=valid_team_validation_config(),
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
            id="mission-test",
        )
        session = SimpleNamespace(
            scalars=lambda _statement: SimpleNamespace(all=lambda: []),
        )

        with (
            patch(
                "app.admin_missions._validate_references"
            ) as validate_references,
            patch(
                "app.admin_missions._validate_rewards"
            ) as validate_rewards,
            patch(
                "app.admin_missions.validate_team_mission_validation_config",
                wraps=validate_team_mission_validation_config,
            ) as validate_team_config,
        ):
            _validate_for_publish(session, mission)

        validate_references.assert_called_once_with(
            session,
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
        )
        validate_team_config.assert_called_once_with(mission.validation_config)
        validate_rewards.assert_called_once_with(session, [])

    def test_publish_validation_rejects_invalid_team_configuration_safely(self) -> None:
        mission = SimpleNamespace(
            mission_type="team",
            content={
                "schemaVersion": 1,
                "ui": {"label": "TEAM", "instruction": "Join nearby players."},
            },
            validation_config=invalid_team_validation_config(),
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
        )
        session = SimpleNamespace()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Защищённая конфигурация team Mission не соответствует контракту.",
        )

    def test_accepts_valid_segment_content(self) -> None:
        _validate_public_segment_content(valid_segment_content())

    def test_rejects_segment_content_without_echoing_sensitive_value(self) -> None:
        content = valid_segment_content()
        content["arScene"]["validationConfig"] = {
            "acceptedAnswers": ["sensitive-answer"],
        }

        with self.assertRaises(HTTPException) as captured:
            _validate_public_segment_content(content)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Публичный content Segment не соответствует опубликованному контракту.",
        )
        self.assertNotIn("sensitive-answer", captured.exception.detail)


if __name__ == "__main__":
    unittest.main()
