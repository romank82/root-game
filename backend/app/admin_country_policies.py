"""Админ-CRUD политик по странам (13.2-a): list/create/update/delete.

- GET    /api/v1/admin/country-policies            — список с пагинацией.
- POST   /api/v1/admin/country-policies            — создать политику.
- PATCH  /api/v1/admin/country-policies/{id}       — частичное обновление
  (policy/restricted_features/reason; country_code менять нельзя,
  extra="forbid" -> 422).
- DELETE /api/v1/admin/country-policies/{id}       — удалить политику.

Семантика policy (модель 13.1): allowed (default, всё разрешено),
restricted (вход можно, функционал из restricted_features — нельзя),
blocked (вход нельзя). Отсутствие записи = allowed.

Применение политик (gate при входе для blocked, ограничение функционала
для restricted) — 13.2-b, отдельный шаг; здесь только CRUD + аудит.

Удаление — hard delete: политика страны это настройка, не история
игрока/ledger; immutable аудит (до/после) сохраняется в admin_audit_log
(entity_id — строка без FK на таблицу политики), поэтому после удаления
факт создания/изменения/удаления политики полностью восстановим по аудиту.
Soft-delete (status='archived') здесь не нужен: у политик нет зависимых
FK и player-прогресса, а archived-семантика зарезервирована для контента.

Permission: players.manage (модерация игроков) — без новой permission.
Политики стран — частный случай управления игроками; admin_player_inventory
и admin_player_mission уже используют players.manage. Отдельная permission
(country_policies.manage) добавится позже, если появятся требования
разделения ролей.
"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.models import AdminUser, CountryPolicy

router = APIRouter(
    prefix="/api/v1/admin/country-policies",
    tags=["admin-country-policies"],
)

PLAYERS_MANAGE_PERMISSION = "players.manage"

VALID_POLICIES = ("allowed", "restricted", "blocked")
VALID_FEATURES = frozenset({"transfer", "mission", "team"})

DEFAULT_LIST_LIMIT = 20
MAX_LIST_LIMIT = 100


class CountryPolicyPayload(BaseModel):
    """Создание политики страны (13.2-a)."""

    model_config = ConfigDict(extra="forbid")

    country_code: str = Field(..., min_length=2, max_length=2)
    policy: str = Field(..., pattern="^(allowed|restricted|blocked)$")
    restricted_features: list[str] | None = None
    reason: str | None = Field(None, max_length=255)


class CountryPolicyUpdatePayload(BaseModel):
    """Частичное обновление политики (country_code менять нельзя)."""

    model_config = ConfigDict(extra="forbid")

    policy: str | None = Field(None, pattern="^(allowed|restricted|blocked)$")
    restricted_features: list[str] | None = None
    reason: str | None = Field(None, max_length=255)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:24]}"


def _validate_features(features: list[str] | None) -> None:
    """restricted_features — подмножество {'transfer','mission','team'}."""
    if features is None:
        return
    invalid = [feature for feature in features if feature not in VALID_FEATURES]
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "restricted_features может содержать только: "
                f"{', '.join(sorted(VALID_FEATURES))}."
            ),
        )


def _serialize_country_policy(policy: CountryPolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "countryCode": policy.country_code,
        "policy": policy.policy,
        "restrictedFeatures": policy.restricted_features,
        "reason": policy.reason,
        "createdAt": policy.created_at.isoformat() if policy.created_at else None,
        "updatedAt": policy.updated_at.isoformat() if policy.updated_at else None,
    }


@router.get("", response_model=None)
def list_country_policies(
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Список политик стран (пагинация, сортировка по country_code)."""
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)

    with SessionLocal() as session:  # read-only, не begin()
        total = session.scalar(
            select(func.count()).select_from(CountryPolicy)
        ) or 0
        rows = session.execute(
            select(CountryPolicy)
            .order_by(CountryPolicy.country_code)
            .offset(offset)
            .limit(limit)
        ).scalars().all()
        policies = [_serialize_country_policy(policy) for policy in rows]

    return {
        "policies": policies,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("", response_model=None)
def create_country_policy(
    payload: CountryPolicyPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Создать политику для страны (403/409/422 по защитам ниже)."""
    country_code = payload.country_code.strip().upper()
    if len(country_code) != 2 or not country_code.isalpha():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="country_code должен быть ISO-2 (2 буквы).",
        )
    _validate_features(payload.restricted_features)

    with SessionLocal.begin() as session:
        existing = session.scalar(
            select(CountryPolicy).where(CountryPolicy.country_code == country_code)
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Политика для страны уже существует.",
            )

        policy = CountryPolicy(
            id=_new_id("country-policy"),
            country_code=country_code,
            policy=payload.policy,
            restricted_features=(
                list(payload.restricted_features)
                if payload.restricted_features is not None
                else None
            ),
            reason=payload.reason,
        )
        session.add(policy)
        try:
            session.flush()
            # Подтянуть серверные created_at/updated_at (server_default now()).
            session.refresh(policy)
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Политика для страны уже существует.",
            ) from error

        after = _serialize_country_policy(policy)
        write_admin_audit(
            session,
            actor=admin,
            action="country_policy.created",
            entity_type="country_policy",
            entity_id=policy.id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=None,
            after=after,
            metadata={},
        )
        return {"policy": after}


@router.patch("/{policy_id}", response_model=None)
def update_country_policy(
    policy_id: str,
    payload: CountryPolicyUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, Any]:
    """Частичное обновление политики (country_code менять нельзя: 422)."""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Передайте хотя бы одно поле для изменения.",
        )
    if "restricted_features" in updates:
        _validate_features(updates["restricted_features"])

    with SessionLocal.begin() as session:
        policy = session.get(CountryPolicy, policy_id)
        if policy is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Политика не найдена.",
            )

        before = _serialize_country_policy(policy)

        if "policy" in updates:
            policy.policy = updates["policy"]
        if "restricted_features" in updates:
            policy.restricted_features = (
                list(updates["restricted_features"])
                if updates["restricted_features"] is not None
                else None
            )
        if "reason" in updates:
            policy.reason = updates["reason"]

        session.flush()
        session.refresh(policy)
        after = _serialize_country_policy(policy)

        write_admin_audit(
            session,
            actor=admin,
            action="country_policy.updated",
            entity_type="country_policy",
            entity_id=policy.id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=before,
            after=after,
            metadata={},
        )
        return {"policy": after}


@router.delete("/{policy_id}", response_model=None)
def delete_country_policy(
    policy_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(PLAYERS_MANAGE_PERMISSION)),
) -> dict[str, bool]:
    """Удалить политику страны (hard delete: настройка, не история)."""
    with SessionLocal.begin() as session:
        policy = session.get(CountryPolicy, policy_id)
        if policy is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Политика не найдена.",
            )

        before = _serialize_country_policy(policy)
        write_admin_audit(
            session,
            actor=admin,
            action="country_policy.deleted",
            entity_type="country_policy",
            entity_id=policy.id,
            request=request,
            permission_code=PLAYERS_MANAGE_PERMISSION,
            before=before,
            after=None,
            metadata={},
        )
        session.delete(policy)

    return {"deleted": True}