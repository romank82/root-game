from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminUser, GeoZone
from app.slug_utils import _normalize_slug


router = APIRouter(prefix="/api/v1/admin/geo-zones", tags=["admin-geo-zones"])

GEO_ZONES_READ_PERMISSION = "geo_zones.read"
GEO_ZONES_MANAGE_PERMISSION = "geo_zones.manage"
VALID_ZONE_TYPES = {"radius", "polygon", "poi", "event"}
VALID_ZONE_STATUSES = {"draft", "published", "archived"}


class AdminGeoZoneCreatePayload(BaseModel):
    slug: str = Field(min_length=3, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    zone_type: str = Field(default="radius", min_length=1, max_length=32)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_meters: int | None = Field(default=None, ge=1, le=100_000)
    search_radius_meters: int | None = Field(default=None, ge=1, le=100_000)
    location_constraints: dict[str, Any] = Field(default_factory=dict)
    polygon_coordinates: list[list[float]] | None = Field(default=None)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    starts_at: datetime | None = Field(default=None)
    ends_at: datetime | None = Field(default=None)
    max_location_accuracy_meters: int | None = Field(default=None, ge=0)
    minimum_presence_seconds: int = Field(default=0, ge=0)


class AdminGeoZoneUpdatePayload(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    zone_type: str | None = Field(default=None, min_length=1, max_length=32)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_meters: int | None = Field(default=None, ge=1, le=100_000)
    search_radius_meters: int | None = Field(default=None, ge=1, le=100_000)
    location_constraints: dict[str, Any] | None = None
    polygon_coordinates: list[list[float]] | None = Field(default=None)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    starts_at: datetime | None = Field(default=None)
    ends_at: datetime | None = Field(default=None)
    max_location_accuracy_meters: int | None = Field(default=None, ge=0)
    minimum_presence_seconds: int | None = Field(default=None, ge=0)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _resolve_effective(
    payload: AdminGeoZoneCreatePayload | AdminGeoZoneUpdatePayload,
    existing: GeoZone | None = None,
) -> dict[str, Any]:
    """
    Build the effective geo-zone state used for cross-field validation.

    Create — the payload itself is the effective state.
    Update — existing zone values overlaid with explicitly provided fields,
    so a partial PATCH is validated against the resulting state: each field
    that is not sent keeps its current value, an explicit null clears it.
    """
    if isinstance(payload, AdminGeoZoneCreatePayload):
        return {
            "zone_type": payload.zone_type,
            "latitude": payload.latitude,
            "longitude": payload.longitude,
            "radius_meters": payload.radius_meters,
            "search_radius_meters": payload.search_radius_meters,
            "location_constraints": payload.location_constraints,
            "polygon_coordinates": payload.polygon_coordinates,
            "timezone": payload.timezone,
            "starts_at": payload.starts_at,
            "ends_at": payload.ends_at,
        }

    if existing is None:
        raise ValueError("existing geo-zone is required for update validation")

    effective = {
        "zone_type": existing.zone_type,
        "latitude": existing.latitude,
        "longitude": existing.longitude,
        "radius_meters": existing.radius_meters,
        "search_radius_meters": existing.search_radius_meters,
        "location_constraints": existing.location_constraints,
        "polygon_coordinates": existing.polygon_coordinates,
        "timezone": existing.timezone,
        "starts_at": existing.starts_at,
        "ends_at": existing.ends_at,
    }
    effective.update(
        {
            key: value
            for key, value in payload.model_dump(exclude_unset=True).items()
            if key in effective
        }
    )
    return effective


def _fail(field: str, message: str) -> None:
    raise HTTPException(status_code=422, detail=f"{field}: {message}")


VALID_LOCATION_CONSTRAINT_KEYS = frozenset({
    "avoid_buildings",
    "avoid_water",
    "avoid_roads",
    "avoid_private",
})


def _validate_location_constraints(value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        _fail("location_constraints", "должен быть JSON-объектом")
    for key, val in value.items():
        if key not in VALID_LOCATION_CONSTRAINT_KEYS:
            _fail(
                "location_constraints",
                f"неизвестный ключ: {key}. Допустимы: {', '.join(sorted(VALID_LOCATION_CONSTRAINT_KEYS))}",
            )
        if not isinstance(val, bool):
            _fail(
                "location_constraints",
                f"значение для {key} должно быть boolean",
            )


def _validate_geo_zone(effective: dict[str, Any]) -> None:
    _validate_location_constraints(effective.get("location_constraints"))

    zone_type = effective.get("zone_type")

    if zone_type not in VALID_ZONE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                "Недопустимый zone_type. Разрешены: radius, polygon, poi, event."
            ),
        )

    timezone = effective.get("timezone")
    if timezone is None or not str(timezone).strip():
        raise HTTPException(
            status_code=422,
            detail="timezone не может быть пустым.",
        )

    latitude = effective.get("latitude")
    longitude = effective.get("longitude")
    radius_meters = effective.get("radius_meters")
    polygon_coordinates = effective.get("polygon_coordinates")

    if zone_type == "radius":
        radius_meters = effective.get("radius_meters")
        if radius_meters is None or radius_meters <= 0:
            _fail("radius_meters", "для zone_type=radius обязателен (целое > 0)")
        search_radius = effective.get("search_radius_meters")
        if search_radius is None or search_radius <= 0:
            _fail("search_radius_meters", "для zone_type=radius обязателен (целое > 0)")
        if effective.get("polygon_coordinates") not in (None, []):
            _fail("polygon_coordinates", "несовместим с zone_type=radius")

        lat = effective.get("latitude")
        lon = effective.get("longitude")
        if (lat is None) != (lon is None):
            _fail("latitude/longitude", "задавайте оба или ни одного")
        if lat is not None:
            if not (-90 <= lat <= 90):
                _fail("latitude", "должна быть от -90 до 90")
            if not (-180 <= lon <= 180):
                _fail("longitude", "должна быть от -180 до 180")

    elif zone_type == "polygon":
        if polygon_coordinates is None:
            raise HTTPException(
                status_code=422,
                detail="Зона polygon требует polygon_coordinates.",
            )
        if not isinstance(polygon_coordinates, list) or len(polygon_coordinates) < 3:
            raise HTTPException(
                status_code=422,
                detail="polygon_coordinates должен содержать минимум 3 точки.",
            )
        for index, point in enumerate(polygon_coordinates):
            if (
                not isinstance(point, (list, tuple))
                or len(point) != 2
                or not isinstance(point[0], (int, float))
                or isinstance(point[0], bool)
                or not -90 <= point[0] <= 90
                or not isinstance(point[1], (int, float))
                or isinstance(point[1], bool)
                or not -180 <= point[1] <= 180
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Каждая точка polygon_coordinates должна быть [lat, lon] "
                        "с lat ∈ [-90, 90] и lon ∈ [-180, 180]."
                    ),
                )
        if not all(
            value is None
            for value in (latitude, longitude, radius_meters)
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Зона polygon не может содержать latitude/longitude/radius_meters."
                ),
            )

    elif zone_type == "poi":
        if latitude is None:
            raise HTTPException(status_code=422, detail="Зона poi требует latitude.")
        if longitude is None:
            raise HTTPException(status_code=422, detail="Зона poi требует longitude.")
        if polygon_coordinates is not None:
            raise HTTPException(
                status_code=422,
                detail="Зона poi не может содержать polygon_coordinates.",
            )

    else:  # event
        if latitude is None:
            raise HTTPException(status_code=422, detail="Зона event требует latitude.")
        if longitude is None:
            raise HTTPException(status_code=422, detail="Зона event требует longitude.")
        if polygon_coordinates is not None:
            raise HTTPException(
                status_code=422,
                detail="Зона event не может содержать polygon_coordinates.",
            )
        if effective.get("starts_at") is None:
            raise HTTPException(
                status_code=422,
                detail="Зона event требует starts_at.",
            )
        if effective.get("ends_at") is None:
            raise HTTPException(
                status_code=422,
                detail="Зона event требует ends_at.",
            )

    starts_at = effective.get("starts_at")
    ends_at = effective.get("ends_at")
    if starts_at is not None and ends_at is not None and starts_at > ends_at:
        raise HTTPException(
            status_code=422,
            detail="starts_at не может быть позже ends_at.",
        )


def _serialize_geo_zone(zone: GeoZone) -> dict[str, Any]:
    return {
        "id": zone.id,
        "slug": zone.slug,
        "title": zone.title,
        "description": zone.description,
        "zoneType": zone.zone_type,
        "status": zone.status,
        "sortOrder": zone.sort_order,
        "latitude": zone.latitude,
        "longitude": zone.longitude,
        "radiusMeters": zone.radius_meters,
        "searchRadiusMeters": zone.search_radius_meters,
        "locationConstraints": zone.location_constraints or {},
        "polygonCoordinates": zone.polygon_coordinates,
        "timezone": zone.timezone,
        "startsAt": zone.starts_at.isoformat() if zone.starts_at else None,
        "endsAt": zone.ends_at.isoformat() if zone.ends_at else None,
        "maxLocationAccuracyMeters": zone.max_location_accuracy_meters,
        "minimumPresenceSeconds": zone.minimum_presence_seconds,
        "createdAt": zone.created_at.isoformat() if zone.created_at else None,
        "updatedAt": zone.updated_at.isoformat() if zone.updated_at else None,
    }


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    zone_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="geo_zone",
        entity_id=zone_id,
        request=request,
        permission_code=GEO_ZONES_MANAGE_PERMISSION,
        metadata=metadata,
    )


@router.get("")
def list_admin_geo_zones(
    _admin: AdminUser = Depends(require_permission(GEO_ZONES_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        zones = session.scalars(
            select(GeoZone).order_by(
                GeoZone.status, GeoZone.sort_order, GeoZone.id
            )
        ).all()

        return {"geoZones": [_serialize_geo_zone(zone) for zone in zones]}


@router.get("/{zone_id}")
def get_admin_geo_zone(
    zone_id: str,
    _admin: AdminUser = Depends(require_permission(GEO_ZONES_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        zone = session.get(GeoZone, zone_id)

        if zone is None:
            raise HTTPException(status_code=404, detail="Геозона не найдена.")

        return {"geoZone": _serialize_geo_zone(zone)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_geo_zone(
    payload: AdminGeoZoneCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(GEO_ZONES_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        slug = _normalize_slug(payload.slug)

        if session.scalar(select(GeoZone.id).where(GeoZone.slug == slug)):
            raise HTTPException(
                status_code=409,
                detail="Геозона с таким slug уже существует.",
            )

        _validate_geo_zone(_resolve_effective(payload))

        zone = GeoZone(
            id=_new_id("geo-zone"),
            slug=slug,
            title=payload.title.strip(),
            description=payload.description.strip() if payload.description else None,
            zone_type=payload.zone_type,
            status="draft",
            sort_order=payload.sort_order,
            latitude=payload.latitude,
            longitude=payload.longitude,
            radius_meters=payload.radius_meters,
            search_radius_meters=payload.search_radius_meters,
            location_constraints=payload.location_constraints,
            polygon_coordinates=payload.polygon_coordinates,
            timezone=payload.timezone.strip() or "UTC",
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
            max_location_accuracy_meters=payload.max_location_accuracy_meters,
            minimum_presence_seconds=payload.minimum_presence_seconds,
        )
        session.add(zone)
        session.flush()

        _audit(
            session,
            admin=admin,
            action="geo_zone.created",
            zone_id=zone.id,
            metadata={
                "slug": zone.slug,
                "zoneType": zone.zone_type,
                "status": zone.status,
            },
            request=request,
        )

        return {"geoZone": _serialize_geo_zone(zone)}


@router.patch("/{zone_id}")
def update_admin_geo_zone(
    zone_id: str,
    payload: AdminGeoZoneUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(GEO_ZONES_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        zone = session.get(GeoZone, zone_id)

        if zone is None:
            raise HTTPException(status_code=404, detail="Геозона не найдена.")

        changed_fields: list[str] = []

        # Сначала проверка «итогового состояния» (существующие значения + явно
        # переданные поля), затем любые изменения ORM-объекта.
        _validate_geo_zone(_resolve_effective(payload, existing=zone))

        if "slug" in updates:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(GeoZone.id).where(
                    GeoZone.slug == slug,
                    GeoZone.id != zone.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Геозона с таким slug уже существует.",
                )
            zone.slug = slug
            changed_fields.append("slug")

        scalar_fields = {
            "title": "title",
            "description": "description",
            "zone_type": "zoneType",
            "status": "status",
            "sort_order": "sortOrder",
            "latitude": "latitude",
            "longitude": "longitude",
            "radius_meters": "radiusMeters",
            "search_radius_meters": "searchRadiusMeters",
            "location_constraints": "locationConstraints",
            "polygon_coordinates": "polygonCoordinates",
            "timezone": "timezone",
            "starts_at": "startsAt",
            "ends_at": "endsAt",
            "max_location_accuracy_meters": "maxLocationAccuracyMeters",
            "minimum_presence_seconds": "minimumPresenceSeconds",
        }

        for field_name, audit_name in scalar_fields.items():
            if field_name not in updates:
                continue

            value = updates[field_name]

            if field_name == "title":
                value = value.strip()

            if field_name == "description" and value is not None:
                value = value.strip() or None

            if field_name == "status" and value not in VALID_ZONE_STATUSES:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Недопустимый статус геозоны. Разрешены: "
                        "draft, published, archived."
                    ),
                )

            if field_name == "timezone" and value is not None:
                value = value.strip()

            if field_name == "location_constraints" and value is None:
                value = {}

            setattr(zone, field_name, value)
            changed_fields.append(audit_name)

        session.flush()

        _audit(
            session,
            admin=admin,
            action="geo_zone.updated",
            zone_id=zone.id,
            metadata={
                "changedFields": changed_fields,
                "status": zone.status,
            },
            request=request,
        )

        return {"geoZone": _serialize_geo_zone(zone)}