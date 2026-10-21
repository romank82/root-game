"""Admin CRUD для Chapter (Sprint 8.22, backend).

Глава — дочерняя сущность Season (Season -> Chapter -> Segment -> Mission),
поэтому модуль совмещает два эталона: CRUD по образцу admin_seasons.py
(права, serialize, audit, endpoints, slug, lock, ensure_editable),
валидация FK season_id — по образцу _validate_chapter из admin_segments.py
(проверка существования через session.get -> 422).

Согласованные решения (Sprint 8.22, D3):
(а) create в archived-сезон запрещён (422);
(б) смена season_id у published-главы запрещена (409);
(в) повторный publish published-главы запрещён (422).

Жизненный цикл (контракт docs/api-contracts.md): draft -> published -> archived.
Строгая иерархия: глава публикуется только когда её season.status == "published"
(проверка в publish-эндпоинте под row-lock обеих строк — _lock_chapter +
_lock_season). Archived — финальный и не изменяется (409). reverse-переходы
запрещены. Схема таблицы chapters уже существует (модель Chapter),
миграция схемы не требуется — только сид прав chapters.read/chapters.manage.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminUser, Chapter, Season

router = APIRouter(prefix="/api/v1/admin/chapters", tags=["admin-chapters"])

CHAPTERS_READ_PERMISSION = "chapters.read"
CHAPTERS_MANAGE_PERMISSION = "chapters.manage"

# В chapters.status нет DB CHECK — допустимые значения валидируются в коде.
VALID_CHAPTER_STATUSES = frozenset({"draft", "published", "archived"})

# Скопировано из admin_seasons.py / admin_segments.py (общий контракт slug).
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[a-z0-9-]{0,126}[a-z0-9])?$")

# Транслитерация кириллицы для автогенерации slug из русскоязычного title.
_CYRILLIC_TO_LATIN = {
    ord("а"): "a", ord("б"): "b", ord("в"): "v", ord("г"): "g", ord("д"): "d",
    ord("е"): "e", ord("ё"): "e", ord("ж"): "zh", ord("з"): "z", ord("и"): "i",
    ord("й"): "y", ord("к"): "k", ord("л"): "l", ord("м"): "m", ord("н"): "n",
    ord("о"): "o", ord("п"): "p", ord("р"): "r", ord("с"): "s", ord("т"): "t",
    ord("у"): "u", ord("ф"): "f", ord("х"): "kh", ord("ц"): "ts", ord("ч"): "ch",
    ord("ш"): "sh", ord("щ"): "sch", ord("ъ"): "", ord("ы"): "y", ord("ь"): "",
    ord("э"): "e", ord("ю"): "yu", ord("я"): "ya",
}


class ChapterCreatePayload(BaseModel):
    """Payload создания главы (контракт: seasonId, slug, title, description, sort_order)."""

    # populate_by_name: клиенты могут слать и camelCase (seasonId),
    # и snake_case (season_id) — паттерн AdminSegmentPayloadModel.
    model_config = ConfigDict(populate_by_name=True)

    season_id: str = Field(min_length=1, max_length=64, alias="seasonId")
    slug: str | None = Field(default=None, min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)

class ChapterUpdatePayload(BaseModel):
    """Payload обновления: все поля опциональны (PATCH)."""

    model_config = ConfigDict(populate_by_name=True)

    season_id: str | None = Field(
        default=None, min_length=1, max_length=64, alias="seasonId"
    )
    slug: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)


class ChapterResponse(BaseModel):
    """Схема ответа (camelCase) для OpenAPI-документации."""

    id: str
    seasonId: str
    slug: str
    title: str
    description: str | None = None
    status: str
    sortOrder: int
    createdAt: str | None = None
    updatedAt: str | None = None


def _new_id() -> str:
    return f"chapter-{uuid4().hex}"


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()

    if not SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "slug должен содержать строчные латинские буквы, цифры и дефисы; "
                "длина — от 3 до 128 символов."
            ),
        )

    return slug


def _slugify_title(title: str) -> str:
    """Генерирует валидный slug из title (транслитерация + дефисы)."""
    candidate = title.lower().translate(_CYRILLIC_TO_LATIN)
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate).strip("-")

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Не удалось сгенерировать slug из title; передайте slug явно.",
        )

    try:
        return _normalize_slug(candidate)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Из title не удалось сгенерировать корректный slug; "
                "укажите slug явно."
            ),
        ) from exc


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
    if value not in VALID_CHAPTER_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Недопустимый статус главы. Разрешены: "
                f"{', '.join(sorted(VALID_CHAPTER_STATUSES))}."
            ),
        )


def _serialize(chapter: Chapter) -> dict[str, Any]:
    return {
        "id": chapter.id,
        "seasonId": chapter.season_id,
        "slug": chapter.slug,
        "title": chapter.title,
        "description": chapter.description,
        "status": chapter.status,
        "sortOrder": chapter.sort_order,
        "createdAt": chapter.created_at.isoformat() if chapter.created_at else None,
        "updatedAt": chapter.updated_at.isoformat() if chapter.updated_at else None,
    }


def _validate_season(session: Session, season_id: str) -> None:
    """Валидация FK season_id (эталон _validate_chapter из admin_segments.py).

    Проверяет только существование сезона — строгая иерархия статусов
    проверяется отдельно (create: archived -> 422; publish: не published -> 422).
    """
    if session.get(Season, season_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Указанный сезон (season_id) не существует.",
        )


def _lock_chapter(session: Session, chapter_id: str) -> Chapter:
    chapter = session.scalar(
        select(Chapter).where(Chapter.id == chapter_id).with_for_update()
    )
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Глава не найдена."
        )
    return chapter


def _lock_season(session: Session, season_id: str) -> Season:
    season = session.scalar(
        select(Season).where(Season.id == season_id).with_for_update()
    )
    if season is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Сезон не найден."
        )
    return season


def _ensure_editable(chapter: Chapter) -> None:
    if chapter.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Архивированная глава является финальной и не может изменяться.",
        )


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    chapter_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="chapter",
        entity_id=chapter_id,
        request=request,
        permission_code=CHAPTERS_MANAGE_PERMISSION,
        metadata=metadata,
    )


@router.get("")
def list_admin_chapters(
    status: str | None = None,
    season_id: str | None = None,
    _admin: AdminUser = Depends(require_permission(CHAPTERS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        if status is not None:
            _assert_known_status(status)

        # Sprint 8.23 (Этап 1): опциональный фильтр season_id — только главы
        # этого сезона. Без параметра поведение не меняется (обратная
        # совместимость). Несуществующий сезон -> 404; валидатор _validate_season
        # отдаёт 422 и используется create/update, поэтому здесь проверка
        # через сессию с 404 (согласовано в задаче 8.23).
        if season_id is not None and session.get(Season, season_id) is None:
            # 404 целочисленным литералом: имя параметра функции `status`
            # затеняет модуль fastapi.status (как и было до этого эндпоинта).
            raise HTTPException(
                status_code=404,
                detail="Сезон не найден.",
            )

        query = select(Chapter).order_by(Chapter.sort_order, Chapter.id)
        if status is not None:
            query = query.where(Chapter.status == status)
        if season_id is not None:
            query = query.where(Chapter.season_id == season_id)

        chapters = session.scalars(query).all()
        return {"chapters": [_serialize(chapter) for chapter in chapters]}


@router.get("/{chapter_id}")
def get_admin_chapter(
    chapter_id: str,
    _admin: AdminUser = Depends(require_permission(CHAPTERS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        chapter = session.get(Chapter, chapter_id)

        if chapter is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Глава не найдена."
            )

        return {"chapter": _serialize(chapter)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_chapter(
    payload: ChapterCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(CHAPTERS_MANAGE_PERMISSION)),
):
    title = _normalize_title(payload.title)
    slug = (
        _normalize_slug(payload.slug)
        if payload.slug is not None
        else _slugify_title(title)
    )

    with SessionLocal.begin() as session:
        if session.scalar(select(Chapter.id).where(Chapter.slug == slug)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Глава с таким slug уже существует.",
            )

        _validate_season(session, payload.season_id)
        # (D3а): создание главы в архивном сезоне запрещено.
        season = session.get(Season, payload.season_id)
        if season.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Нельзя создавать главу в архивном сезоне.",
            )

        chapter = Chapter(
            id=_new_id(),
            season_id=payload.season_id,
            slug=slug,
            title=title,
            description=_normalize_optional_description(payload.description),
            status="draft",
            sort_order=payload.sort_order,
        )
        session.add(chapter)
        session.flush()

        _audit(
            session,
            admin=admin,
            action="chapter.created",
            chapter_id=chapter.id,
            metadata={
                "slug": chapter.slug,
                "status": chapter.status,
                "seasonId": chapter.season_id,
                "sortOrder": chapter.sort_order,
            },
            request=request,
        )

        return {"chapter": _serialize(chapter)}


@router.patch("/{chapter_id}")
def update_admin_chapter(
    chapter_id: str,
    payload: ChapterUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(CHAPTERS_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        chapter = _lock_chapter(session, chapter_id)
        _ensure_editable(chapter)

        changed_fields: list[str] = []

        if "season_id" in updates and updates["season_id"] is not None:
            new_season_id = updates["season_id"]
            _validate_season(session, new_season_id)
            # (D3б): опубликованную главу нельзя переносить в другой сезон.
            if chapter.status == "published":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Нельзя менять сезон у опубликованной главы.",
                )
            chapter.season_id = new_season_id
            changed_fields.append("seasonId")

        if "slug" in updates and updates["slug"] is not None:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(Chapter.id).where(
                    Chapter.slug == slug,
                    Chapter.id != chapter.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Глава с таким slug уже существует.",
                )
            chapter.slug = slug
            changed_fields.append("slug")

        if "title" in updates and updates["title"] is not None:
            chapter.title = _normalize_title(updates["title"])
            changed_fields.append("title")

        if "description" in updates:
            chapter.description = _normalize_optional_description(
                updates["description"]
            )
            changed_fields.append("description")

        if "sort_order" in updates and updates["sort_order"] is not None:
            chapter.sort_order = updates["sort_order"]
            changed_fields.append("sortOrder")

        session.flush()

        _audit(
            session,
            admin=admin,
            action="chapter.updated",
            chapter_id=chapter.id,
            metadata={
                "changedFields": changed_fields,
                "status": chapter.status,
            },
            request=request,
        )

        return {"chapter": _serialize(chapter)}


@router.post("/{chapter_id}/publish")
def publish_admin_chapter(
    chapter_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(CHAPTERS_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        chapter = _lock_chapter(session, chapter_id)
        _ensure_editable(chapter)

        # (D3в): повторный publish запрещён (стиль admin_seasons).
        if chapter.status == "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Глава уже опубликована.",
            )

        # Строгая иерархия: сезон берётся под row-lock в той же транзакции.
        season = _lock_season(session, chapter.season_id)
        if season.status != "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Глава публикуется только в опубликованном сезоне.",
            )

        previous_status = chapter.status
        chapter.status = "published"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="chapter.published",
            chapter_id=chapter.id,
            metadata={
                "slug": chapter.slug,
                "previousStatus": previous_status,
                "seasonId": chapter.season_id,
            },
            request=request,
        )

        return {"chapter": _serialize(chapter)}


@router.post("/{chapter_id}/archive")
def archive_admin_chapter(
    chapter_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(CHAPTERS_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        chapter = _lock_chapter(session, chapter_id)

        if chapter.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Глава уже архивирована.",
            )

        if chapter.status != "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Архивировать можно только опубликованную главу.",
            )

        previous_status = chapter.status
        chapter.status = "archived"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="chapter.archived",
            chapter_id=chapter.id,
            metadata={
                "slug": chapter.slug,
                "previousStatus": previous_status,
                "seasonId": chapter.season_id,
            },
            request=request,
        )

        return {"chapter": _serialize(chapter)}

