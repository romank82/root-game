from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminUser, ARObject, GeoZone
from app.slug_utils import _normalize_slug


router = APIRouter(prefix="/api/v1/admin/ar-objects", tags=["admin-ar-objects"])

AR_OBJECTS_READ_PERMISSION = "ar_objects.read"
AR_OBJECTS_MANAGE_PERMISSION = "ar_objects.manage"
VALID_AR_STATUSES = {"draft", "published", "archived"}


class AdminARObjectCreatePayload(BaseModel):
    slug: str = Field(min_length=3, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    geo_zone_id: str = Field(min_length=1, max_length=64)
    object_type: str = Field(min_length=1, max_length=64)
    asset_uri: str = Field(min_length=1, max_length=512)
    asset_mime_type: str | None = Field(default=None, max_length=128)
    scene_preset: str | None = Field(default=None, max_length=128)
    scale_meters: float = Field(default=1.0, gt=0.0, le=10.0)
    orientation: str = Field(default="free", min_length=1, max_length=32)
    discovery_scenario: dict[str, Any] = Field(default_factory=dict)
    minigame_config: dict[str, Any] = Field(default_factory=dict)
    instruction_text: str | None = Field(default=None, max_length=20_000)
    validation_config: dict[str, Any] = Field(default_factory=dict)
    starts_at: datetime | None = Field(default=None)
    ends_at: datetime | None = Field(default=None)


class AdminARObjectUpdatePayload(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    geo_zone_id: str | None = Field(default=None, min_length=1, max_length=64)
    object_type: str | None = Field(default=None, min_length=1, max_length=64)
    asset_uri: str | None = Field(default=None, min_length=1, max_length=512)
    asset_mime_type: str | None = Field(default=None, max_length=128)
    scene_preset: str | None = Field(default=None, max_length=128)
    scale_meters: float | None = Field(default=None, gt=0.0, le=10.0)
    orientation: str | None = Field(default=None, min_length=1, max_length=32)
    discovery_scenario: dict[str, Any] | None = None
    minigame_config: dict[str, Any] | None = None
    instruction_text: str | None = Field(default=None, max_length=20_000)
    validation_config: dict[str, Any] | None = None
    starts_at: datetime | None = Field(default=None)
    ends_at: datetime | None = Field(default=None)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _validate_geo_zone_exists(session: Session, geo_zone_id: str) -> None:
    if session.get(GeoZone, geo_zone_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Указанный geo_zone_id не существует.",
        )


def _validate_time_window(
    starts_at: datetime | None,
    ends_at: datetime | None,
) -> None:
    if starts_at is None or ends_at is None:
        return

    # SQLite хранит timezone-колонки naive, а pydantic парсит offset-aware:
    # сравниваем в UTC, чтобы смешанные значения не роняли сравнение.
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=timezone.utc)
    else:
        starts_at = starts_at.astimezone(timezone.utc)

    if ends_at.tzinfo is None:
        ends_at = ends_at.replace(tzinfo=timezone.utc)
    else:
        ends_at = ends_at.astimezone(timezone.utc)

    if starts_at > ends_at:
        raise HTTPException(
            status_code=422,
            detail="starts_at не может быть позже ends_at.",
        )


VALID_ORIENTATIONS = frozenset({"free", "upright", "flat"})


def _validate_orientation(value: str | None) -> None:
    if value is None:
        return
    if value not in VALID_ORIENTATIONS:
        raise HTTPException(
            status_code=422,
            detail="orientation должен быть одним из: free, upright, flat.",
        )


def _serialize_ar_object(obj: ARObject) -> dict[str, Any]:
    return {
        "id": obj.id,
        "slug": obj.slug,
        "title": obj.title,
        "description": obj.description,
        "status": obj.status,
        "sortOrder": obj.sort_order,
        "geoZoneId": obj.geo_zone_id,
        "objectType": obj.object_type,
        "assetUri": obj.asset_uri,
        "assetMimeType": obj.asset_mime_type,
        "scenePreset": obj.scene_preset,
        "scaleMeters": obj.scale_meters,
        "orientation": obj.orientation,
        "discoveryScenario": obj.discovery_scenario,
        "minigameConfig": obj.minigame_config,
        "instructionText": obj.instruction_text,
        "validationConfig": obj.validation_config,
        "startsAt": obj.starts_at.isoformat() if obj.starts_at else None,
        "endsAt": obj.ends_at.isoformat() if obj.ends_at else None,
        "createdAt": obj.created_at.isoformat() if obj.created_at else None,
        "updatedAt": obj.updated_at.isoformat() if obj.updated_at else None,
    }


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    ar_object_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="ar_object",
        entity_id=ar_object_id,
        request=request,
        permission_code=AR_OBJECTS_MANAGE_PERMISSION,
        metadata=metadata,
    )


@router.get("")
def list_admin_ar_objects(
    _admin: AdminUser = Depends(require_permission(AR_OBJECTS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        objects = session.scalars(
            select(ARObject).order_by(
                ARObject.status, ARObject.sort_order, ARObject.id
            )
        ).all()

        return {"arObjects": [_serialize_ar_object(obj) for obj in objects]}


@router.get("/{ar_object_id}")
def get_admin_ar_object(
    ar_object_id: str,
    _admin: AdminUser = Depends(require_permission(AR_OBJECTS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        obj = session.get(ARObject, ar_object_id)

        if obj is None:
            raise HTTPException(status_code=404, detail="AR-объект не найден.")

        return {"arObject": _serialize_ar_object(obj)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_ar_object(
    payload: AdminARObjectCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(AR_OBJECTS_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        slug = _normalize_slug(payload.slug)

        if session.scalar(select(ARObject.id).where(ARObject.slug == slug)):
            raise HTTPException(
                status_code=409,
                detail="AR-объект с таким slug уже существует.",
            )

        _validate_geo_zone_exists(session, payload.geo_zone_id)
        _validate_time_window(payload.starts_at, payload.ends_at)
        _validate_orientation(payload.orientation)

        obj = ARObject(
            id=_new_id("ar-object"),
            slug=slug,
            title=payload.title.strip(),
            description=(
                payload.description.strip() if payload.description else None
            ),
            status="draft",
            sort_order=payload.sort_order,
            geo_zone_id=payload.geo_zone_id,
            object_type=payload.object_type.strip(),
            asset_uri=payload.asset_uri.strip(),
            asset_mime_type=(
                payload.asset_mime_type.strip() if payload.asset_mime_type else None
            ),
            scene_preset=payload.scene_preset.strip() if payload.scene_preset else None,
            scale_meters=payload.scale_meters,
            orientation=payload.orientation,
            discovery_scenario=payload.discovery_scenario,
            minigame_config=payload.minigame_config,
            instruction_text=(
                payload.instruction_text.strip() if payload.instruction_text else None
            ),
            validation_config=payload.validation_config,
            starts_at=payload.starts_at,
            ends_at=payload.ends_at,
        )
        session.add(obj)
        session.flush()

        _audit(
            session,
            admin=admin,
            action="ar_object.created",
            ar_object_id=obj.id,
            metadata={
                "slug": obj.slug,
                "geoZoneId": obj.geo_zone_id,
                "objectType": obj.object_type,
                "status": obj.status,
            },
            request=request,
        )

        return {"arObject": _serialize_ar_object(obj)}


@router.patch("/{ar_object_id}")
def update_admin_ar_object(
    ar_object_id: str,
    payload: AdminARObjectUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(AR_OBJECTS_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        obj = session.get(ARObject, ar_object_id)

        if obj is None:
            raise HTTPException(status_code=404, detail="AR-объект не найден.")

        changed_fields: list[str] = []

        # Проверки итогового состояния — до любых изменений ORM-объекта.
        if "geo_zone_id" in updates:
            _validate_geo_zone_exists(session, updates["geo_zone_id"])

        effective_starts = updates.get("starts_at", obj.starts_at)
        effective_ends = updates.get("ends_at", obj.ends_at)
        _validate_time_window(effective_starts, effective_ends)
        _validate_orientation(payload.orientation)

        if "slug" in updates:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(ARObject.id).where(
                    ARObject.slug == slug,
                    ARObject.id != obj.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="AR-объект с таким slug уже существует.",
                )
            obj.slug = slug
            changed_fields.append("slug")

        scalar_fields = {
            "title": "title",
            "description": "description",
            "status": "status",
            "sort_order": "sortOrder",
            "geo_zone_id": "geoZoneId",
            "object_type": "objectType",
            "asset_uri": "assetUri",
            "asset_mime_type": "assetMimeType",
            "scene_preset": "scenePreset",
            "scale_meters": "scaleMeters",
            "orientation": "orientation",
            "discovery_scenario": "discoveryScenario",
            "minigame_config": "minigameConfig",
            "instruction_text": "instructionText",
            "validation_config": "validationConfig",
            "starts_at": "startsAt",
            "ends_at": "endsAt",
        }

        for field_name, audit_name in scalar_fields.items():
            if field_name not in updates:
                continue

            value = updates[field_name]

            if field_name in ("title", "object_type", "asset_uri") and value is not None:
                value = value.strip()

            if field_name == "orientation" and value is not None:
                value = value.strip().lower()

            if (
                field_name
                in ("description", "asset_mime_type", "scene_preset", "instruction_text")
                and value is not None
            ):
                value = value.strip() or None

            if (
                field_name in ("discovery_scenario", "minigame_config", "validation_config")
                and value is None
            ):
                value = {}

            if field_name == "status" and value not in VALID_AR_STATUSES:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Недопустимый статус AR-объекта. Разрешены: "
                        "draft, published, archived."
                    ),
                )

            setattr(obj, field_name, value)
            changed_fields.append(audit_name)

        session.flush()

        _audit(
            session,
            admin=admin,
            action="ar_object.updated",
            ar_object_id=obj.id,
            metadata={
                "changedFields": changed_fields,
                "status": obj.status,
            },
            request=request,
        )

        return {"arObject": _serialize_ar_object(obj)}

