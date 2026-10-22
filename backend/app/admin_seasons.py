"""Admin CRUD для Season (Sprint 8.21, backend).

Сезон — верхнеуровневая организационная единица контента
(Season -> Chapter -> Segment -> Mission). CRUD написан по образцу
admin_minigame_profiles.py (права, сериализация, аудит через
write_admin_audit) и admin_segments.py (slug-валидация SLUG_PATTERN,
row-lock, _ensure_editable).

Жизненный цикл (контракт docs/api-contracts.md): draft -> published -> archived.
Опубликованный сезон можно редактировать; archived — финальный и не изменяется
(409). reverse-переходы запрещены: archived нельзя ни публиковать, ни
редактировать. Схема таблицы seasons уже существует (модель Season),
DB CHECK на status нет — все статусы и переходы валидируются в прикладном коде.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminUser, Season
from app.slug_utils import _normalize_slug, _slugify_title

router = APIRouter(prefix="/api/v1/admin/seasons", tags=["admin-seasons"])

SEASONS_READ_PERMISSION = "seasons.read"
SEASONS_MANAGE_PERMISSION = "seasons.manage"

# В seasons.status нет DB CHECK — допустимые значения валидируются в коде.
VALID_SEASON_STATUSES = frozenset({"draft", "published", "archived"})


class SeasonCreatePayload(BaseModel):
    """Payload создания сезона (контракт: slug, title, description, sort_order)."""

    slug: str | None = Field(default=None, min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)


class SeasonUpdatePayload(BaseModel):
    """Payload обновления: все поля опциональны (PATCH)."""

    slug: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)


class SeasonResponse(BaseModel):
    """Схема ответа (camelCase) для OpenAPI-документации."""

    id: str
    slug: str
    title: str
    description: str | None = None
    status: str
    sortOrder: int
    createdAt: str | None = None
    updatedAt: str | None = None


def _new_id() -> str:
    return f"season-{uuid4().hex}"



def _normalize_title(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="title не может состоять только из пробелов.",
        )
    return stripped


def _normalize_optional_description(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _assert_known_status(value: str) -> None:
    if value not in VALID_SEASON_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Недопустимый статус сезона. Разрешены: "
                f"{', '.join(sorted(VALID_SEASON_STATUSES))}."
            ),
        )


def _serialize(season: Season) -> dict[str, Any]:
    return {
        "id": season.id,
        "slug": season.slug,
        "title": season.title,
        "description": season.description,
        "status": season.status,
        "sortOrder": season.sort_order,
        "createdAt": season.created_at.isoformat() if season.created_at else None,
        "updatedAt": season.updated_at.isoformat() if season.updated_at else None,
    }


def _lock_season(session: Session, season_id: str) -> Season:
    season = session.scalar(
        select(Season).where(Season.id == season_id).with_for_update()
    )
    if season is None:
        raise HTTPException(status_code=404, detail="Сезон не найден.")
    return season


def _ensure_editable(season: Season) -> None:
    if season.status == "archived":
        raise HTTPException(
            status_code=409,
            detail="Archived сезон является финальным и не может изменяться.",
        )


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    season_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="season",
        entity_id=season_id,
        request=request,
        permission_code=SEASONS_MANAGE_PERMISSION,
        metadata=metadata,
    )


@router.get("")
def list_admin_seasons(
    status: str | None = None,
    _admin: AdminUser = Depends(require_permission(SEASONS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        if status is not None:
            _assert_known_status(status)

        query = select(Season).order_by(Season.sort_order, Season.id)
        if status is not None:
            query = query.where(Season.status == status)

        seasons = session.scalars(query).all()
        return {"seasons": [_serialize(season) for season in seasons]}


@router.get("/{season_id}")
def get_admin_season(
    season_id: str,
    _admin: AdminUser = Depends(require_permission(SEASONS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        season = session.get(Season, season_id)

        if season is None:
            raise HTTPException(status_code=404, detail="Сезон не найден.")

        return {"season": _serialize(season)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_season(
    payload: SeasonCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEASONS_MANAGE_PERMISSION)),
):
    title = _normalize_title(payload.title)
    slug = (
        _normalize_slug(payload.slug)
        if payload.slug is not None
        else _slugify_title(title)
    )

    with SessionLocal.begin() as session:
        if session.scalar(select(Season.id).where(Season.slug == slug)):
            raise HTTPException(
                status_code=409, detail="Сезон с таким slug уже существует."
            )

        season = Season(
            id=_new_id(),
            slug=slug,
            title=title,
            description=_normalize_optional_description(payload.description),
            status="draft",
            sort_order=payload.sort_order,
        )
        session.add(season)
        session.flush()

        _audit(
            session,
            admin=admin,
            action="season.created",
            season_id=season.id,
            metadata={
                "slug": season.slug,
                "status": season.status,
                "sortOrder": season.sort_order,
            },
            request=request,
        )

        return {"season": _serialize(season)}


@router.patch("/{season_id}")
def update_admin_season(
    season_id: str,
    payload: SeasonUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEASONS_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        season = _lock_season(session, season_id)
        _ensure_editable(season)

        changed_fields: list[str] = []

        if "slug" in updates and updates["slug"] is not None:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(Season.id).where(
                    Season.slug == slug,
                    Season.id != season.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=409, detail="Сезон с таким slug уже существует."
                )
            season.slug = slug
            changed_fields.append("slug")

        if "title" in updates and updates["title"] is not None:
            season.title = _normalize_title(updates["title"])
            changed_fields.append("title")

        if "description" in updates:
            season.description = _normalize_optional_description(
                updates["description"]
            )
            changed_fields.append("description")

        if "sort_order" in updates and updates["sort_order"] is not None:
            season.sort_order = updates["sort_order"]
            changed_fields.append("sortOrder")

        session.flush()

        _audit(
            session,
            admin=admin,
            action="season.updated",
            season_id=season.id,
            metadata={"changedFields": changed_fields, "status": season.status},
            request=request,
        )

        return {"season": _serialize(season)}


@router.post("/{season_id}/publish")
def publish_admin_season(
    season_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEASONS_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        season = _lock_season(session, season_id)
        _ensure_editable(season)

        if season.status == "published":
            raise HTTPException(
                status_code=422, detail="Сезон уже опубликован."
            )

        previous_status = season.status
        season.status = "published"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="season.published",
            season_id=season.id,
            metadata={"slug": season.slug, "previousStatus": previous_status},
            request=request,
        )

        return {"season": _serialize(season)}


@router.post("/{season_id}/archive")
def archive_admin_season(
    season_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(SEASONS_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        season = _lock_season(session, season_id)

        if season.status == "archived":
            raise HTTPException(
                status_code=422, detail="Сезон уже архивирован."
            )

        if season.status != "published":
            raise HTTPException(
                status_code=422,
                detail="Архивировать можно только опубликованный сезон.",
            )

        previous_status = season.status
        season.status = "archived"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="season.archived",
            season_id=season.id,
            metadata={"slug": season.slug, "previousStatus": previous_status},
            request=request,
        )

        return {"season": _serialize(season)}