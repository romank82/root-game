import math
import random
import unittest

from app.geo_spawn import (
    METERS_PER_DEGREE_LATITUDE,
    SpawnPoint,
    generate_spawn_point,
)


class GenerateSpawnPointTests(unittest.TestCase):
    def test_returns_spawn_point_dataclass(self) -> None:
        result = generate_spawn_point(55.7558, 37.6173, 3000, rng=random.Random(42))
        self.assertIsInstance(result, SpawnPoint)
        self.assertIsInstance(result.latitude, float)
        self.assertIsInstance(result.longitude, float)
        self.assertIsInstance(result.distance_from_center_m, float)

    def test_distance_never_exceeds_search_radius(self) -> None:
        rng = random.Random(42)
        for _ in range(200):
            result = generate_spawn_point(55.7558, 37.6173, 1000, rng=rng)
            self.assertLessEqual(result.distance_from_center_m, 1000.0)
            self.assertGreaterEqual(result.distance_from_center_m, 0.0)

    def test_distance_actually_reaches_far_zone(self) -> None:
        # На 1000 попыток хоть одна точка должна быть ближе к краю радиуса (>= 800м)
        rng = random.Random(42)
        distances = [
            generate_spawn_point(55.7558, 37.6173, 1000, rng=rng).distance_from_center_m
            for _ in range(1000)
        ]
        self.assertGreater(max(distances), 800.0)

    def test_with_zero_radius_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_spawn_point(55.7558, 37.6173, 0)

    def test_with_negative_radius_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_spawn_point(55.7558, 37.6173, -100)

    def test_with_none_radius_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_spawn_point(55.7558, 37.6173, None)  # type: ignore[arg-type]

    def test_invalid_latitude_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_spawn_point(100.0, 37.6173, 1000)
        with self.assertRaises(ValueError):
            generate_spawn_point(-100.0, 37.6173, 1000)

    def test_invalid_longitude_raises(self) -> None:
        with self.assertRaises(ValueError):
            generate_spawn_point(55.7558, 200.0, 1000)
        with self.assertRaises(ValueError):
            generate_spawn_point(55.7558, -200.0, 1000)

    def test_deterministic_with_seeded_rng(self) -> None:
        r1 = generate_spawn_point(55.7558, 37.6173, 3000, rng=random.Random(42))
        r2 = generate_spawn_point(55.7558, 37.6173, 3000, rng=random.Random(42))
        self.assertEqual(r1.latitude, r2.latitude)
        self.assertEqual(r1.longitude, r2.longitude)
        self.assertEqual(r1.distance_from_center_m, r2.distance_from_center_m)

    def test_coordinates_are_close_to_center(self) -> None:
        # Для радиуса 3000м смещение по широте не больше ~0.03°
        result = generate_spawn_point(55.7558, 37.6173, 3000, rng=random.Random(42))
        self.assertLess(abs(result.latitude - 55.7558), 0.05)
        self.assertLess(abs(result.longitude - 37.6173), 0.1)

    def test_longitude_wraps_near_antimeridian(self) -> None:
        # Центр у +180, точка может выйти за границу — должна нормализоваться.
        rng = random.Random(42)
        for _ in range(50):
            result = generate_spawn_point(0.0, 179.99, 5000, rng=rng)
            self.assertGreaterEqual(result.longitude, -180.0)
            self.assertLessEqual(result.longitude, 180.0)

    def test_sqrt_correction_avoids_center_bias(self) -> None:
        # Без sqrt-коррекции среднее расстояние было бы ~ R/2 = 500м.
        # С коррекцией среднее ближе к 2R/3 = ~666м.
        rng = random.Random(42)
        distances = [
            generate_spawn_point(0.0, 0.0, 1000, rng=rng).distance_from_center_m
            for _ in range(2000)
        ]
        avg = sum(distances) / len(distances)
        # Проверяем, что среднее между 600 и 750 (ближе к 2R/3, а не к R/2)
        self.assertGreater(avg, 600.0)
        self.assertLess(avg, 750.0)


if __name__ == "__main__":
    unittest.main()