from datetime import datetime
from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from app.admin_geo_zones import (
    AdminGeoZoneCreatePayload,
    AdminGeoZoneUpdatePayload,
    _normalize_slug,
    _resolve_effective,
    _serialize_geo_zone,
    _validate_geo_zone,
)


def _effective(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "zone_type": "radius",
        "latitude": 55.7558,
        "longitude": 37.6173,
        "radius_meters": 500,
        "search_radius_meters": 3000,
        "polygon_coordinates": None,
        "timezone": "UTC",
        "starts_at": None,
        "ends_at": None,
    }
    base.update(overrides)
    return base


class AdminGeoZonesValidationTests(unittest.TestCase):
    def _assert_422(self, effective: dict[str, object], fragment: str) -> None:
        with self.assertRaises(HTTPException) as captured:
            _validate_geo_zone(effective)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn(fragment, captured.exception.detail)

    def _assert_ok(self, effective: dict[str, object]) -> None:
        try:
            _validate_geo_zone(effective)
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"Валидация не должна падать: {exc.detail}")

    def test_validate_geo_zone_rejects_unknown_zone_type(self) -> None:
        self._assert_422(_effective(zone_type="wormhole"), "zone_type")

    def test_validate_geo_zone_radius_rejects_lon_without_lat(self) -> None:
        self._assert_422(_effective(latitude=None), "latitude/longitude")

    def test_validate_geo_zone_radius_rejects_lat_without_lon(self) -> None:
        self._assert_422(_effective(longitude=None), "latitude/longitude")

    def test_validate_geo_zone_radius_rejects_missing_radius_meters(self) -> None:
        self._assert_422(_effective(radius_meters=None), "radius_meters")

    def test_validate_geo_zone_radius_rejects_polygon_coordinates(self) -> None:
        self._assert_422(
            _effective(
                polygon_coordinates=[[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]]
            ),
            "polygon_coordinates",
        )

    def test_validate_geo_zone_radius_accepts_valid_zone(self) -> None:
        self._assert_ok(_effective())

    def test_validate_geo_zone_radius_accepts_without_coordinates(self) -> None:
        self._assert_ok(_effective(latitude=None, longitude=None))

    def test_validate_geo_zone_polygon_rejects_missing_polygon_coordinates(
        self,
    ) -> None:
        self._assert_422(
            _effective(
                zone_type="polygon",
                latitude=None,
                longitude=None,
                radius_meters=None,
                polygon_coordinates=None,
            ),
            "polygon_coordinates",
        )

    def test_validate_geo_zone_polygon_rejects_two_points(self) -> None:
        self._assert_422(
            _effective(
                zone_type="polygon",
                latitude=None,
                longitude=None,
                radius_meters=None,
                polygon_coordinates=[[0.0, 0.0], [1.0, 1.0]],
            ),
            "минимум 3",
        )

    def test_validate_geo_zone_polygon_rejects_latitude_out_of_range(self) -> None:
        self._assert_422(
            _effective(
                zone_type="polygon",
                latitude=None,
                longitude=None,
                radius_meters=None,
                polygon_coordinates=[[91.0, 0.0], [1.0, 1.0], [2.0, 2.0]],
            ),
            "polygon_coordinates",
        )

    def test_validate_geo_zone_polygon_rejects_longitude_out_of_range(self) -> None:
        self._assert_422(
            _effective(
                zone_type="polygon",
                latitude=None,
                longitude=None,
                radius_meters=None,
                polygon_coordinates=[[0.0, 181.0], [1.0, 1.0], [2.0, 2.0]],
            ),
            "polygon_coordinates",
        )

    def test_validate_geo_zone_polygon_rejects_center_coordinates(self) -> None:
        self._assert_422(
            _effective(
                zone_type="polygon",
                latitude=55.7558,
                longitude=None,
                radius_meters=None,
                polygon_coordinates=[[0.0, 0.0], [1.0, 1.0], [2.0, 2.0]],
            ),
            "polygon",
        )

    def test_validate_geo_zone_polygon_accepts_three_points(self) -> None:
        self._assert_ok(
            _effective(
                zone_type="polygon",
                latitude=None,
                longitude=None,
                radius_meters=None,
                polygon_coordinates=[[55.7, 37.6], [55.8, 37.7], [55.75, 37.65]],
            ),
        )

    def test_validate_geo_zone_poi_rejects_missing_latitude(self) -> None:
        self._assert_422(_effective(zone_type="poi", latitude=None), "latitude")

    def test_validate_geo_zone_poi_accepts_with_and_without_radius(self) -> None:
        self._assert_ok(_effective(zone_type="poi"))
        self._assert_ok(_effective(zone_type="poi", radius_meters=None))

    def test_validate_geo_zone_event_rejects_missing_starts_at_and_ends_at(
        self,
    ) -> None:
        self._assert_422(
            _effective(
                zone_type="event",
                starts_at=None,
                ends_at=datetime(2026, 10, 1),
            ),
            "starts_at",
        )
        self._assert_422(
            _effective(
                zone_type="event",
                starts_at=datetime(2026, 10, 1),
                ends_at=None,
            ),
            "ends_at",
        )

    def test_validate_geo_zone_event_rejects_ends_before_starts(self) -> None:
        self._assert_422(
            _effective(
                zone_type="event",
                starts_at=datetime(2026, 10, 2),
                ends_at=datetime(2026, 10, 1),
            ),
            "starts_at",
        )

    def test_validate_geo_zone_event_accepts_valid_interval(self) -> None:
        self._assert_ok(
            _effective(
                zone_type="event",
                starts_at=datetime(2026, 10, 1),
                ends_at=datetime(2026, 10, 2),
            ),
        )

    def test_validate_geo_zone_rejects_empty_timezone(self) -> None:
        self._assert_422(_effective(timezone="   "), "timezone")

    def test_validate_geo_zone_rejects_starts_after_ends_for_any_type(self) -> None:
        self._assert_422(
            _effective(
                starts_at=datetime(2026, 10, 2),
                ends_at=datetime(2026, 10, 1),
            ),
            "starts_at",
        )


class AdminGeoZonesResolveEffectiveTests(unittest.TestCase):
    def test_resolve_effective_merges_existing_with_explicit_update_fields(
        self,
    ) -> None:
        payload = AdminGeoZoneUpdatePayload(radius_meters=1000)
        existing = SimpleNamespace(
            zone_type="radius",
            latitude=55.7558,
            longitude=37.6173,
            radius_meters=500,
            search_radius_meters=3000,
            location_constraints={},
            polygon_coordinates=None,
            timezone="UTC",
            starts_at=None,
            ends_at=None,
        )

        effective = _resolve_effective(payload, existing=existing)

        self.assertEqual(effective["zone_type"], "radius")
        self.assertEqual(effective["latitude"], 55.7558)
        self.assertEqual(effective["longitude"], 37.6173)
        self.assertEqual(effective["radius_meters"], 1000)  # перезаписан
        self.assertEqual(effective["search_radius_meters"], 3000)  # сохранён
        self.assertIsNone(effective["polygon_coordinates"])
        self.assertEqual(effective["timezone"], "UTC")

    def test_resolve_effective_create_uses_payload_directly(self) -> None:
        payload = AdminGeoZoneCreatePayload(
            slug="test-zone",
            title="Test zone",
            zone_type="poi",
            latitude=10.0,
            longitude=20.0,
        )

        effective = _resolve_effective(payload)

        self.assertEqual(effective["zone_type"], "poi")
        self.assertEqual(effective["latitude"], 10.0)
        self.assertIsNone(effective["radius_meters"])


class AdminGeoZonesSerializationTests(unittest.TestCase):
    def test_serialize_geo_zone_maps_camel_case_with_iso_dates(self) -> None:
        zone = SimpleNamespace(
            id="geo-zone-1",
            slug="central-park",
            title="Центральный парк",
            description="Тестовая зона",
            zone_type="radius",
            status="published",
            sort_order=10,
            latitude=55.7558,
            longitude=37.6173,
            radius_meters=500,
            search_radius_meters=3000,
            location_constraints={"avoid_buildings": True, "avoid_water": False},
            polygon_coordinates=None,
            timezone="Europe/Moscow",
            starts_at=datetime(2026, 10, 1, 9, 0, 0),
            ends_at=datetime(2026, 10, 2, 21, 30, 0),
            max_location_accuracy_meters=10,
            minimum_presence_seconds=60,
            created_at=datetime(2026, 5, 1, 12, 30, 45),
            updated_at=datetime(2026, 5, 2, 9, 0, 0),
        )

        serialized = _serialize_geo_zone(zone)

        self.assertEqual(serialized["id"], "geo-zone-1")
        self.assertEqual(serialized["slug"], "central-park")
        self.assertEqual(serialized["title"], "Центральный парк")
        self.assertEqual(serialized["zoneType"], "radius")
        self.assertEqual(serialized["status"], "published")
        self.assertEqual(serialized["sortOrder"], 10)
        self.assertEqual(serialized["latitude"], 55.7558)
        self.assertEqual(serialized["longitude"], 37.6173)
        self.assertEqual(serialized["radiusMeters"], 500)
        self.assertEqual(serialized["searchRadiusMeters"], 3000)
        self.assertEqual(
            serialized["locationConstraints"],
            {"avoid_buildings": True, "avoid_water": False},
        )
        self.assertIsNone(serialized["polygonCoordinates"])
        self.assertEqual(serialized["timezone"], "Europe/Moscow")
        self.assertEqual(serialized["startsAt"], "2026-10-01T09:00:00")
        self.assertEqual(serialized["endsAt"], "2026-10-02T21:30:00")
        self.assertEqual(serialized["maxLocationAccuracyMeters"], 10)
        self.assertEqual(serialized["minimumPresenceSeconds"], 60)
        self.assertEqual(serialized["createdAt"], "2026-05-01T12:30:45")
        self.assertEqual(serialized["updatedAt"], "2026-05-02T09:00:00")

    def test_serialize_geo_zone_preserves_polygon_coordinates(self) -> None:
        points = [[55.7, 37.6], [55.8, 37.7], [55.75, 37.65]]
        zone = SimpleNamespace(
            id="geo-zone-2",
            slug="polygon-zone",
            title="Polygon",
            description=None,
            zone_type="polygon",
            status="draft",
            sort_order=0,
            latitude=None,
            longitude=None,
            radius_meters=None,
            search_radius_meters=None,
            location_constraints={},
            polygon_coordinates=points,
            timezone="UTC",
            starts_at=None,
            ends_at=None,
            max_location_accuracy_meters=None,
            minimum_presence_seconds=0,
            created_at=None,
            updated_at=None,
        )

        serialized = _serialize_geo_zone(zone)

        self.assertEqual(serialized["polygonCoordinates"], points)
        self.assertIs(serialized["polygonCoordinates"], points)

    def test_serialize_geo_zone_maps_optional_nulls_to_none(self) -> None:
        zone = SimpleNamespace(
            id="geo-zone-3",
            slug="minimal-zone",
            title="Minimal",
            description=None,
            zone_type="poi",
            status="draft",
            sort_order=0,
            latitude=10.0,
            longitude=20.0,
            radius_meters=None,
            search_radius_meters=None,
            location_constraints={},
            polygon_coordinates=None,
            timezone="UTC",
            starts_at=None,
            ends_at=None,
            max_location_accuracy_meters=None,
            minimum_presence_seconds=0,
            created_at=None,
            updated_at=None,
        )

        serialized = _serialize_geo_zone(zone)

        self.assertIsNone(serialized["description"])
        self.assertIsNone(serialized["radiusMeters"])
        self.assertIsNone(serialized["searchRadiusMeters"])
        self.assertIsNone(serialized["polygonCoordinates"])
        self.assertIsNone(serialized["startsAt"])
        self.assertIsNone(serialized["endsAt"])
        self.assertIsNone(serialized["maxLocationAccuracyMeters"])
        self.assertIsNone(serialized["createdAt"])
        self.assertIsNone(serialized["updatedAt"])
        self.assertEqual(serialized["locationConstraints"], {})

    def test_serialize_geo_zone_includes_search_radius_meters(self) -> None:
        zone = SimpleNamespace(
            id="geo-zone-4",
            slug="search-radius-zone",
            title="Search radius",
            description=None,
            zone_type="radius",
            status="draft",
            sort_order=0,
            latitude=None,
            longitude=None,
            radius_meters=500,
            search_radius_meters=3000,
            location_constraints={},
            polygon_coordinates=None,
            timezone="UTC",
            starts_at=None,
            ends_at=None,
            max_location_accuracy_meters=None,
            minimum_presence_seconds=0,
            created_at=None,
            updated_at=None,
        )

        serialized = _serialize_geo_zone(zone)

        self.assertEqual(serialized["searchRadiusMeters"], 3000)


class AdminGeoZonesSlugTests(unittest.TestCase):
    def test_normalize_slug_lowercases_and_strips(self) -> None:
        self.assertEqual(_normalize_slug("  Central-Park-2026  "), "central-park-2026")
        self.assertEqual(_normalize_slug("park"), "park")

    def test_normalize_slug_rejects_invalid_characters(self) -> None:
        for raw in ("парк центр", "park!", "park_name", "-park", "park-"):
            with self.assertRaises(HTTPException) as captured:
                _normalize_slug(raw)

            self.assertEqual(captured.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()