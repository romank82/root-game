from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from app.admin_ar_objects import (
    AdminARObjectCreatePayload,
    AdminARObjectUpdatePayload,
    _new_id,
    _normalize_slug,
    _serialize_ar_object,
    _validate_geo_zone_exists,
    _validate_time_window,
)


def _ar_object(**overrides: object) -> SimpleNamespace:
    base: dict[str, object] = {
        "id": "ar-object-1",
        "slug": "tower-sprite",
        "title": "Спрайт башни",
        "description": None,
        "status": "draft",
        "sort_order": 0,
        "geo_zone_id": "geo-zone-1",
        "object_type": "sprite",
        "asset_uri": "https://cdn.example.com/assets/tower.glb",
        "asset_mime_type": None,
        "scene_preset": None,
        "scale_meters": 1.0,
        "orientation": "free",
        "discovery_scenario": {"trigger": "proximity"},
        "minigame_config": {},
        "instruction_text": None,
        "validation_config": {"validator": "qr"},
        "starts_at": None,
        "ends_at": None,
        "created_at": datetime(2026, 5, 1, 12, 30, 45),
        "updated_at": datetime(2026, 5, 2, 9, 0, 0),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class AdminARObjectGeoZoneValidationTests(unittest.TestCase):
    def test_validate_geo_zone_exists_rejects_unknown_zone(self) -> None:
        session = SimpleNamespace(get=lambda *args: None)

        with self.assertRaises(HTTPException) as captured:
            _validate_geo_zone_exists(session, "geo-zone-missing")

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("geo_zone_id", captured.exception.detail)

    def test_validate_geo_zone_exists_accepts_existing_zone(self) -> None:
        session = SimpleNamespace(
            get=lambda *args: SimpleNamespace(id="geo-zone-1")
        )

        try:
            _validate_geo_zone_exists(session, "geo-zone-1")
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"Существующая зона не должна отклоняться: {exc.detail}")

    def test_validate_geo_zone_exists_looks_up_by_geo_zone_id(self) -> None:
        seen: dict[str, str] = {}

        def fake_get(_model: object, entity_id: str) -> SimpleNamespace:
            seen["id"] = entity_id
            return SimpleNamespace(id=entity_id)

        session = SimpleNamespace(get=fake_get)

        _validate_geo_zone_exists(session, "geo-zone-42")

        self.assertEqual(seen["id"], "geo-zone-42")


class AdminARObjectTimeWindowValidationTests(unittest.TestCase):
    def test_validate_time_window_allows_both_none(self) -> None:
        try:
            _validate_time_window(None, None)
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"Оба None должны проходить: {exc.detail}")

    def test_validate_time_window_allows_only_starts(self) -> None:
        try:
            _validate_time_window(datetime(2026, 6, 1, 10, 0, 0), None)
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"Только starts_at должен проходить: {exc.detail}")

    def test_validate_time_window_allows_only_ends(self) -> None:
        try:
            _validate_time_window(None, datetime(2026, 6, 1, 10, 0, 0))
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"Только ends_at должен проходить: {exc.detail}")

    def test_validate_time_window_rejects_starts_after_ends(self) -> None:
        starts = datetime(2026, 6, 2, 10, 0, 0)
        ends = datetime(2026, 6, 1, 10, 0, 0)

        with self.assertRaises(HTTPException) as captured:
            _validate_time_window(starts, ends)

        self.assertEqual(captured.exception.status_code, 422)
        self.assertIn("starts_at", captured.exception.detail)

    def test_validate_time_window_allows_starts_equals_ends(self) -> None:
        moment = datetime(2026, 6, 1, 10, 0, 0)

        try:
            _validate_time_window(moment, moment)
        except HTTPException as exc:  # pragma: no cover
            self.fail(f"starts_at == ends_at должен проходить: {exc.detail}")

    def test_validate_time_window_normalizes_naive_and_aware(self) -> None:
        # SQLite возвращает naive, pydantic может отдать aware-значение;
        # сравнение должно выполняться в UTC без TypeError.
        naive = datetime(2026, 6, 1, 12, 0, 0)  # трактуется как UTC
        aware = datetime(2026, 6, 1, 12, 0, 1, tzinfo=timezone.utc)

        with self.assertRaises(HTTPException) as captured:
            _validate_time_window(aware, naive)

        self.assertEqual(captured.exception.status_code, 422)


class AdminARObjectSlugNormalizationTests(unittest.TestCase):
    def test_normalize_slug_strips_and_lowercases(self) -> None:
        self.assertEqual(_normalize_slug("  Tower-Sprite  "), "tower-sprite")

    def test_normalize_slug_rejects_invalid_characters(self) -> None:
        with self.assertRaises(HTTPException) as captured:
            _normalize_slug("tower sprite")

        self.assertEqual(captured.exception.status_code, 422)

    def test_normalize_slug_rejects_empty_after_strip(self) -> None:
        with self.assertRaises(HTTPException) as captured:
            _normalize_slug("   ")

        self.assertEqual(captured.exception.status_code, 422)


class AdminARObjectSerializationTests(unittest.TestCase):
    def test_serialize_maps_all_fields_to_camel_case_with_iso_dates(self) -> None:
        obj = _ar_object(
            starts_at=datetime(2026, 6, 1, 7, 0, 0),
            ends_at=datetime(2026, 7, 1, 23, 59, 59),
            scale_meters=1.5,
            orientation="upright",
        )

        serialized = _serialize_ar_object(obj)

        self.assertEqual(serialized["id"], "ar-object-1")
        self.assertEqual(serialized["slug"], "tower-sprite")
        self.assertEqual(serialized["title"], "Спрайт башни")
        self.assertIsNone(serialized["description"])
        self.assertEqual(serialized["status"], "draft")
        self.assertEqual(serialized["sortOrder"], 0)
        self.assertEqual(serialized["geoZoneId"], "geo-zone-1")
        self.assertEqual(serialized["objectType"], "sprite")
        self.assertEqual(
            serialized["assetUri"], "https://cdn.example.com/assets/tower.glb"
        )
        self.assertIsNone(serialized["assetMimeType"])
        self.assertIsNone(serialized["scenePreset"])
        self.assertEqual(serialized["scaleMeters"], 1.5)
        self.assertEqual(serialized["orientation"], "upright")
        self.assertIsNone(serialized["instructionText"])
        self.assertEqual(serialized["startsAt"], "2026-06-01T07:00:00")
        self.assertEqual(serialized["endsAt"], "2026-07-01T23:59:59")
        self.assertEqual(serialized["createdAt"], "2026-05-01T12:30:45")
        self.assertEqual(serialized["updatedAt"], "2026-05-02T09:00:00")

    def test_serialize_preserves_json_dicts(self) -> None:
        obj = _ar_object(
            discovery_scenario={"trigger": "proximity", "radiusMeters": 20},
            minigame_config={"type": "tap", "sequence": ["a", "b"]},
            validation_config={"validator": "qr", "qrSecret": "s3cr3t"},
        )

        serialized = _serialize_ar_object(obj)

        self.assertEqual(
            serialized["discoveryScenario"],
            {"trigger": "proximity", "radiusMeters": 20},
        )
        self.assertEqual(
            serialized["minigameConfig"],
            {"type": "tap", "sequence": ["a", "b"]},
        )
        self.assertEqual(
            serialized["validationConfig"],
            {"validator": "qr", "qrSecret": "s3cr3t"},
        )

    def test_serialize_none_guards_optional_fields(self) -> None:
        obj = _ar_object(
            description=None,
            asset_mime_type=None,
            scene_preset=None,
            instruction_text=None,
            starts_at=None,
            ends_at=None,
            created_at=None,
            updated_at=None,
        )

        serialized = _serialize_ar_object(obj)

        for key in (
            "description",
            "assetMimeType",
            "scenePreset",
            "instructionText",
            "startsAt",
            "endsAt",
            "createdAt",
            "updatedAt",
        ):
            self.assertIsNone(serialized[key], f"Поле {key} должно быть None")


class AdminARObjectIdTests(unittest.TestCase):
    def test_new_id_uses_prefix_and_is_unique(self) -> None:
        ids = {_new_id("ar-object") for _ in range(100)}

        self.assertEqual(len(ids), 100)
        self.assertTrue(all(item.startswith("ar-object-") for item in ids))


class AdminARObjectPayloadContractTests(unittest.TestCase):
    def test_create_payload_accepts_minimal_payload_with_defaults(self) -> None:
        payload = AdminARObjectCreatePayload(
            slug="minimal-object",
            title="Minimal",
            geo_zone_id="zone-1",
            object_type="model",
            asset_uri="s3://bucket/object.glb",
        )

        self.assertEqual(payload.sort_order, 0)
        self.assertEqual(payload.discovery_scenario, {})
        self.assertEqual(payload.minigame_config, {})
        self.assertEqual(payload.validation_config, {})
        self.assertIsNone(payload.description)
        self.assertIsNone(payload.starts_at)
        self.assertIsNone(payload.ends_at)

    def test_create_payload_rejects_short_slug(self) -> None:
        with self.assertRaises(ValidationError):
            AdminARObjectCreatePayload(
                slug="ab", title="T", geo_zone_id="z", object_type="m", asset_uri="a"
            )

    def test_create_payload_rejects_empty_geo_zone_id(self) -> None:
        with self.assertRaises(ValidationError):
            AdminARObjectCreatePayload(
                slug="abc", title="T", geo_zone_id="", object_type="m", asset_uri="a"
            )

    def test_create_payload_rejects_overlong_asset_uri(self) -> None:
        with self.assertRaises(ValidationError):
            AdminARObjectCreatePayload(
                slug="abc",
                title="T",
                geo_zone_id="z",
                object_type="m",
                asset_uri="a" * 513,
            )

    def test_create_payload_rejects_out_of_range_sort_order(self) -> None:
        with self.assertRaises(ValidationError):
            AdminARObjectCreatePayload(
                slug="abc",
                title="T",
                geo_zone_id="z",
                object_type="m",
                asset_uri="a",
                sort_order=-1,
            )
        with self.assertRaises(ValidationError):
            AdminARObjectCreatePayload(
                slug="abc",
                title="T",
                geo_zone_id="z",
                object_type="m",
                asset_uri="a",
                sort_order=100_001,
            )

    def test_create_payload_rejects_overlong_object_type(self) -> None:
        with self.assertRaises(ValidationError):
            AdminARObjectCreatePayload(
                slug="abc",
                title="T",
                geo_zone_id="z",
                object_type="m" * 65,
                asset_uri="a",
            )

    def test_update_payload_accepts_partial_fields(self) -> None:
        payload = AdminARObjectUpdatePayload(
            status="published", sort_order=7, geo_zone_id="zone-9"
        )

        self.assertEqual(payload.status, "published")
        self.assertEqual(payload.sort_order, 7)
        self.assertEqual(payload.geo_zone_id, "zone-9")
        self.assertIsNone(payload.slug)
        self.assertIsNone(payload.title)

    def test_update_payload_defaults_to_all_none(self) -> None:
        payload = AdminARObjectUpdatePayload()

        self.assertIsNone(payload.slug)
        self.assertIsNone(payload.status)
        self.assertIsNone(payload.starts_at)
        self.assertIsNone(payload.discovery_scenario)

    def test_update_payload_rejects_overlong_slug(self) -> None:
        with self.assertRaises(ValidationError):
            AdminARObjectUpdatePayload(slug="a" * 129)


if __name__ == "__main__":
    unittest.main()
