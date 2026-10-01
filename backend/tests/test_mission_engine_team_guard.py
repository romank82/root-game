import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.mission_engine import MissionEngineError, _submit_mission_once


class LegacyTeamSubmitGuardTests(unittest.TestCase):
    def test_rejects_team_before_progress_synchronization(self) -> None:
        mission = SimpleNamespace(id="mission-team", mission_type="team")
        session = SimpleNamespace(scalar=Mock(return_value=mission))
        session_context = Mock()
        session_context.__enter__ = Mock(return_value=session)
        session_context.__exit__ = Mock(return_value=False)
        session_local = SimpleNamespace(begin=Mock(return_value=session_context))

        with (
            patch("app.mission_engine.SessionLocal", session_local),
            patch("app.mission_engine._ensure_player") as ensure_player,
            patch(
                "app.mission_engine._synchronize_player_missions"
            ) as synchronize_progress,
        ):
            with self.assertRaises(MissionEngineError) as captured:
                _submit_mission_once(
                    player_id="player-test",
                    mission_id="mission-team",
                )

        self.assertEqual(captured.exception.status_code, 409)
        self.assertEqual(
            captured.exception.detail,
            "Team Mission требует отдельного geo/team runtime API.",
        )
        ensure_player.assert_called_once_with(session, "player-test")
        synchronize_progress.assert_not_called()


if __name__ == "__main__":
    unittest.main()
