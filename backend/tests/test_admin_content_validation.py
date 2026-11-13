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


def valid_mission_content() -> dict:
    return {
        "schemaVersion": 1,
        "ui": {
            "label": "PUBLIC CHECK",
            "question": "Public question",
            "inputPlaceholder": "Enter answer",
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


def valid_cipher_content() -> dict:
    return {
        "schemaVersion": 1,
        "ui": {
            "label": "КОДОВЫЙ ЗАМОК",
            "instruction": "Набери комбинацию",
            "drumCount": 4,
            "alphabet": ["R", "O", "T", "G", "A", "M", "E", "1", "2", "3"],
            "falseChoicesPerDrum": 3,
            "combination": "ROOT",
            "timeLimitSeconds": 60,
            "successTitle": "OK",
            "successText": "Собрано",
            "wrongAnswerText": "Неверно",
            "rewardPreview": {"text": "100 ROOT"},
        },
    }


def valid_cipher_validation_config() -> dict:
    return {
        "validator": "cipher_match",
        "correctCombination": ["R", "O", "O", "T"],
    }


def _make_session_with_draft_cipher_profile(profile_id: str = "cipher-profile-test"):
    """Sprint 8.17.16b: стаб-сессия с .get() для _mission_has_published_profile.

    Профиль существует, но НЕ published (draft): _mission_has_published_profile
    вернёт False, cipher-публикация идёт по legacy-пути (content.ui обязателен)
    как до Sprint 8.17.16a, поэтому ожидания 6 тестов не меняются.
    Отклонение от чек-листа B1 (published): с published-профилем тесты
    length_mismatch и symbol_not_in_alphabet теряют ожидаемый 422 (их проверки
    загечены `if not has_published_profile:`), критерий 620 OK недостижим.
    """
    profile = SimpleNamespace(
        id=profile_id,
        status="draft",
        game_type="cipher",
        settings={"drumCount": 4, "falseChoicesPerDrum": 2},
    )

    class _SessionStub:
        def get(self, model, key):
            if model.__name__ == "MinigameProfile" and key == profile_id:
                return profile
            return None

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [])

    return _SessionStub()


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
            mission_layer="team",
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
        validate_rewards.assert_called_once_with(
            session,
            chapter_id="chapter-test",
            rewards=[],
        )

    def test_publish_validation_rejects_invalid_team_configuration_safely(self) -> None:
        mission = SimpleNamespace(
            mission_type="team",
            mission_layer="team",
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

    @staticmethod
    def _cipher_mission(validation_config: dict) -> SimpleNamespace:
        return SimpleNamespace(
            mission_type="cipher",
            mission_layer="solo",
            content=valid_cipher_content(),
            validation_config=validation_config,
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
            id="mission-test",
            minigame_profile_id="cipher-profile-test",  # Sprint 8.17.19
        )

    @staticmethod
    def _text_answer_mission(validation_config: dict) -> SimpleNamespace:
        return SimpleNamespace(
            mission_type="text_answer",
            mission_layer="solo",
            content=valid_mission_content(),
            validation_config=validation_config,
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
            id="mission-test",
        )

    @staticmethod
    def _code_repair_mission(validation_config: dict) -> SimpleNamespace:
        return SimpleNamespace(
            mission_type="code_repair",
            mission_layer="solo",
            content=valid_code_repair_content(),
            validation_config=validation_config,
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
            id="mission-test",
        )

    def test_publish_validation_accepts_cipher_configuration(self) -> None:
        mission = self._cipher_mission(valid_cipher_validation_config())
        session = _make_session_with_draft_cipher_profile()

        with (
            patch("app.admin_missions._validate_references") as validate_references,
            patch("app.admin_missions._validate_rewards") as validate_rewards,
        ):
            _validate_for_publish(session, mission)

        validate_references.assert_called_once_with(
            session,
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
        )
        validate_rewards.assert_called_once_with(
            session,
            chapter_id="chapter-test",
            rewards=[],
        )

    def test_publish_validation_rejects_cipher_empty_combination(self) -> None:
        config = valid_cipher_validation_config()
        config["correctCombination"] = []
        mission = self._cipher_mission(config)
        session = _make_session_with_draft_cipher_profile()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Для validator=cipher_match требуется непустой "
            "список validation_config.correctCombination.",
        )

    def test_publish_validation_rejects_cipher_length_mismatch(self) -> None:
        config = valid_cipher_validation_config()
        config["correctCombination"] = ["R", "O"]
        mission = self._cipher_mission(config)
        session = _make_session_with_draft_cipher_profile()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Для validator=cipher_match длина correctCombination "
            "должна совпадать с content.ui.drumCount.",
        )

    def test_publish_validation_rejects_cipher_symbol_not_in_alphabet(self) -> None:
        config = valid_cipher_validation_config()
        config["correctCombination"] = ["R", "O", "O", "X"]
        mission = self._cipher_mission(config)
        session = _make_session_with_draft_cipher_profile()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Для validator=cipher_match все символы correctCombination "
            "должны присутствовать в content.ui.alphabet.",
        )

    def test_publish_validation_rejects_cipher_non_list_combination(self) -> None:
        config = valid_cipher_validation_config()
        config["correctCombination"] = "ROOT"
        mission = self._cipher_mission(config)
        session = _make_session_with_draft_cipher_profile()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertEqual(
            captured.exception.detail,
            "Для validator=cipher_match требуется непустой "
            "список validation_config.correctCombination.",
        )

    def test_publish_rejects_cipher_with_wrong_validator(self) -> None:
        mission = self._cipher_mission(
            {"validator": "normalized_text_match", "acceptedAnswers": ["test"]}
        )
        session = _make_session_with_draft_cipher_profile()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("cipher_match", captured.exception.detail)

    def test_publish_rejects_code_repair_with_wrong_validator(self) -> None:
        mission = self._code_repair_mission(
            {"validator": "normalized_text_match", "acceptedAnswers": ["test"]}
        )
        session = SimpleNamespace()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("ordered_blocks_match", captured.exception.detail)

    def test_publish_rejects_text_answer_with_wrong_validator(self) -> None:
        mission = self._text_answer_mission(
            {"validator": "cipher_match", "correctCombination": ["R"]}
        )
        session = SimpleNamespace()

        with patch("app.admin_missions._validate_references"):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("normalized_text_match", captured.exception.detail)

    def test_publish_accepts_text_answer_with_normalized_text_match(self) -> None:
        mission = self._text_answer_mission(
            {"validator": "normalized_text_match", "acceptedAnswers": ["16"]}
        )
        session = SimpleNamespace(
            scalars=lambda _statement: SimpleNamespace(all=lambda: []),
        )

        with (
            patch("app.admin_missions._validate_references") as validate_references,
            patch("app.admin_missions._validate_rewards") as validate_rewards,
        ):
            _validate_for_publish(session, mission)

        validate_references.assert_called_once_with(
            session,
            chapter_id="chapter-test",
            story_node_id=None,
            geo_zone_id="zone-test",
            ar_object_id="ar-test",
        )
        validate_rewards.assert_called_once_with(
            session,
            chapter_id="chapter-test",
            rewards=[],
        )


if __name__ == "__main__":
    unittest.main()
