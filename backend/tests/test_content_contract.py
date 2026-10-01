import unittest

from app.content_contract import (
    PublicContentValidationError,
    validate_mission_content,
    validate_segment_content,
)


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


def valid_text_answer_content() -> dict:
    return {
        "schemaVersion": 1,
        "ui": {
            "label": "PUBLIC CHECK",
            "question": "Public question",
            "inputPlaceholder": "Enter answer",
            "successTitle": "Completed",
            "successText": "Reward was granted by the server.",
            "rewardPreview": {
                "text": "Public preview only",
            },
        },
    }


def valid_team_content() -> dict:
    return {
        "schemaVersion": 1,
        "ui": {
            "label": "TEAM CIPHER",
            "instruction": "Join nearby players.",
            "joinTitle": "Join session",
            "joinText": "Wait for a compatible team.",
            "waitingText": "Waiting for players.",
            "readyText": "Team is ready.",
            "activeText": "Challenge is active.",
            "successTitle": "Completed",
            "failureText": "The team attempt ended.",
            "rewardPreview": {"text": "Public preview only"},
        },
    }


def valid_code_repair_content() -> dict:
    return {
        "schemaVersion": 1,
        "ui": {
            "label": "CODE REPAIR",
            "instruction": "Arrange public blocks.",
            "blocks": ["packet.", "signature", "return "],
            "maxBlocks": 3,
            "lineNumber": "017",
            "placeholder": "Select blocks",
            "wrongAnswerText": "Try again.",
        },
    }


class SegmentContentContractTests(unittest.TestCase):
    def test_accepts_documented_minimal_segment_content(self) -> None:
        validate_segment_content(valid_segment_content())

    def test_accepts_valid_optional_ar_scene_extensions(self) -> None:
        content = valid_segment_content()
        content["arScene"]["visibleFaces"] = ["north", "east"]
        content["arScene"]["qrMode"] = "VIRTUAL_FACE_QR"

        validate_segment_content(content)

    def test_rejects_boolean_schema_version(self) -> None:
        content = valid_segment_content()
        content["schemaVersion"] = True

        with self.assertRaises(PublicContentValidationError):
            validate_segment_content(content)

    def test_rejects_invalid_coordinate_and_radius_relation(self) -> None:
        content = valid_segment_content()
        content["location"]["safeScanPoint"]["latitude"] = 91

        with self.assertRaises(PublicContentValidationError):
            validate_segment_content(content)

        content = valid_segment_content()
        content["location"]["searchRadiusMeters"] = 10
        content["location"]["safeScanRadiusMeters"] = 15

        with self.assertRaises(PublicContentValidationError):
            validate_segment_content(content)

    def test_rejects_nested_server_only_validation_key(self) -> None:
        content = valid_segment_content()
        content["arScene"]["validationConfig"] = {
            "acceptedAnswers": ["must-not-be-public"],
        }

        with self.assertRaises(PublicContentValidationError):
            validate_segment_content(content)


class MissionContentContractTests(unittest.TestCase):
    def test_accepts_public_text_answer_content(self) -> None:
        validate_mission_content("text_answer", valid_text_answer_content())

    def test_accepts_public_code_repair_content(self) -> None:
        validate_mission_content("code_repair", valid_code_repair_content())

    def test_accepts_public_team_content_without_runtime_policy(self) -> None:
        validate_mission_content("team", valid_team_content())

    def test_rejects_team_runtime_policy_in_public_content(self) -> None:
        content = valid_team_content()
        content["ui"]["entryFeeRootAtomic"] = 25

        with self.assertRaises(PublicContentValidationError):
            validate_mission_content("team", content)

    def test_rejects_unknown_public_mission_type(self) -> None:
        with self.assertRaises(PublicContentValidationError):
            validate_mission_content("unsupported_type", valid_text_answer_content())

    def test_rejects_nested_protected_answer_and_award_fields(self) -> None:
        for forbidden_key in (
            "acceptedAnswers",
            "correctSequence",
            "validationConfig",
            "walletBalanceAfter",
            "inventoryMutation",
            "completionFlag",
        ):
            with self.subTest(forbidden_key=forbidden_key):
                content = valid_text_answer_content()
                content["ui"]["nested"] = {forbidden_key: "must-not-be-public"}

                with self.assertRaises(PublicContentValidationError):
                    validate_mission_content("text_answer", content)

    def test_rejects_invalid_code_repair_blocks(self) -> None:
        content = valid_code_repair_content()
        content["ui"]["blocks"] = []

        with self.assertRaises(PublicContentValidationError):
            validate_mission_content("code_repair", content)

    def test_rejects_invalid_reward_preview_shape(self) -> None:
        content = valid_text_answer_content()
        content["ui"]["rewardPreview"] = {
            "text": "Public preview",
            "amount": 100,
        }

        with self.assertRaises(PublicContentValidationError):
            validate_mission_content("text_answer", content)


if __name__ == "__main__":
    unittest.main()
