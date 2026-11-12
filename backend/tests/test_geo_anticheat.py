"""Sprint 8.9.a: unit-тесты чистых функций anti-cheat (geo_anticheat).

Без БД и внешних эффектов: проверяют evaluate_velocity, evaluate_accuracy
и build_signal_payload на пороговых сценариях. Координаты в payload не
попадают — это проверяется отдельно (test_build_signal_payload_no_coords).
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from app.geo_anticheat import (
    ANTICHEAT_ACCURACY_MIN_METERS,
    ANTICHEAT_MAX_SPEED_KMH,
    build_signal_payload,
    evaluate_accuracy,
    evaluate_velocity,
)


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class EvaluateVelocityTests(unittest.TestCase):
    def test_velocity_slow_is_none(self) -> None:
        generated_at = _utc(2026, 11, 12, 10, 0, 0)
        result = evaluate_velocity(
            spawn_latitude=55.75,
            spawn_longitude=37.61,
            generated_at=generated_at,
            scan_at=generated_at + timedelta(hours=1),
            current_latitude=55.7505,
            current_longitude=37.6105,
        )
        self.assertIsNone(result)

    def test_velocity_teleport_is_signal(self) -> None:
        generated_at = _utc(2026, 11, 12, 10, 0, 0)
        # 10 с — выше ANTICHEAT_MIN_ELAPSED_SECONDS, поэтому сигнал ожидается;
        # интервал меньше порога проверяется отдельно (…_elapsed_too_small).
        result = evaluate_velocity(
            spawn_latitude=55.75,
            spawn_longitude=37.61,
            generated_at=generated_at,
            scan_at=generated_at + timedelta(seconds=10),
            current_latitude=55.76,
            current_longitude=37.62,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["signal"], "velocity")
        self.assertGreater(result["speedKmh"], ANTICHEAT_MAX_SPEED_KMH)
        self.assertAlmostEqual(result["distanceKm"], 1.276, places=3)
        self.assertEqual(result["elapsedSeconds"], 10)
        self.assertEqual(result["thresholdKmh"], ANTICHEAT_MAX_SPEED_KMH)

    def test_velocity_elapsed_too_small_is_none(self) -> None:
        generated_at = _utc(2026, 11, 12, 10, 0, 0)
        # Даже при огромном расстоянии: elapsed < MIN_ELAPSED -> пропуск.
        result = evaluate_velocity(
            spawn_latitude=55.75,
            spawn_longitude=37.61,
            generated_at=generated_at,
            scan_at=generated_at + timedelta(seconds=2),
            current_latitude=55.76,
            current_longitude=37.62,
        )
        self.assertIsNone(result)

    def test_velocity_missing_scan_at_is_none(self) -> None:
        result = evaluate_velocity(
            spawn_latitude=55.75,
            spawn_longitude=37.61,
            generated_at=_utc(2026, 11, 12, 10, 0, 0),
            scan_at=None,
            current_latitude=55.76,
            current_longitude=37.62,
        )
        self.assertIsNone(result)


class EvaluateAccuracyTests(unittest.TestCase):
    def test_accuracy_ideal_is_signal(self) -> None:
        result = evaluate_accuracy(accuracy_meters=1.0)
        self.assertIsNotNone(result)
        self.assertEqual(result["signal"], "accuracy")
        self.assertEqual(result["accuracyMeters"], 1.0)
        self.assertEqual(result["thresholdMeters"], ANTICHEAT_ACCURACY_MIN_METERS)

    def test_accuracy_normal_is_none(self) -> None:
        self.assertIsNone(evaluate_accuracy(accuracy_meters=10.0))

    def test_accuracy_missing_is_none(self) -> None:
        self.assertIsNone(evaluate_accuracy(accuracy_meters=None))


class BuildSignalPayloadTests(unittest.TestCase):
    def test_build_signal_payload_no_coords(self) -> None:
        signals = [
            {
                "signal": "velocity",
                "speedKmh": 400.0,
                "distanceKm": 1.2,
                "elapsedSeconds": 11,
                "thresholdKmh": ANTICHEAT_MAX_SPEED_KMH,
            }
        ]
        payload = build_signal_payload(
            mission_id="mission-1",
            zone_id="zone-slug",
            signals=signals,
        )
        self.assertEqual(payload["missionId"], "mission-1")
        self.assertEqual(payload["zoneId"], "zone-slug")
        self.assertEqual(payload["signals"], signals)

        for key in ("latitude", "longitude", "generatedFromLat", "generatedFromLng"):
            self.assertNotIn(key, payload)
        for signal in payload["signals"]:
            for key in ("latitude", "longitude"):
                self.assertNotIn(key, signal)


if __name__ == "__main__":
    unittest.main()