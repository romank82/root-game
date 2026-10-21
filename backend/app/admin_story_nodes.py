"""Admin CRUD для StoryNode (Sprint 8.26, backend).

StoryNode — дочерняя сущность Chapter (Season -> Chapter -> StoryNode),
поэтому модуль повторяет эталон admin_chapters.py: права, serialize, audit,
endpoints, slug, lock, ensure_editable, строгая иерархия при publish. Валидация
FK chapter_id — по образцу _validate_chapter из admin_segments.py
(проверка существования через session.get -> 422).

Согласованные решения (Sprint 8.26, ревью 8.24):
(а) create в archived-главу запрещён (422);
(б) смена chapter_id у published-story-node запрещена (409);
(в) повторный publish published-story-node запрещён (422);
(г) перенос story-node в archived-главу по PATCH запрещён (422, аналогия (а)).

Жизненный цикл (контракт docs/api-contracts.md): draft -> published -> archived.
Строгая иерархия: story-node публикуется только когда его chapter.status ==
"published" (проверка в publish-эндпоинте под row-lock обеих строк —
_lock_story_node + _lock_chapter). Archived — финальный и не изменяется (409).
reverse-переходы запрещены. Схема таблицы story_nodes уже существует
(модель StoryNode, models.py:89) — миграция схемы не требуется, только сид
прав story_nodes.read/story_nodes.manage (a3f9c18e42b7 -> 90de6dad12b).

presentation_type: в коде нет словаря допустимых значений (модель хранит
произвольную строку, default "archive") — валидируется только непустота и
длина <= 32. content: JSON без известной структуры (в mission_engine.py:382
передаётся как есть) — принимается любой dict, пустой -> {}.
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
from app.models import AdminUser, Chapter, StoryNode

router = APIRouter(prefix="/api/v1/admin/story-nodes", tags=["admin-story-nodes"])

STORY_NODES_READ_PERMISSION = "story_nodes.read"
STORY_NODES_MANAGE_PERMISSION = "story_nodes.manage"

# В story_nodes.status нет DB CHECK — допустимые значения валидируются в коде.
VALID_STORY_NODE_STATUSES = frozenset({"draft", "published", "archived"})

# Скопировано из admin_chapters.py / admin_segments.py (общий контракт slug).
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


class StoryNodeCreatePayload(BaseModel):
    """Payload создания сюжетного узла (контракт: chapterId, slug, title, body,
    presentationType, content, sort_order)."""

    # populate_by_name: клиенты могут слать и camelCase (chapterId),
    # и snake_case (chapter_id) — паттерн AdminSegmentPayloadModel.
    model_config = ConfigDict(populate_by_name=True)

    chapter_id: str = Field(min_length=1, max_length=64, alias="chapterId")
    slug: str | None = Field(default=None, min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    body: str = Field(min_length=1, max_length=200_000)
    presentation_type: str | None = Field(
        default=None, min_length=1, max_length=32, alias="presentationType"
    )
    content: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=100_000)


class StoryNodeUpdatePayload(BaseModel):
    """Payload обновления: все поля опциональны (PATCH)."""

    model_config = ConfigDict(populate_by_name=True)

    chapter_id: str | None = Field(
        default=None, min_length=1, max_length=64, alias="chapterId"
    )
    slug: str | None = Field(default=None, min_length=1, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    body: str | None = Field(default=None, min_length=1, max_length=200_000)
    presentation_type: str | None = Field(
        default=None, min_length=1, max_length=32, alias="presentationType"
    )
    content: dict[str, Any] | None = Field(default=None)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)


class StoryNodeResponse(BaseModel):
    """Схема ответа (camelCase) для OpenAPI-документации."""

    id: str
    chapterId: str
    slug: str
    title: str
    body: str
    presentationType: str
    content: dict[str, Any]
    status: str
    sortOrder: int
    createdAt: str | None = None
    updatedAt: str | None = None


def _new_id() -> str:
    return f"story-node-{uuid4().hex}"


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


def _normalize_body(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="body не может быть пустым.",
        )
    return stripped


def _normalize_presentation_type(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="presentation_type не может быть пустым.",
        )
    return stripped


def _normalize_content(value: dict[str, Any] | None) -> dict[str, Any]:
    return value or {}


def _assert_known_status(value: str) -> None:
    if value not in VALID_STORY_NODE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Недопустимый статус story-node. Разрешены: "
                f"{', '.join(sorted(VALID_STORY_NODE_STATUSES))}."
            ),
        )


def _serialize(story_node: StoryNode) -> dict[str, Any]:
    return {
        "id": story_node.id,
        "chapterId": story_node.chapter_id,
        "slug": story_node.slug,
        "title": story_node.title,
        "body": story_node.body,
        "presentationType": story_node.presentation_type,
        "content": story_node.content,
        "status": story_node.status,
        "sortOrder": story_node.sort_order,
        "createdAt": story_node.created_at.isoformat() if story_node.created_at else None,
        "updatedAt": story_node.updated_at.isoformat() if story_node.updated_at else None,
    }


def _validate_chapter(session: Session, chapter_id: str) -> None:
    """Валидация FK chapter_id (эталон _validate_chapter из admin_segments.py).

    Проверяет только существование главы — строгая иерархия статусов
    проверяется отдельно (create/update в archived-главу -> 422;
    publish при не published главе -> 422).
    """
    if session.get(Chapter, chapter_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Указанная глава (chapter_id) не существует.",
        )


def _lock_story_node(session: Session, story_node_id: str) -> StoryNode:
    story_node = session.scalar(
        select(StoryNode).where(StoryNode.id == story_node_id).with_for_update()
    )
    if story_node is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Story-node не найден."
        )
    return story_node


def _lock_chapter(session: Session, chapter_id: str) -> Chapter:
    chapter = session.scalar(
        select(Chapter).where(Chapter.id == chapter_id).with_for_update()
    )
    if chapter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Глава не найдена."
        )
    return chapter


def _ensure_editable(story_node: StoryNode) -> None:
    if story_node.status == "archived":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Архивированный story-node является финальным и не может изменяться.",
        )


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    story_node_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="story_node",
        entity_id=story_node_id,
        request=request,
        permission_code=STORY_NODES_MANAGE_PERMISSION,
        metadata=metadata,
    )


def _is_archived_chapter(session: Session, chapter_id: str) -> bool:
    chapter = session.get(Chapter, chapter_id)
    return chapter is not None and chapter.status == "archived"


@router.get("")
def list_admin_story_nodes(
    status: str | None = None,
    chapter_id: str | None = None,
    _admin: AdminUser = Depends(require_permission(STORY_NODES_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        if status is not None:
            _assert_known_status(status)

        query = select(StoryNode).order_by(StoryNode.sort_order, StoryNode.id)
        if status is not None:
            query = query.where(StoryNode.status == status)
        if chapter_id is not None:
            query = query.where(StoryNode.chapter_id == chapter_id)

        story_nodes = session.scalars(query).all()
        return {"story_nodes": [_serialize(node) for node in story_nodes]}


@router.get("/{story_node_id}")
def get_admin_story_node(
    story_node_id: str,
    _admin: AdminUser = Depends(require_permission(STORY_NODES_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        story_node = session.get(StoryNode, story_node_id)

        if story_node is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Story-node не найден."
            )

        return {"story_node": _serialize(story_node)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_story_node(
    payload: StoryNodeCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(STORY_NODES_MANAGE_PERMISSION)),
):
    title = _normalize_title(payload.title)
    body = _normalize_body(payload.body)
    presentation_type = _normalize_presentation_type(
        payload.presentation_type or "archive"
    )
    slug = (
        _normalize_slug(payload.slug)
        if payload.slug is not None
        else _slugify_title(title)
    )

    with SessionLocal.begin() as session:
        if session.scalar(select(StoryNode.id).where(StoryNode.slug == slug)):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Story-node с таким slug уже существует.",
            )

        _validate_chapter(session, payload.chapter_id)
        # (а): создание story-node в архивной главе запрещено.
        if _is_archived_chapter(session, payload.chapter_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Нельзя создавать story-node в архивной главе.",
            )

        story_node = StoryNode(
            id=_new_id(),
            chapter_id=payload.chapter_id,
            slug=slug,
            title=title,
            body=body,
            presentation_type=presentation_type,
            content=_normalize_content(payload.content),
            status="draft",
            sort_order=payload.sort_order,
        )
        session.add(story_node)
        session.flush()

        _audit(
            session,
            admin=admin,
            action="story_node.created",
            story_node_id=story_node.id,
            metadata={
                "slug": story_node.slug,
                "status": story_node.status,
                "chapterId": story_node.chapter_id,
                "sortOrder": story_node.sort_order,
            },
            request=request,
        )

        return {"story_node": _serialize(story_node)}


@router.patch("/{story_node_id}")
def update_admin_story_node(
    story_node_id: str,
    payload: StoryNodeUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(STORY_NODES_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        story_node = _lock_story_node(session, story_node_id)
        _ensure_editable(story_node)

        changed_fields: list[str] = []

        if "chapter_id" in updates and updates["chapter_id"] is not None:
            new_chapter_id = updates["chapter_id"]
            _validate_chapter(session, new_chapter_id)
            # (г): перенос в архивную главу запрещён (аналогия create).
            if _is_archived_chapter(session, new_chapter_id):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Нельзя переносить story-node в архивную главу.",
                )
            # (б): опубликованный story-node нельзя переносить в другую главу.
            if story_node.status == "published":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Нельзя менять главу у опубликованного story-node.",
                )
            story_node.chapter_id = new_chapter_id
            changed_fields.append("chapterId")

        if "slug" in updates and updates["slug"] is not None:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(StoryNode.id).where(
                    StoryNode.slug == slug,
                    StoryNode.id != story_node.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Story-node с таким slug уже существует.",
                )
            story_node.slug = slug
            changed_fields.append("slug")

        if "title" in updates and updates["title"] is not None:
            story_node.title = _normalize_title(updates["title"])
            changed_fields.append("title")

        if "body" in updates and updates["body"] is not None:
            story_node.body = _normalize_body(updates["body"])
            changed_fields.append("body")

        if (
            "presentation_type" in updates
            and updates["presentation_type"] is not None
        ):
            story_node.presentation_type = _normalize_presentation_type(
                updates["presentation_type"]
            )
            changed_fields.append("presentationType")

        if "content" in updates:
            story_node.content = _normalize_content(updates["content"])
            changed_fields.append("content")

        if "sort_order" in updates and updates["sort_order"] is not None:
            story_node.sort_order = updates["sort_order"]
            changed_fields.append("sortOrder")

        session.flush()

        _audit(
            session,
            admin=admin,
            action="story_node.updated",
            story_node_id=story_node.id,
            metadata={
                "changedFields": changed_fields,
                "status": story_node.status,
            },
            request=request,
        )

        return {"story_node": _serialize(story_node)}


@router.post("/{story_node_id}/publish")
def publish_admin_story_node(
    story_node_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(STORY_NODES_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        story_node = _lock_story_node(session, story_node_id)
        _ensure_editable(story_node)

        # (в): повторный publish запрещён (стиль admin_chapters).
        if story_node.status == "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Story-node уже опубликован.",
            )

        # Строгая иерархия: глава берётся под row-lock в той же транзакции.
        chapter = _lock_chapter(session, story_node.chapter_id)
        if chapter.status != "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Story-node публикуется только в опубликованной главе.",
            )

        previous_status = story_node.status
        story_node.status = "published"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="story_node.published",
            story_node_id=story_node.id,
            metadata={
                "slug": story_node.slug,
                "previousStatus": previous_status,
                "chapterId": story_node.chapter_id,
            },
            request=request,
        )

        return {"story_node": _serialize(story_node)}


@router.post("/{story_node_id}/archive")
def archive_admin_story_node(
    story_node_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(STORY_NODES_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        story_node = _lock_story_node(session, story_node_id)

        if story_node.status == "archived":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Story-node уже архивирован.",
            )

        if story_node.status != "published":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Архивировать можно только опубликованный story-node.",
            )

        previous_status = story_node.status
        story_node.status = "archived"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="story_node.archived",
            story_node_id=story_node.id,
            metadata={
                "slug": story_node.slug,
                "previousStatus": previous_status,
                "chapterId": story_node.chapter_id,
            },
            request=request,
        )

        return {"story_node": _serialize(story_node)}