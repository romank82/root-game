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
from app.models import AdminUser, Item, RewardPool, RewardPoolEntry
from app.slug_utils import _normalize_slug


router = APIRouter(prefix="/api/v1/admin/reward-pools", tags=["admin-reward-pools"])

REWARD_POOLS_READ_PERMISSION = "reward_pools.read"
REWARD_POOLS_MANAGE_PERMISSION = "reward_pools.manage"
VALID_POOL_STATUSES = {"draft", "published"}
VALID_REWARD_TYPES = {"currency", "item"}


class AdminRewardPoolEntryPayload(BaseModel):
    reward_type: str = Field(min_length=1, max_length=64)
    amount: int | None = Field(default=None, ge=1, le=1_000_000)
    item_id: str | None = Field(default=None, max_length=64)
    reward_value: dict[str, Any] = Field(default_factory=dict)
    weight: int = Field(default=1, ge=1, le=1_000_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)


class AdminRewardPoolCreatePayload(BaseModel):
    slug: str = Field(min_length=3, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    entries: list[AdminRewardPoolEntryPayload] = Field(default_factory=list)


class AdminRewardPoolUpdatePayload(BaseModel):
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    status: str | None = Field(default=None, min_length=1, max_length=32)
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    entries: list[AdminRewardPoolEntryPayload] | None = None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _validate_entries(
    session: Session,
    entries: list[AdminRewardPoolEntryPayload],
) -> None:
    for entry in entries:
        if entry.reward_type not in VALID_REWARD_TYPES:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Недопустимый reward_type. Разрешены: "
                    "currency, item."
                ),
            )

        if entry.reward_type == "currency":
            if entry.amount is None or entry.amount <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Награда currency должна иметь положительный amount.",
                )

            if entry.reward_value.get("currency") != "ROOT":
                raise HTTPException(
                    status_code=422,
                    detail='Для currency reward_value должен содержать {"currency":"ROOT"}.',
                )

        elif entry.reward_type == "item":
            if not entry.item_id:
                raise HTTPException(
                    status_code=422,
                    detail="Награда item должна содержать item_id.",
                )

            if session.get(Item, entry.item_id) is None:
                raise HTTPException(
                    status_code=422,
                    detail="Награда item ссылается на несуществующий item_id.",
                )

        if entry.weight <= 0:
            raise HTTPException(
                status_code=422,
                detail="Вес награды (weight) должен быть положительным.",
            )

        if entry.weight > 1_000_000:
            raise HTTPException(
                status_code=422,
                detail="Вес награды (weight) не может превышать 1 000 000.",
            )


def _replace_entries(
    session: Session,
    *,
    pool_id: str,
    entries: list[AdminRewardPoolEntryPayload],
) -> None:
    old_entries = session.scalars(
        select(RewardPoolEntry).where(RewardPoolEntry.pool_id == pool_id)
    ).all()

    for old_entry in old_entries:
        session.delete(old_entry)

    session.flush()

    for entry in entries:
        session.add(
            RewardPoolEntry(
                id=_new_id("reward-pool-entry"),
                pool_id=pool_id,
                reward_type=entry.reward_type,
                amount=entry.amount,
                item_id=entry.item_id,
                reward_value=entry.reward_value,
                weight=entry.weight,
                sort_order=entry.sort_order,
            )
        )


def _serialize_entry(entry: RewardPoolEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "rewardType": entry.reward_type,
        "amount": entry.amount,
        "itemId": entry.item_id,
        "rewardValue": entry.reward_value,
        "weight": entry.weight,
        "sortOrder": entry.sort_order,
    }


def _serialize_pool(
    session: Session,
    pool: RewardPool,
) -> dict[str, Any]:
    entries = session.scalars(
        select(RewardPoolEntry)
        .where(RewardPoolEntry.pool_id == pool.id)
        .order_by(RewardPoolEntry.sort_order, RewardPoolEntry.id)
    ).all()

    return {
        "id": pool.id,
        "slug": pool.slug,
        "title": pool.title,
        "description": pool.description,
        "status": pool.status,
        "sortOrder": pool.sort_order,
        "entries": [_serialize_entry(entry) for entry in entries],
        "createdAt": pool.created_at.isoformat() if pool.created_at else None,
        "updatedAt": pool.updated_at.isoformat() if pool.updated_at else None,
    }


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    pool_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="reward_pool",
        entity_id=pool_id,
        request=request,
        permission_code=REWARD_POOLS_MANAGE_PERMISSION,
        metadata=metadata,
    )


@router.get("")
def list_admin_reward_pools(
    _admin: AdminUser = Depends(require_permission(REWARD_POOLS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        pools = session.scalars(
            select(RewardPool).order_by(
                RewardPool.status, RewardPool.sort_order, RewardPool.id
            )
        ).all()

        return {
            "rewardPools": [
                _serialize_pool(session, pool)
                for pool in pools
            ]
        }


@router.get("/{pool_id}")
def get_admin_reward_pool(
    pool_id: str,
    _admin: AdminUser = Depends(require_permission(REWARD_POOLS_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        pool = session.get(RewardPool, pool_id)

        if pool is None:
            raise HTTPException(status_code=404, detail="Пул наград не найден.")

        return {"rewardPool": _serialize_pool(session, pool)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_reward_pool(
    payload: AdminRewardPoolCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(REWARD_POOLS_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        slug = _normalize_slug(payload.slug)

        if session.scalar(select(RewardPool.id).where(RewardPool.slug == slug)):
            raise HTTPException(
                status_code=409,
                detail="Пул наград с таким slug уже существует.",
            )

        _validate_entries(session, payload.entries)

        pool = RewardPool(
            id=_new_id("reward-pool"),
            slug=slug,
            title=payload.title.strip(),
            description=payload.description.strip() if payload.description else None,
            status="draft",
            sort_order=payload.sort_order,
        )
        session.add(pool)
        session.flush()

        _replace_entries(
            session,
            pool_id=pool.id,
            entries=payload.entries,
        )
        session.flush()

        _audit(
            session,
            admin=admin,
            action="reward_pool.created",
            pool_id=pool.id,
            metadata={
                "slug": pool.slug,
                "status": pool.status,
                "entryCount": len(payload.entries),
            },
            request=request,
        )

        return {"rewardPool": _serialize_pool(session, pool)}


@router.patch("/{pool_id}")
def update_admin_reward_pool(
    pool_id: str,
    payload: AdminRewardPoolUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(REWARD_POOLS_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        pool = session.get(RewardPool, pool_id)

        if pool is None:
            raise HTTPException(status_code=404, detail="Пул наград не найден.")

        changed_fields: list[str] = []

        if "slug" in updates:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(RewardPool.id).where(
                    RewardPool.slug == slug,
                    RewardPool.id != pool.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Пул наград с таким slug уже существует.",
                )
            pool.slug = slug
            changed_fields.append("slug")

        scalar_fields = {
            "title": "title",
            "description": "description",
            "status": "status",
            "sort_order": "sortOrder",
        }

        for field_name, audit_name in scalar_fields.items():
            if field_name not in updates:
                continue

            value = updates[field_name]

            if field_name == "title":
                value = value.strip()

            if field_name == "description" and value is not None:
                value = value.strip() or None

            if field_name == "status" and value not in VALID_POOL_STATUSES:
                raise HTTPException(
                    status_code=422,
                    detail="Недопустимый статус пула. Разрешены: draft, published.",
                )

            setattr(pool, field_name, value)
            changed_fields.append(audit_name)

        if "entries" in updates:
            _validate_entries(session, payload.entries or [])
            _replace_entries(
                session,
                pool_id=pool.id,
                entries=payload.entries or [],
            )
            changed_fields.append("entries")

        session.flush()

        _audit(
            session,
            admin=admin,
            action="reward_pool.updated",
            pool_id=pool.id,
            metadata={
                "changedFields": changed_fields,
                "entryCount": (
                    len(payload.entries)
                    if "entries" in updates and payload.entries is not None
                    else None
                ),
            },
            request=request,
        )

        return {"rewardPool": _serialize_pool(session, pool)}
