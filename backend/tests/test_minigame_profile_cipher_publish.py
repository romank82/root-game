"""Sprint 8.17.12: автотесты для published-ветки cipher после 8.17.14–8.17.19 + hotfix.

Покрывает:
- (а) cipher + published-профиль + пустой content.ui -> publish OK (8.17.16 gate
      require_full_cipher_ui=False; correctCombination не требуется — hotfix 8.17.18);
- (б) cipher + published-профиль + неполный content.ui -> publish OK (8.17.16);
- (в) cipher + draft/archived-профиль + пустой content.ui -> 422 (no published
      profile => legacy full-ui требования);
- (г) legacy cipher без профиля + пустой content.ui -> 422 (8.17.16 legacy-путь
      и 8.17.19 «профиль обязателен»);
- (д) _resolve_minigame_settings (8.17.15): published-профиль -> profile.settings,
      legacy без профиля -> content.ui.

Стиль: SimpleNamespace-стабы (как test_admin_content_validation.py), без in-memory SQLite.
"""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.admin_missions import _validate_for_publish
from app.mission_engine import _resolve_minigame_settings


PROFILE_ID = "cipher-profile-test"


def _make_profile(
    *,
    status: str = "published",
    settings: dict | None = None,
    profile_id: str = PROFILE_ID,
) -> SimpleNamespace:
    """Профиль мини-игры: published/draft/archived с настройками cipher."""
    return SimpleNamespace(
        id=profile_id,
        name="Cipher Test Profile",
        game_type="cipher",
        settings=settings
        if settings is not None
        else {"drumCount": 5, "falseChoicesPerDrum": 10, "timeLimitSeconds": 30},
        status=status,
    )


def _make_mission(
    *,
    minigame_profile_id: str | None = None,
    content: dict | None = None,
    validation_config: dict | None = None,
) -> SimpleNamespace:
    """Mission для публикации: по умолчанию cipher, все publish-обязательные поля заданы."""
    return SimpleNamespace(
        id="mission-test",
        mission_type="cipher",
        mission_layer="solo",
        content=content if content is not None else {"schemaVersion": 1, "ui": {}},
        validation_config=validation_config
        if validation_config is not None
        else {"validator": "cipher_match"},
        chapter_id="chapter-test",
        story_node_id=None,
        geo_zone_id="zone-test",
        ar_object_id="ar-test",
        minigame_profile_id=minigame_profile_id,
        status="published",
    )


def _make_session(profile: SimpleNamespace | None = None):
    """Стаб-сессия: .get(MinigameProfile, id) и .scalars(...) (как в test_admin_content_validation)."""

    class _SessionStub:
        def get(self, model, key):
            if model.__name__ == "MinigameProfile" and profile is not None and key == profile.id:
                return profile
            return None

        def scalars(self, _statement):
            return SimpleNamespace(all=lambda: [])

    return _SessionStub()


class AdminPublishCipherProfileTests(unittest.TestCase):
    """Тесты (а)-(г): поведение _validate_for_publish для published/draft/legacy cipher."""

    def test_publish_accepts_published_profile_empty_content_ui(self) -> None:
        """(а) Sprint 8.17.16+18: published-профиль + пустой content.ui + без
        correctCombination (генер. на backend) -> publish OK (не бросает)."""
        profile = _make_profile(status="published")
        mission = _make_mission(
            minigame_profile_id=profile.id,
            content={"schemaVersion": 1, "ui": {}},
            validation_config={"validator": "cipher_match"},
        )
        session = _make_session(profile)

        with (
            patch("app.admin_missions._validate_references"),
            patch("app.admin_missions._validate_rewards"),
        ):
            result = _validate_for_publish(session, mission)

        self.assertIsNone(result)

    def test_publish_accepts_published_profile_partial_content_ui(self) -> None:
        """(б) Sprint 8.17.16: published-профиль + content.ui без drumCount/
        alphabet/combination -> publish OK (требования полного ui сняты)."""
        profile = _make_profile(status="published")
        mission = _make_mission(
            minigame_profile_id=profile.id,
            content={
                "schemaVersion": 1,
                "ui": {"label": "x", "instruction": "y"},
            },
            validation_config={"validator": "cipher_match"},
        )
        session = _make_session(profile)

        with (
            patch("app.admin_missions._validate_references"),
            patch("app.admin_missions._validate_rewards"),
        ):
            result = _validate_for_publish(session, mission)

        self.assertIsNone(result)

    def test_publish_rejects_draft_or_archived_profile_empty_content_ui(self) -> None:
        """(в) Sprint 8.17.16: draft/archived-профиль — НЕ published, ->
        require_full_cipher_ui=True, пустой content.ui отклоняется (422)."""
        for status in ("draft", "archived"):
            with self.subTest(status=status):
                profile = _make_profile(status=status)
                mission = _make_mission(
                    minigame_profile_id=profile.id,
                    content={"schemaVersion": 1, "ui": {}},
                    validation_config={"validator": "cipher_match"},
                )
                session = _make_session(profile)

                with (
                    patch("app.admin_missions._validate_references"),
                    patch("app.admin_missions._validate_rewards"),
                ):
                    with self.assertRaises(HTTPException) as captured:
                        _validate_for_publish(session, mission)

                self.assertEqual(captured.exception.status_code, 422)

    def test_publish_rejects_legacy_without_profile_empty_content_ui(self) -> None:
        """(г) Sprint 8.17.16/8.17.19: legacy cipher без профиля + пустой
        content.ui -> 422 (полный ui обязателен; профиль обязателен)."""
        mission = _make_mission(
            minigame_profile_id=None,
            content={"schemaVersion": 1, "ui": {}},
            validation_config={"validator": "cipher_match"},
        )
        session = _make_session(profile=None)

        with (
            patch("app.admin_missions._validate_references"),
            patch("app.admin_missions._validate_rewards"),
        ):
            with self.assertRaises(HTTPException) as captured:
                _validate_for_publish(session, mission)

        self.assertEqual(captured.exception.status_code, 422)


class ResolveMinigameSettingsTests(unittest.TestCase):
    """Тест (д): _resolve_minigame_settings приоритет profile.settings vs content.ui."""

    def test_published_profile_settings_override_content_ui(self) -> None:
        """(д1) Sprint 8.17.15: published-профиль -> profile.settings,
        даже если content.ui задан."""
        profile = _make_profile(
            status="published",
            settings={"drumCount": 5, "falseChoicesPerDrum": 10, "timeLimitSeconds": 30},
        )
        mission = _make_mission(
            minigame_profile_id=profile.id,
            content={
                "schemaVersion": 1,
                "ui": {
                    "drumCount": 4,
                    "falseChoicesPerDrum": 2,
                    "alphabet": ["R", "O", "T"],
                    "combination": "ROOT",
                },
            },
        )
        session = _make_session(profile)

        settings = _resolve_minigame_settings(session, mission)

        self.assertEqual(
            settings,
            {"drumCount": 5, "falseChoicesPerDrum": 10, "timeLimitSeconds": 30},
        )
        self.assertNotEqual(settings.get("drumCount"), 4)

    def test_legacy_without_profile_uses_content_ui(self) -> None:
        """(д2) Sprint 8.17.15: миссия без профиля -> legacy content.ui."""
        mission = _make_mission(
            minigame_profile_id=None,
            content={
                "schemaVersion": 1,
                "ui": {
                    "drumCount": 4,
                    "falseChoicesPerDrum": 2,
                    "alphabet": ["R", "O", "T"],
                    "combination": "ROOT",
                },
            },
        )
        session = _make_session(profile=None)

        settings = _resolve_minigame_settings(session, mission)

        self.assertEqual(
            settings,
            {
                "drumCount": 4,
                "falseChoicesPerDrum": 2,
                "alphabet": ["R", "O", "T"],
                "combination": "ROOT",
            },
        )

    def test_draft_profile_falls_back_to_content_ui(self) -> None:
        """(д-доп) Sprint 8.17.15: draft-профиль НЕ считается источником —
        берётся legacy content.ui (зеркало gate из admin_missions)."""
        profile = _make_profile(
            status="draft",
            settings={"drumCount": 7, "falseChoicesPerDrum": 1},
        )
        mission = _make_mission(
            minigame_profile_id=profile.id,
            content={
                "schemaVersion": 1,
                "ui": {"drumCount": 4, "falseChoicesPerDrum": 2},
            },
        )
        session = _make_session(profile)

        settings = _resolve_minigame_settings(session, mission)

        self.assertEqual(settings, {"drumCount": 4, "falseChoicesPerDrum": 2})


if __name__ == "__main__":
    unittest.main()

