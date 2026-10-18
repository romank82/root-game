"""Admin CRUD for minigame profile settings (Sprint 8.17, шаг 3).

Справочник переиспользуемых настроек мини-игр (cipher / code_repair /
text_answer): один профиль может применяться во многих миссиях. Поля и роли
сверены с admin_geo_zones.py (CRUD, аудит через write_admin_audit, rights).

Жизненный цикл: draft -> published -> archived. reverse-переходы запрещены;
опубликовать можно только профиль с непустыми настройками (иначе миссия,
использующая профиль, была бы нерешаемой).
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
from app.models import AdminUser, MinigameProfile

router = APIRouter(
    prefix="/api/v1/admin/minigame-profiles",
    tags=["admin-minigame-profiles"],
)

MINIGAME_PROFILES_READ_PERMISSION = "minigame_profiles.read"
MINIGAME_PROFILES_MANAGE_PERMISSION = "minigame_profiles.manage"

# Сверено с mission_type в content_contract.py / admin_missions.py.
VALID_GAME_TYPES = frozenset({"cipher", "code_repair", "text_answer"})


class AdminMinigameProfileCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    game_type: str = Field(min_length=1, max_length=64)
    settings: dict[str, Any] = Field(default_factory=dict)


class AdminMinigameProfileUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    game_type: str | None = Field(default=None, min_length=1, max_length=64)
    settings: dict[str, Any] | None = None


class AdminMinigameProfileResponse(BaseModel):
    """Схема ответа (camelCase) для OpenAPI-документации."""

    id: str
    name: str
    gameType: str
    settings: dict[str, Any]
    status: str
    createdAt: str | None = None
    updatedAt: str | None = None


def _new_id() -> str:
    return f"minigame-profile-{uuid4().hex}"


def _normalize_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="name не может быть пустым.")
    return stripped


def _validate_game_type(game_type: str) -> None:
    if game_type not in VALID_GAME_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                "Недопустимый game_type. Разрешены: "
                f"{', '.join(sorted(VALID_GAME_TYPES))}."
            ),
        )


def _serialize(profile: MinigameProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "gameType": profile.game_type,
        "settings": profile.settings or {},
        "status": profile.status,
        "createdAt": profile.created_at.isoformat() if profile.created_at else None,
        "updatedAt": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    profile_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="minigame_profile",
        entity_id=profile_id,
        request=request,
        permission_code=MINIGAME_PROFILES_MANAGE_PERMISSION,
        metadata=metadata,
    )


@router.get("")
def list_admin_minigame_profiles(
    _admin: AdminUser = Depends(
        require_permission(MINIGAME_PROFILES_READ_PERMISSION)
    ),
):
    with SessionLocal.begin() as session:
        profiles = session.scalars(
            select(MinigameProfile).order_by(MinigameProfile.name)
        ).all()
        return {
            "minigameProfiles": [_serialize(profile) for profile in profiles]
        }


@router.get("/{profile_id}")
def get_admin_minigame_profile(
    profile_id: str,
    _admin: AdminUser = Depends(
        require_permission(MINIGAME_PROFILES_READ_PERMISSION)
    ),
):
    with SessionLocal.begin() as session:
        profile = session.get(MinigameProfile, profile_id)

        if profile is None:
            raise HTTPException(
                status_code=404, detail="Профиль мини-игры не найден."
            )

        return {"minigameProfile": _serialize(profile)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_minigame_profile(
    payload: AdminMinigameProfileCreatePayload,
    request: Request,
    admin: AdminUser = Depends(
        require_permission(MINIGAME_PROFILES_MANAGE_PERMISSION)
    ),
):
    name = _normalize_name(payload.name)
    _validate_game_type(payload.game_type)

    with SessionLocal.begin() as session:
        if session.scalar(
            select(MinigameProfile.id).where(MinigameProfile.name == name)
        ):
            raise HTTPException(
                status_code=409,
                detail="Профиль мини-игры с таким name уже существует.",
            )

        profile = MinigameProfile(
            id=_new_id(),
            name=name,
            game_type=payload.game_type,
            settings=payload.settings or {},
            status="draft",
        )
        session.add(profile)
        session.flush()

        _audit(
            session,
            admin=admin,
            action="minigame_profile.created",
            profile_id=profile.id,
            metadata={
                "name": profile.name,
                "gameType": profile.game_type,
                "status": profile.status,
            },
            request=request,
        )

        return {"minigameProfile": _serialize(profile)}


@router.patch("/{profile_id}")
def update_admin_minigame_profile(
    profile_id: str,
    payload: AdminMinigameProfileUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(
        require_permission(MINIGAME_PROFILES_MANAGE_PERMISSION)
    ),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    name = _normalize_name(payload.name) if payload.name is not None else None
    if payload.game_type is not None:
        _validate_game_type(payload.game_type)

    with SessionLocal.begin() as session:
        profile = session.get(MinigameProfile, profile_id)

        if profile is None:
            raise HTTPException(
                status_code=404, detail="Профиль мини-игры не найден."
            )

        changed_fields: list[str] = []

        if name is not None and name != profile.name:
            existing = session.scalar(
                select(MinigameProfile.id).where(
                    MinigameProfile.name == name,
                    MinigameProfile.id != profile.id,
                )
            )
            if existing is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Профиль мини-игры с таким name уже существует.",
                )
            profile.name = name
            changed_fields.append("name")

        if payload.game_type is not None:
            profile.game_type = payload.game_type
            changed_fields.append("game_type")

        if payload.settings is not None:
            profile.settings = payload.settings or {}
            changed_fields.append("settings")

        session.flush()

        _audit(
            session,
            admin=admin,
            action="minigame_profile.updated",
            profile_id=profile.id,
            metadata={
                "changedFields": changed_fields,
                "status": profile.status,
            },
            request=request,
        )

        return {"minigameProfile": _serialize(profile)}


@router.post("/{profile_id}/publish")
def publish_admin_minigame_profile(
    profile_id: str,
    request: Request,
    admin: AdminUser = Depends(
        require_permission(MINIGAME_PROFILES_MANAGE_PERMISSION)
    ),
):
    with SessionLocal.begin() as session:
        profile = session.get(MinigameProfile, profile_id)

        if profile is None:
            raise HTTPException(
                status_code=404, detail="Профиль мини-игры не найден."
            )

        if profile.status == "published":
            raise HTTPException(
                status_code=422, detail="Профиль уже опубликован."
            )

        if not profile.settings:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Нельзя опубликовать профиль с пустыми настройками: "
                    "заполните settings."
                ),
            )

        profile.status = "published"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="minigame_profile.published",
            profile_id=profile.id,
            metadata={"status": profile.status, "gameType": profile.game_type},
            request=request,
        )

        return {"minigameProfile": _serialize(profile)}


@router.post("/{profile_id}/archive")
def archive_admin_minigame_profile(
    profile_id: str,
    request: Request,
    admin: AdminUser = Depends(
        require_permission(MINIGAME_PROFILES_MANAGE_PERMISSION)
    ),
):
    with SessionLocal.begin() as session:
        profile = session.get(MinigameProfile, profile_id)

        if profile is None:
            raise HTTPException(
                status_code=404, detail="Профиль мини-игры не найден."
            )

        if profile.status == "archived":
            raise HTTPException(
                status_code=422, detail="Профиль уже архивирован."
            )

        profile.status = "archived"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="minigame_profile.archived",
            profile_id=profile.id,
            metadata={"status": profile.status, "gameType": profile.game_type},
            request=request,
        )

        return {"minigameProfile": _serialize(profile)}


