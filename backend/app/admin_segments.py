from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.content_contract import PublicContentValidationError, validate_segment_content
from app.db import SessionLocal
from app.models import AdminUser, Chapter, Mission, Segment, SegmentMission
from app.slug_utils import _normalize_slug, _slugify_title, unique_slug


router = APIRouter(prefix="/api/v1/admin/segments", tags=["admin-segments"])

SEGMENT_READ_PERMISSION = "segments.read"
SEGMENT_MANAGE_PERMISSION = "segments.manage"
ACTIVE_LINK_STATUS = "active"
ARCHIVED_LINK_STATUS = "archived"


def _validate_public_segment_content(content: Any) -> None:
    """Do not expose submitted content or protected values in validation errors."""
    try:
        validate_segment_content(content)
    except PublicContentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Публичный content Segment не соответствует опубликованному контракту.",
        ) from exc


class AdminSegmentPayloadModel(BaseModel):
    # Contract uses camelCase. populate_by_name retains safe compatibility with
    # server-side callers that use Python field names.
    model_config = ConfigDict(populate_by_name=True)


class AdminSegmentMissionLinkPayload(AdminSegmentPayloadModel):
    mission_id: str = Field(
        min_length=1,
        max_length=64,
        alias="missionId",
    )
    sort_order: int = Field(
        default=0,
        ge=0,
        le=100_000,
        alias="sortOrder",
    )


class AdminSegmentCreatePayload(AdminSegmentPayloadModel):
    chapter_id: str = Field(
        min_length=1,
        max_length=64,
        alias="chapterId",
    )
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    content: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(
        default=0,
        ge=0,
        le=100_000,
        alias="sortOrder",
    )
    linked_missions: list[AdminSegmentMissionLinkPayload] = Field(
        default_factory=list,
        alias="linkedMissions",
    )


class AdminSegmentUpdatePayload(AdminSegmentPayloadModel):
    chapter_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
        alias="chapterId",
    )
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    content: dict[str, Any] | None = None
    sort_order: int | None = Field(
        default=None,
        ge=0,
        le=100_000,
        alias="sortOrder",
    )
    linked_missions: list[AdminSegmentMissionLinkPayload] | None = Field(
        default=None,
        alias="linkedMissions",
    )


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} не может состоять только из пробелов.",
        )
    return normalized


def _normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _serialize_link(link: SegmentMission) -> dict[str, Any]:
    return {
        "id": link.id,
        "missionId": link.mission_id,
        "sortOrder": link.sort_order,
    }


def _active_links(session: Session, segment_id: str) -> list[SegmentMission]:
    return session.scalars(
        select(SegmentMission)
        .where(
            SegmentMission.segment_id == segment_id,
            SegmentMission.status == ACTIVE_LINK_STATUS,
        )
        .order_by(SegmentMission.sort_order, SegmentMission.id)
    ).all()


def _serialize_segment(session: Session, segment: Segment) -> dict[str, Any]:
    return {
        "id": segment.id,
        "chapterId": segment.chapter_id,
        "slug": segment.slug,
        "title": segment.title,
        "description": segment.description,
        "content": segment.content,
        "status": segment.status,
        "sortOrder": segment.sort_order,
        "linkedMissions": [
            _serialize_link(link) for link in _active_links(session, segment.id)
        ],
        "createdAt": segment.created_at.isoformat() if segment.created_at else None,
        "updatedAt": segment.updated_at.isoformat() if segment.updated_at else None,
    }


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    segment: Segment,
    request: Request,
    metadata: dict[str, Any],
) -> None:
    # content is intentionally not copied to audit metadata.
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="segment",
        entity_id=segment.id,
        request=request,
        permission_code=SEGMENT_MANAGE_PERMISSION,
        metadata=metadata,
    )


def _validate_chapter(session: Session, chapter_id: str) -> None:
    if session.get(Chapter, chapter_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Указанная глава (chapter_id) не существует.",
        )


def _validate_link_payload(
    session: Session,
    *,
    chapter_id: str,
    links: list[AdminSegmentMissionLinkPayload],
) -> dict[str, Mission]:
    mission_ids = [link.mission_id for link in links]

    if len(mission_ids) != len(set(mission_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="linkedMissions не должен содержать повторяющиеся missionId.",
        )

    if not mission_ids:
        return {}

    missions = session.scalars(
        select(Mission)
        .where(Mission.id.in_(mission_ids))
        .with_for_update()
    ).all()
    missions_by_id = {mission.id: mission for mission in missions}

    missing_ids = sorted(set(mission_ids) - set(missions_by_id))
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="linkedMissions содержит несуществующую Mission.",
        )

    wrong_chapter = [
        mission.id
        for mission in missions_by_id.values()
        if mission.chapter_id != chapter_id
    ]
    if wrong_chapter:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Каждая linked Mission должна принадлежать той же chapter_id, "
                "что и Segment."
            ),
        )

    return missions_by_id


def _validate_publishable(
    session: Session,
    segment: Segment,
    *,
    locked_active_links: list[SegmentMission] | None = None,
) -> None:
    _validate_chapter(session, segment.chapter_id)

    links = locked_active_links
    if links is None:
        links = session.scalars(
            select(SegmentMission)
            .where(
                SegmentMission.segment_id == segment.id,
                SegmentMission.status == ACTIVE_LINK_STATUS,
            )
            .with_for_update()
        ).all()

    if not links:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Нельзя опубликовать Segment без хотя бы одной active "
                "связанной published Mission."
            ),
        )

    mission_ids = [link.mission_id for link in links]
    missions = session.scalars(
        select(Mission).where(Mission.id.in_(mission_ids)).with_for_update()
    ).all()
    missions_by_id = {mission.id: mission for mission in missions}

    if len(missions_by_id) != len(mission_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Segment содержит ссылку на несуществующую Mission.",
        )

    for mission in missions_by_id.values():
        if mission.chapter_id != segment.chapter_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Нельзя опубликовать Segment со связанной Mission "
                    "из другой главы."
                ),
            )
        if mission.status != "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Для публикации Segment каждая active связанная Mission "
                    "должна иметь status=published."
                ),
            )


def _replace_active_links(
    session: Session,
    *,
    segment: Segment,
    links: list[AdminSegmentMissionLinkPayload],
    admin: AdminUser,
) -> dict[str, int]:
    """
    Synchronize the active link set without deleting history.

    Omitted active rows become archived. A re-added former pair creates a new
    immutable row; the partial unique index prevents two active copies.
    """
    _validate_link_payload(session, chapter_id=segment.chapter_id, links=links)

    current_links = session.scalars(
        select(SegmentMission)
        .where(
            SegmentMission.segment_id == segment.id,
            SegmentMission.status == ACTIVE_LINK_STATUS,
        )
        .with_for_update()
    ).all()
    current_by_mission_id = {link.mission_id: link for link in current_links}
    desired_by_mission_id = {link.mission_id: link for link in links}

    archived_count = 0
    updated_count = 0
    created_count = 0

    for mission_id, current_link in current_by_mission_id.items():
        desired = desired_by_mission_id.get(mission_id)

        if desired is None:
            current_link.status = ARCHIVED_LINK_STATUS
            current_link.archived_at = _now()
            current_link.archived_by_admin_id = admin.id
            archived_count += 1
            continue

        if current_link.sort_order != desired.sort_order:
            current_link.sort_order = desired.sort_order
            updated_count += 1

    for mission_id, desired in desired_by_mission_id.items():
        if mission_id in current_by_mission_id:
            continue

        session.add(
            SegmentMission(
                id=_new_id("segment-mission"),
                segment_id=segment.id,
                mission_id=mission_id,
                status=ACTIVE_LINK_STATUS,
                sort_order=desired.sort_order,
            )
        )
        created_count += 1

    session.flush()

    return {
        "created": created_count,
        "updated": updated_count,
        "archived": archived_count,
        "active": len(desired_by_mission_id),
    }


def _lock_segment(session: Session, segment_id: str) -> Segment:
    segment = session.scalar(
        select(Segment).where(Segment.id == segment_id).with_for_update()
    )
    if segment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment не найден.")
    return segment


def _ensure_editable(segment: Segment) -> None:
    if segment.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Archived Segment является финальным и не может изменяться.",
        )


@router.get("")
def list_admin_segments(
    chapter_id: str | None = None,
    _admin: AdminUser = Depends(require_permission(SEGMENT_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        # Sprint 8.23 (Этап 1): опциональный фильтр chapter_id — только
        # сегменты этой главы. Без параметра поведение не меняется (обратная
        # совместимость). Несуществующая глава -> 404; валидатор _validate_chapter
        # отдаёт 422 и используется create/update, поэтому здесь проверка через
        # сессию с литералом 404 (без затенения fastapi.status).
        if chapter_id is not None and session.get(Chapter, chapter_id) is None:
            raise HTTPException(
                status_code=404,
                detail="Глава не найдена.",
            )

        query = select(Segment).order_by(Segment.status, Segment.sort_order, Segment.id)
        if chapter_id is not None:
            query = query.where(Segment.chapter_id == chapter_id)

        segments = session.scalars(query).all()
        return {
            "segments": [
                _serialize_segment(session, segment)
                for segment in segments
            ]
        }


@router.get("/{segment_id}")
def get_admin_segment(
    segment_id: str,
    _admin: AdminUser = Depends(require_permission(SEGMENT_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        segment = session.get(Segment, segment_id)
        if segment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment не найден.")
        return {"segment": _serialize_segment(session, segment)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_segment(
    payload: AdminSegmentCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEGMENT_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        title = _normalize_required(payload.title, "title")
        slug = (
            _normalize_slug(payload.slug)
            if payload.slug is not None
            else _slugify_title(title)
        )

        if payload.slug is None:
            slug = unique_slug(
                slug,
                lambda s: session.scalar(
                    select(Segment.id).where(Segment.slug == s)
                ) is not None,
            )
        elif session.scalar(select(Segment.id).where(Segment.slug == slug)) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Segment с таким slug уже существует.",
            )

        _validate_chapter(session, payload.chapter_id)
        _validate_link_payload(
            session,
            chapter_id=payload.chapter_id,
            links=payload.linked_missions,
        )

        segment = Segment(
            id=_new_id("segment"),
            chapter_id=payload.chapter_id,
            slug=slug,
            title=title,
            description=_normalize_optional(payload.description),
            content=payload.content,
            status="draft",
            sort_order=payload.sort_order,
        )
        session.add(segment)
        session.flush()

        link_summary = _replace_active_links(
            session,
            segment=segment,
            links=payload.linked_missions,
            admin=admin,
        )

        _audit(
            session,
            admin=admin,
            action="segment.created",
            segment=segment,
            request=request,
            metadata={
                "slug": segment.slug,
                "status": segment.status,
                "chapterId": segment.chapter_id,
                "activeLinkCount": link_summary["active"],
            },
        )

        return {"segment": _serialize_segment(session, segment)}


@router.patch("/{segment_id}")
def update_admin_segment(
    segment_id: str,
    payload: AdminSegmentUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEGMENT_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        segment = _lock_segment(session, segment_id)
        _ensure_editable(segment)

        changed_fields: list[str] = []
        link_summary: dict[str, int] | None = None

        if "slug" in updates and updates["slug"] is not None:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(Segment.id).where(
                    Segment.slug == slug,
                    Segment.id != segment.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Segment с таким slug уже существует.",
                )
            segment.slug = slug
            changed_fields.append("slug")

        if "chapter_id" in updates:
            _validate_chapter(session, updates["chapter_id"])
            segment.chapter_id = updates["chapter_id"]
            changed_fields.append("chapterId")

        scalar_fields = {
            "title": "title",
            "description": "description",
            "content": "content",
            "sort_order": "sortOrder",
        }
        for field_name, audit_name in scalar_fields.items():
            if field_name not in updates:
                continue

            value = updates[field_name]
            if field_name == "title":
                value = _normalize_required(value, "title")
            elif field_name == "description":
                value = _normalize_optional(value)

            setattr(segment, field_name, value)
            changed_fields.append(audit_name)

        if "linked_missions" in updates:
            link_summary = _replace_active_links(
                session,
                segment=segment,
                links=payload.linked_missions or [],
                admin=admin,
            )
            changed_fields.append("linkedMissions")
        else:
            # Changing chapter without replacing links still must satisfy same-chapter rule.
            existing_links = session.scalars(
                select(SegmentMission)
                .where(
                    SegmentMission.segment_id == segment.id,
                    SegmentMission.status == ACTIVE_LINK_STATUS,
                )
                .with_for_update()
            ).all()
            _validate_link_payload(
                session,
                chapter_id=segment.chapter_id,
                links=[
                    AdminSegmentMissionLinkPayload(
                        mission_id=link.mission_id,
                        sort_order=link.sort_order,
                    )
                    for link in existing_links
                ],
            )

        if segment.status == "published" and "content" in updates:
            _validate_public_segment_content(segment.content)

        session.flush()

        if segment.status == "published":
            _validate_publishable(session, segment)

        _audit(
            session,
            admin=admin,
            action="segment.updated",
            segment=segment,
            request=request,
            metadata={
                "slug": segment.slug,
                "status": segment.status,
                "changedFields": changed_fields,
                "contentChanged": "content" in updates,
                "activeLinkCount": (
                    link_summary["active"]
                    if link_summary is not None
                    else len(_active_links(session, segment.id))
                ),
                "linksCreated": link_summary["created"] if link_summary else 0,
                "linksUpdated": link_summary["updated"] if link_summary else 0,
                "linksArchived": link_summary["archived"] if link_summary else 0,
            },
        )

        return {"segment": _serialize_segment(session, segment)}


@router.post("/{segment_id}/publish")
def publish_admin_segment(
    segment_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEGMENT_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        segment = _lock_segment(session, segment_id)
        _ensure_editable(segment)

        if segment.status == "published":
            return {"segment": _serialize_segment(session, segment)}

        _validate_public_segment_content(segment.content)
        _validate_publishable(session, segment)
        previous_status = segment.status
        segment.status = "published"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="segment.published",
            segment=segment,
            request=request,
            metadata={
                "slug": segment.slug,
                "previousStatus": previous_status,
                "activeLinkCount": len(_active_links(session, segment.id)),
            },
        )

        return {"segment": _serialize_segment(session, segment)}


@router.post("/{segment_id}/unpublish")
def unpublish_admin_segment(
    segment_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEGMENT_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        segment = _lock_segment(session, segment_id)
        _ensure_editable(segment)

        if segment.status == "draft":
            return {"segment": _serialize_segment(session, segment)}

        previous_status = segment.status
        segment.status = "draft"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="segment.unpublished",
            segment=segment,
            request=request,
            metadata={
                "slug": segment.slug,
                "previousStatus": previous_status,
            },
        )

        return {"segment": _serialize_segment(session, segment)}


@router.post("/{segment_id}/archive")
def archive_admin_segment(
    segment_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEGMENT_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        segment = _lock_segment(session, segment_id)

        if segment.status == "archived":
            return {"segment": _serialize_segment(session, segment)}

        previous_status = segment.status
        segment.status = "archived"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="segment.archived",
            segment=segment,
            request=request,
            metadata={
                "slug": segment.slug,
                "previousStatus": previous_status,
                "activeLinkCount": len(_active_links(session, segment.id)),
            },
        )

        return {"segment": _serialize_segment(session, segment)}
