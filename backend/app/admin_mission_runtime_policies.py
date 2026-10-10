from __future__ import annotations

from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.geo_team_runtime_models import MissionRuntimePolicy
from app.models import AdminUser, Item, Mission
from app.runtime_policy_contract import (
    RuntimePolicyValidationError,
    validate_runtime_policy,
)


router = APIRouter(
    prefix="/api/v1/admin/mission-runtime-policies",
    tags=["admin-mission-runtime-policies"],
)

router_missions = APIRouter(
    prefix="/api/v1/admin/missions",
    tags=["admin-missions-runtime-policy"],
)

# Option A: policy is mission configuration, so the mission permission pair is
# reused. Switching to dedicated codes is a migration-only change (see plan 2.1).
POLICY_READ_PERMISSION = "missions.read"
POLICY_MANAGE_PERMISSION = "missions.manage"

VALID_POLICY_STATUSES = {"draft", "published", "archived"}

# Mirrors backend/app/runtime_policy_contract.py constants so Pydantic rejects
# out-of-range values early. The contract remains the single source of truth.
ENTRY_ROOT_ATOMIC_MAX = 2_147_483_647
MAX_ATTEMPTS_MAX = 10
DEADLINE_SECONDS_MAX = 86_400

UPDATABLE_FIELDS = (
    "entry_root_atomic",
    "max_attempts",
    "attempt_deadline_seconds",
    "repeatability_policy",
    "required_items_json",
    "challenge_policy_json",
    "reward_policy_json",
    "fallback_policy_json",
    "feature_flags_json",
)


class AdminMissionRuntimePolicyCreatePayload(BaseModel):
    mission_id: str = Field(min_length=1, max_length=64)
    entry_root_atomic: int = Field(ge=0, le=ENTRY_ROOT_ATOMIC_MAX)
    max_attempts: int = Field(ge=1, le=MAX_ATTEMPTS_MAX)
    attempt_deadline_seconds: int = Field(ge=1, le=DEADLINE_SECONDS_MAX)
    repeatability_policy: str = Field(min_length=1, max_length=64)
    required_items_json: dict[str, Any]
    challenge_policy_json: dict[str, Any]
    reward_policy_json: dict[str, Any]
    fallback_policy_json: dict[str, Any] | None = None
    feature_flags_json: dict[str, Any] = Field(default_factory=dict)


class AdminMissionRuntimePolicyUpdatePayload(BaseModel):
    entry_root_atomic: int | None = Field(
        default=None, ge=0, le=ENTRY_ROOT_ATOMIC_MAX
    )
    max_attempts: int | None = Field(default=None, ge=1, le=MAX_ATTEMPTS_MAX)
    attempt_deadline_seconds: int | None = Field(
        default=None, ge=1, le=DEADLINE_SECONDS_MAX
    )
    repeatability_policy: str | None = Field(default=None, min_length=1, max_length=64)
    required_items_json: dict[str, Any] | None = None
    challenge_policy_json: dict[str, Any] | None = None
    reward_policy_json: dict[str, Any] | None = None
    fallback_policy_json: dict[str, Any] | None = None


class MissionRuntimePolicyUpsertPayload(BaseModel):
    """Minimal mission-scoped payload for the runtime policy upsert.

    Only the fields the admin UI edits are exposed. The contract-only fields
    (reward policy, fallback, feature flags) keep their defaults and are built
    by the endpoint. ``challenge_policy_json`` stays optional in the schema so
    team missions can supply their required cipher challenge, while solo /
    race / co-op missions may omit it.
    """

    entry_root_atomic: int = Field(ge=0, le=ENTRY_ROOT_ATOMIC_MAX)
    required_items_json: dict[str, Any] = Field(
        default_factory=lambda: {"schemaVersion": 1, "items": []}
    )
    max_attempts: int = Field(default=3, ge=1, le=MAX_ATTEMPTS_MAX)
    attempt_deadline_seconds: int = Field(
        default=3600, ge=1, le=DEADLINE_SECONDS_MAX
    )
    repeatability_policy: str = Field(default="after_terminal", max_length=64)
    challenge_policy_json: dict[str, Any] | None = None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _get_mission_or_422(session: Session, mission_id: str) -> Mission:
    mission = session.get(Mission, mission_id)
    if mission is None:
        raise HTTPException(status_code=422, detail="Миссия не найдена.")
    return mission


def _get_policy_or_404(session: Session, policy_id: str) -> MissionRuntimePolicy:
    policy = session.get(MissionRuntimePolicy, policy_id)
    if policy is None:
        raise HTTPException(
            status_code=404, detail="Правило входа миссии не найдено."
        )
    return policy


def _next_version(session: Session, mission_id: str) -> int:
    latest = session.scalar(
        select(func.max(MissionRuntimePolicy.version)).where(
            MissionRuntimePolicy.mission_id == mission_id
        )
    )
    return (latest or 0) + 1


def _policy_arguments(
    *,
    mission_id: str,
    entry_root_atomic: int,
    max_attempts: int,
    attempt_deadline_seconds: int,
    repeatability_policy: str,
    required_items_json: dict[str, Any],
    challenge_policy_json: dict[str, Any],
    reward_policy_json: dict[str, Any],
    fallback_policy_json: dict[str, Any] | None,
    feature_flags_json: dict[str, Any],
) -> dict[str, Any]:
    return {
        "mission_id": mission_id,
        "entry_root_atomic": entry_root_atomic,
        "max_attempts": max_attempts,
        "attempt_deadline_seconds": attempt_deadline_seconds,
        "repeatability_policy": repeatability_policy,
        "required_items_json": required_items_json,
        "challenge_policy_json": challenge_policy_json,
        "reward_policy_json": reward_policy_json,
        "fallback_policy_json": fallback_policy_json,
        "feature_flags_json": feature_flags_json,
    }


def _policy_arguments_from_policy(
    policy: MissionRuntimePolicy,
) -> dict[str, Any]:
    return _policy_arguments(
        mission_id=policy.mission_id,
        entry_root_atomic=policy.entry_root_atomic,
        max_attempts=policy.max_attempts,
        attempt_deadline_seconds=policy.attempt_deadline_seconds,
        repeatability_policy=policy.repeatability_policy,
        required_items_json=policy.required_items_json,
        challenge_policy_json=policy.challenge_policy_json,
        reward_policy_json=policy.reward_policy_json,
        fallback_policy_json=policy.fallback_policy_json,
        feature_flags_json=policy.feature_flags_json,
    )
def _validate_policy_via_contract(
    mission: Mission,
    *,
    mission_id: str,
    entry_root_atomic: Any,
    max_attempts: Any,
    attempt_deadline_seconds: Any,
    repeatability_policy: Any,
    required_items_json: Any,
    challenge_policy_json: Any,
    reward_policy_json: Any,
    fallback_policy_json: Any,
    feature_flags_json: Any,
) -> dict[str, Any]:
    """Run the pure contract validator and map failures to 422.

    RuntimePolicyValidationError messages never echo submitted values, so they
    are safe to expose in an HTTP detail.
    """
    try:
        return validate_runtime_policy(
            mission_category=mission.mission_category,
            entry_root_atomic=entry_root_atomic,
            max_attempts=max_attempts,
            attempt_deadline_seconds=attempt_deadline_seconds,
            repeatability_policy=repeatability_policy,
            required_items_json=required_items_json,
            challenge_policy_json=challenge_policy_json,
            reward_policy_json=reward_policy_json,
            fallback_policy_json=fallback_policy_json,
            feature_flags_json=feature_flags_json,
        )
    except RuntimePolicyValidationError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


def _validate_publish_dependencies(
    session: Session,
    normalized: dict[str, Any],
) -> None:
    """Publish-time DB-backed checks required by the solo policy contract:
    every required item must exist and be published.

    The pure contract deliberately leaves database-dependent checks to the
    admin API layer that owns a session.
    """
    for requirement in normalized["requiredItems"]["items"]:
        item = session.get(Item, requirement["itemId"])
        if item is None or item.status != "published":
            raise HTTPException(
                status_code=422,
                detail=(
                    "Требуемый предмет не найден или не опубликован: "
                    f"{requirement['itemId']}."
                ),
            )


def _serialize_policy(policy: MissionRuntimePolicy) -> dict[str, Any]:
    return {
        "id": policy.id,
        "missionId": policy.mission_id,
        "version": policy.version,
        "status": policy.status,
        "entryRootAtomic": policy.entry_root_atomic,
        "maxAttempts": policy.max_attempts,
        "attemptDeadlineSeconds": policy.attempt_deadline_seconds,
        "repeatabilityPolicy": policy.repeatability_policy,
        "requiredItemsJson": policy.required_items_json,
        "challengePolicyJson": policy.challenge_policy_json,
        "rewardPolicyJson": policy.reward_policy_json,
        "fallbackPolicyJson": policy.fallback_policy_json,
        "featureFlagsJson": policy.feature_flags_json,
        "createdAt": policy.created_at.isoformat() if policy.created_at else None,
        "updatedAt": policy.updated_at.isoformat() if policy.updated_at else None,
    }


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    policy: MissionRuntimePolicy,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="mission_runtime_policy",
        entity_id=policy.id,
        request=request,
        permission_code=POLICY_MANAGE_PERMISSION,
        metadata=metadata,
    )


def _publish_policy(
    session: Session,
    policy: MissionRuntimePolicy,
) -> tuple[bool, str | None]:
    """Transition to published; archive any previous published version.

    Returns ``(changed, previously_archived_policy_id)``. ``changed`` is False
    on an idempotent call for an already published row.
    """
    if policy.status == "published":
        return False, None

    previous = session.scalar(
        select(MissionRuntimePolicy).where(
            MissionRuntimePolicy.mission_id == policy.mission_id,
            MissionRuntimePolicy.status == "published",
            MissionRuntimePolicy.id != policy.id,
        )
    )
    archived_id: str | None = None
    if previous is not None:
        previous.status = "archived"
        # Flush immediately so the previous row stops being "published"
        # before the new one becomes "published"; the partial unique index
        # uq_mission_runtime_policies_one_published_per_mission is enforced
        # per statement and SQLAlchemy may otherwise batch both UPDATEs.
        session.flush()
        archived_id = previous.id

    policy.status = "published"
    return True, archived_id
@router.get("")
def list_admin_mission_runtime_policies(
    mission_id: str | None = None,
    _admin: AdminUser = Depends(require_permission(POLICY_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        statement = select(MissionRuntimePolicy).order_by(
            MissionRuntimePolicy.mission_id,
            MissionRuntimePolicy.status,
            MissionRuntimePolicy.version.desc(),
        )
        if mission_id:
            statement = statement.where(
                MissionRuntimePolicy.mission_id == mission_id
            )
        policies = session.scalars(statement).all()

        return {
            "missionRuntimePolicies": [
                _serialize_policy(policy) for policy in policies
            ]
        }


@router.get("/{policy_id}")
def get_admin_mission_runtime_policy(
    policy_id: str,
    _admin: AdminUser = Depends(require_permission(POLICY_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        policy = _get_policy_or_404(session, policy_id)
        return {"missionRuntimePolicy": _serialize_policy(policy)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_mission_runtime_policy(
    payload: AdminMissionRuntimePolicyCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(POLICY_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        mission = _get_mission_or_422(session, payload.mission_id)

        arguments = _policy_arguments(
            mission_id=payload.mission_id,
            entry_root_atomic=payload.entry_root_atomic,
            max_attempts=payload.max_attempts,
            attempt_deadline_seconds=payload.attempt_deadline_seconds,
            repeatability_policy=payload.repeatability_policy,
            required_items_json=payload.required_items_json,
            challenge_policy_json=payload.challenge_policy_json,
            reward_policy_json=payload.reward_policy_json,
            fallback_policy_json=payload.fallback_policy_json,
            feature_flags_json=payload.feature_flags_json,
        )
        _validate_policy_via_contract(mission, **arguments)

        version = _next_version(session, payload.mission_id)

        policy = MissionRuntimePolicy(
            id=_new_id("mission-runtime-policy"),
            version=version,
            status="draft",
            **arguments,
        )
        session.add(policy)
        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission_runtime_policy.created",
            policy=policy,
            metadata={
                "missionId": policy.mission_id,
                "version": policy.version,
                "status": policy.status,
            },
            request=request,
        )

        return {"missionRuntimePolicy": _serialize_policy(policy)}


@router.patch("/{policy_id}")
def update_admin_mission_runtime_policy(
    policy_id: str,
    payload: AdminMissionRuntimePolicyUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(POLICY_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        policy = _get_policy_or_404(session, policy_id)

        if policy.status == "archived":
            raise HTTPException(
                status_code=409,
                detail="Архивные правила входа миссии изменять нельзя.",
            )
        if policy.status == "published":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Опубликованные правила входа миссии изменять нельзя. "
                    "Создайте новую версию и опубликуйте её."
                ),
            )

        for field_name in UPDATABLE_FIELDS:
            if field_name in updates:
                setattr(policy, field_name, updates[field_name])

        mission = session.get(Mission, policy.mission_id)
        if mission is None:  # FK RESTRICT makes this unreachable; safety net.
            raise HTTPException(status_code=422, detail="Миссия не найдена.")
        _validate_policy_via_contract(
            mission, **_policy_arguments_from_policy(policy)
        )

        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission_runtime_policy.updated",
            policy=policy,
            metadata={
                "missionId": policy.mission_id,
                "version": policy.version,
                "status": policy.status,
                "changedFields": [
                    field for field in UPDATABLE_FIELDS if field in updates
                ],
            },
            request=request,
        )

        return {"missionRuntimePolicy": _serialize_policy(policy)}
@router.post("/{policy_id}/publish")
def publish_admin_mission_runtime_policy(
    policy_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(POLICY_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        policy = _get_policy_or_404(session, policy_id)

        if policy.status == "archived":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Архивные правила входа миссии нельзя публиковать. "
                    "Создайте новую версию."
                ),
            )

        mission = session.get(Mission, policy.mission_id)
        normalized = _validate_policy_via_contract(
            mission, **_policy_arguments_from_policy(policy)
        )
        _validate_publish_dependencies(session, normalized)

        changed, archived_id = _publish_policy(session, policy)
        if not changed:
            # Idempotent repeat of an already published policy.
            return {"missionRuntimePolicy": _serialize_policy(policy)}

        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission_runtime_policy.published",
            policy=policy,
            metadata={
                "missionId": policy.mission_id,
                "version": policy.version,
                "previousStatus": "draft",
                "previousPublishedArchived": archived_id,
            },
            request=request,
        )

        return {"missionRuntimePolicy": _serialize_policy(policy)}


@router.post("/{policy_id}/unpublish")
def unpublish_admin_mission_runtime_policy(
    policy_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(POLICY_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        policy = _get_policy_or_404(session, policy_id)

        if policy.status == "archived":
            raise HTTPException(
                status_code=409,
                detail=(
                    "Архивные правила входа миссии нельзя отозвать в черновик."
                ),
            )

        if policy.status == "draft":
            # Idempotent repeat of an already draft policy.
            return {"missionRuntimePolicy": _serialize_policy(policy)}

        previous_status = policy.status
        policy.status = "draft"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission_runtime_policy.unpublished",
            policy=policy,
            metadata={
                "missionId": policy.mission_id,
                "version": policy.version,
                "previousStatus": previous_status,
            },
            request=request,
        )

        return {"missionRuntimePolicy": _serialize_policy(policy)}


@router.post("/{policy_id}/archive")
def archive_admin_mission_runtime_policy(
    policy_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(POLICY_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        policy = _get_policy_or_404(session, policy_id)

        if policy.status == "archived":
            # Idempotent repeat of an already archived policy.
            return {"missionRuntimePolicy": _serialize_policy(policy)}

        previous_status = policy.status
        policy.status = "archived"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission_runtime_policy.archived",
            policy=policy,
            metadata={
                "missionId": policy.mission_id,
                "version": policy.version,
                "previousStatus": previous_status,
            },
            request=request,
        )

        return {"missionRuntimePolicy": _serialize_policy(policy)}
    feature_flags_json: dict[str, Any] | None = None


@router_missions.get("/{mission_id}/runtime-policy")
def get_mission_runtime_policy(
    mission_id: str,
    _actor: AdminUser = Depends(require_permission(POLICY_READ_PERMISSION)),
):
    """Runtime policy миссии (published если есть, иначе последняя draft).

    Возвращает ``{"runtimePolicy": null}`` если policy нет и 404 если миссии
    нет. Ключ ``runtimePolicy`` намеренно отличается от ``missionRuntimePolicy``
    (роутер mission-runtime-policies): endpoint смотрит на миссию, а не на
    отдельную версию policy.
    """
    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        policy = session.scalar(
            select(MissionRuntimePolicy)
            .where(
                MissionRuntimePolicy.mission_id == mission_id,
                MissionRuntimePolicy.status == "published",
            )
            .order_by(
                MissionRuntimePolicy.version.desc(),
                MissionRuntimePolicy.id.desc(),
            )
        )
        if policy is None:
            policy = session.scalar(
                select(MissionRuntimePolicy)
                .where(
                    MissionRuntimePolicy.mission_id == mission_id,
                    MissionRuntimePolicy.status == "draft",
                )
                .order_by(
                    MissionRuntimePolicy.version.desc(),
                    MissionRuntimePolicy.id.desc(),
                )
            )

        return {"runtimePolicy": _serialize_policy(policy) if policy else None}


@router_missions.put("/{mission_id}/runtime-policy")
def upsert_mission_runtime_policy(
    mission_id: str,
    payload: MissionRuntimePolicyUpsertPayload,
    request: Request,
    actor: AdminUser = Depends(require_permission(POLICY_MANAGE_PERMISSION)),
):
    """Создать или обновить runtime policy миссии через mission_id (умный PUT).

    Если у миссии уже есть черновик (status='draft') — он обновляется на
    месте: id и version не меняются, меняется содержимое. Если черновика нет,
    но есть published — создаётся новая draft-версия (version = max + 1).
    Если policy ещё нет — создаётся version 1. Возвращает 404 если миссии нет.

    Опубликованная policy никогда не меняется, archive не перезаписывается.
    Скрытые поля (reward policy, fallback, feature flags) пересобираются из
    новых значений: reward строится под переданный ``max_attempts``, challenge
    обязателен только для команды (mission_category == 'team') — иначе None.
    """
    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        stored_challenge = payload.challenge_policy_json or {}
        policy_values = {
            "entry_root_atomic": payload.entry_root_atomic,
            "required_items_json": payload.required_items_json,
            "max_attempts": payload.max_attempts,
            "attempt_deadline_seconds": payload.attempt_deadline_seconds,
            "repeatability_policy": payload.repeatability_policy,
            "challenge_policy_json": stored_challenge,
            "reward_policy_json": {
                "schemaVersion": 1,
                "attemptMultipliers": [1.0] * payload.max_attempts,
                "rewards": [],
            },
            "fallback_policy_json": None,
            "feature_flags_json": {},
        }

        _validate_policy_via_contract(
            mission, **_policy_arguments(mission_id=mission_id, **policy_values)
        )

        # Умный PUT: если у миссии уже есть черновик, обновляем его на месте
        # (id и version не меняются). Unique-constraint на (mission_id,
        # status='draft') в БД нет — есть только один published и уникальные
        # version, — поэтому «один draft» гарантируем логикой: берём самый
        # свежий (max version).
        draft = session.scalar(
            select(MissionRuntimePolicy)
            .where(
                MissionRuntimePolicy.mission_id == mission_id,
                MissionRuntimePolicy.status == "draft",
            )
            .order_by(
                MissionRuntimePolicy.version.desc(),
                MissionRuntimePolicy.id.desc(),
            )
            .limit(1)
        )

        if draft is not None:
            for field_name, value in policy_values.items():
                setattr(draft, field_name, value)
            session.flush()

            _audit(
                session,
                admin=actor,
                action="mission_runtime_policy.upserted",
                policy=draft,
                metadata={
                    "missionId": draft.mission_id,
                    "version": draft.version,
                    "status": draft.status,
                },
                request=request,
            )

            return {"runtimePolicy": _serialize_policy(draft)}

        version = _next_version(session, mission_id)
        policy = MissionRuntimePolicy(
            id=_new_id("mission-runtime-policy"),
            version=version,
            status="draft",
            mission_id=mission_id,
            **policy_values,
        )
        session.add(policy)
        session.flush()

        _audit(
            session,
            admin=actor,
            action="mission_runtime_policy.upserted",
            policy=policy,
            metadata={
                "missionId": policy.mission_id,
                "version": policy.version,
                "status": policy.status,
            },
            request=request,
        )

        return {"runtimePolicy": _serialize_policy(policy)}