from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_access import require_permission
from app.admin_audit import write_admin_audit
from app.content_contract import PublicContentValidationError, validate_mission_content
from app.db import SessionLocal
from app.geo_team_contract import (
    GeoTeamConfigurationError,
    validate_team_mission_validation_config,
)
from app.mission_categories import is_valid_category
from app.models import (
    AdminAuditLog,
    AdminUser,
    Chapter,
    Item,
    Mission,
    MissionReward,
    StoryNode,
)


router = APIRouter(prefix="/api/v1/admin/missions", tags=["admin-missions"])

MISSION_READ_PERMISSION = "missions.read"
MISSION_MANAGE_PERMISSION = "missions.manage"
VALID_MISSION_STATUSES = {"draft", "published"}
VALID_REWARD_TYPES = {"currency", "item", "story_node"}
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[a-z0-9-]{0,126}[a-z0-9])?$")


def _validate_public_mission_content(mission_type: str, content: Any) -> None:
    """Do not expose submitted content or protected values in validation errors."""
    try:
        validate_mission_content(mission_type, content)
    except PublicContentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Публичный content Mission не соответствует опубликованному контракту.",
        ) from exc


def _validate_team_mission_config(validation_config: Any) -> None:
    """Validate protected team CMS data without echoing it in an API error."""
    try:
        validate_team_mission_validation_config(validation_config)
    except GeoTeamConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Защищённая конфигурация team Mission не соответствует контракту.",
        ) from exc


def _validate_mission_category(value: str) -> None:
    """Reject an unknown participation category before it reaches the model."""
    if not is_valid_category(value):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Неизвестная категория миссии.",
        )


class AdminMissionRewardPayload(BaseModel):
    reward_type: str = Field(min_length=1, max_length=64)
    amount: int | None = Field(default=None, ge=1, le=1_000_000)
    item_id: str | None = Field(default=None, max_length=64)
    story_node_id: str | None = Field(default=None, max_length=64)
    reward_value: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=100_000)


class AdminMissionCreatePayload(BaseModel):
    chapter_id: str = Field(min_length=1, max_length=64)
    story_node_id: str | None = Field(default=None, max_length=64)
    slug: str = Field(min_length=3, max_length=128)
    mission_type: str = Field(min_length=1, max_length=64)
    mission_category: str = Field(default="solo", min_length=1, max_length=32)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    content: dict[str, Any] = Field(default_factory=dict)
    validation_config: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    rewards: list[AdminMissionRewardPayload] = Field(default_factory=list)


class AdminMissionUpdatePayload(BaseModel):
    chapter_id: str | None = Field(default=None, min_length=1, max_length=64)
    story_node_id: str | None = Field(default=None, max_length=64)
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    mission_type: str | None = Field(default=None, min_length=1, max_length=64)
    mission_category: str | None = Field(default=None, max_length=32)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    content: dict[str, Any] | None = None
    validation_config: dict[str, Any] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    rewards: list[AdminMissionRewardPayload] | None = None


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _client_ip_address(request: Request) -> str | None:
    """Use the direct peer address; do not trust arbitrary forwarded headers."""
    return request.client.host if request.client else None


def _serialize_reward(reward: MissionReward) -> dict[str, Any]:
    return {
        "id": reward.id,
        "rewardType": reward.reward_type,
        "amount": reward.amount,
        "itemId": reward.item_id,
        "storyNodeId": reward.story_node_id,
        "rewardValue": reward.reward_value,
        "sortOrder": reward.sort_order,
    }


def _serialize_mission(
    session: Session,
    mission: Mission,
) -> dict[str, Any]:
    rewards = session.scalars(
        select(MissionReward)
        .where(MissionReward.mission_id == mission.id)
        .order_by(MissionReward.sort_order, MissionReward.id)
    ).all()

    return {
        "id": mission.id,
        "chapterId": mission.chapter_id,
        "storyNodeId": mission.story_node_id,
        "slug": mission.slug,
        "missionType": mission.mission_type,
        "missionCategory": mission.mission_category,
        "title": mission.title,
        "description": mission.description,
        "content": mission.content,
        "validationConfig": mission.validation_config,
        "status": mission.status,
        "sortOrder": mission.sort_order,
        "rewards": [_serialize_reward(reward) for reward in rewards],
        "createdAt": mission.created_at.isoformat() if mission.created_at else None,
        "updatedAt": mission.updated_at.isoformat() if mission.updated_at else None,
    }


def _audit(
    session: Session,
    *,
    admin: AdminUser,
    action: str,
    mission_id: str,
    metadata: dict[str, Any],
    request: Request,
) -> None:
    """
    validation_config is deliberately excluded from metadata:
    it may contain correct answers or other secret validation material.
    """
    write_admin_audit(
        session,
        actor=admin,
        action=action,
        entity_type="mission",
        entity_id=mission_id,
        request=request,
        metadata=metadata,
    )


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()

    if not SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(
            status_code=422,
            detail=(
                "slug должен содержать строчные латинские буквы, цифры "
                "и дефисы; длина — от 3 до 128 символов."
            ),
        )

    return slug


def _validate_references(
    session: Session,
    *,
    chapter_id: str,
    story_node_id: str | None,
) -> None:
    if session.get(Chapter, chapter_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Указанная глава (chapter_id) не существует.",
        )

    if story_node_id is not None and session.get(StoryNode, story_node_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Указанный story_node_id не существует.",
        )


def _validate_rewards(
    session: Session,
    rewards: list[AdminMissionRewardPayload],
) -> None:
    for reward in rewards:
        if reward.reward_type not in VALID_REWARD_TYPES:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Недопустимый reward_type. Разрешены: "
                    "currency, item, story_node."
                ),
            )

        if reward.reward_type == "currency":
            if reward.amount is None or reward.amount <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="Награда currency должна иметь положительный amount.",
                )

            if reward.reward_value.get("currency") != "ROOT":
                raise HTTPException(
                    status_code=422,
                    detail='Для currency reward_value должен содержать {"currency":"ROOT"}.',
                )

        elif reward.reward_type == "item":
            if not reward.item_id:
                raise HTTPException(
                    status_code=422,
                    detail="Награда item должна содержать item_id.",
                )

            if session.get(Item, reward.item_id) is None:
                raise HTTPException(
                    status_code=422,
                    detail="Награда item ссылается на несуществующий item_id.",
                )

        elif reward.reward_type == "story_node":
            if not reward.story_node_id:
                raise HTTPException(
                    status_code=422,
                    detail="Награда story_node должна содержать story_node_id.",
                )

            if session.get(StoryNode, reward.story_node_id) is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Награда story_node ссылается на несуществующий "
                        "story_node_id."
                    ),
                )


def _validate_for_publish(
    session: Session,
    mission: Mission,
) -> None:
    """Reject publishing a mission that the current game engine cannot validate."""
    _validate_public_mission_content(mission.mission_type, mission.content)
    _validate_references(
        session,
        chapter_id=mission.chapter_id,
        story_node_id=mission.story_node_id,
    )

    if mission.mission_type == "team":
        _validate_team_mission_config(mission.validation_config)
    else:
        validator = mission.validation_config.get("validator")

        if validator == "normalized_text_match":
            accepted_answers = mission.validation_config.get("acceptedAnswers")
            if (
                not isinstance(accepted_answers, list)
                or not accepted_answers
                or not all(
                    isinstance(answer, str) and answer.strip()
                    for answer in accepted_answers
                )
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Для validator=normalized_text_match требуется непустой "
                        "список validation_config.acceptedAnswers."
                    ),
                )

        elif validator == "ordered_blocks_match":
            correct_sequence = mission.validation_config.get("correctSequence")
            if (
                not isinstance(correct_sequence, list)
                or not correct_sequence
                or not all(
                    isinstance(block, str) and block.strip()
                    for block in correct_sequence
                )
            ):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Для validator=ordered_blocks_match требуется непустой "
                        "список validation_config.correctSequence."
                    ),
                )

        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Миссию нельзя опубликовать: validation_config.validator "
                    "должен быть normalized_text_match или ordered_blocks_match."
                ),
            )

    rewards = session.scalars(
        select(MissionReward).where(MissionReward.mission_id == mission.id)
    ).all()

    reward_payloads = [
        AdminMissionRewardPayload(
            reward_type=reward.reward_type,
            amount=reward.amount,
            item_id=reward.item_id,
            story_node_id=reward.story_node_id,
            reward_value=reward.reward_value,
            sort_order=reward.sort_order,
        )
        for reward in rewards
    ]
    _validate_rewards(session, reward_payloads)


def _replace_rewards(
    session: Session,
    *,
    mission_id: str,
    rewards: list[AdminMissionRewardPayload],
) -> None:
    old_rewards = session.scalars(
        select(MissionReward).where(MissionReward.mission_id == mission_id)
    ).all()

    for old_reward in old_rewards:
        session.delete(old_reward)

    session.flush()

    for reward in rewards:
        session.add(
            MissionReward(
                id=_new_id("mission-reward"),
                mission_id=mission_id,
                reward_type=reward.reward_type,
                amount=reward.amount,
                item_id=reward.item_id,
                story_node_id=reward.story_node_id,
                reward_value=reward.reward_value,
                sort_order=reward.sort_order,
            )
        )


@router.get("")
def list_admin_missions(
    _admin: AdminUser = Depends(require_permission(MISSION_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        missions = session.scalars(
            select(Mission).order_by(Mission.status, Mission.sort_order, Mission.id)
        ).all()

        return {
            "missions": [
                _serialize_mission(session, mission)
                for mission in missions
            ]
        }


@router.get("/{mission_id}")
def get_admin_mission(
    mission_id: str,
    _admin: AdminUser = Depends(require_permission(MISSION_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)

        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        return {"mission": _serialize_mission(session, mission)}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_admin_mission(
    payload: AdminMissionCreatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(MISSION_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        slug = _normalize_slug(payload.slug)

        if session.scalar(select(Mission.id).where(Mission.slug == slug)):
            raise HTTPException(
                status_code=409,
                detail="Миссия с таким slug уже существует.",
            )

        _validate_references(
            session,
            chapter_id=payload.chapter_id,
            story_node_id=payload.story_node_id,
        )
        _validate_rewards(session, payload.rewards)
        _validate_mission_category(payload.mission_category)

        mission = Mission(
            id=_new_id("mission"),
            chapter_id=payload.chapter_id,
            story_node_id=payload.story_node_id,
            slug=slug,
            mission_type=payload.mission_type.strip(),
            mission_category=payload.mission_category,
            title=payload.title.strip(),
            description=payload.description.strip() if payload.description else None,
            content=payload.content,
            validation_config=payload.validation_config,
            status="draft",
            sort_order=payload.sort_order,
        )
        session.add(mission)
        session.flush()

        _replace_rewards(
            session,
            mission_id=mission.id,
            rewards=payload.rewards,
        )
        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission.created",
            mission_id=mission.id,
            metadata={
                "slug": mission.slug,
                "status": mission.status,
                "rewardCount": len(payload.rewards),
            },
            request=request,
        )

        return {"mission": _serialize_mission(session, mission)}


@router.patch("/{mission_id}")
def update_admin_mission(
    mission_id: str,
    payload: AdminMissionUpdatePayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(MISSION_MANAGE_PERMISSION)),
):
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)

        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        changed_fields: list[str] = []

        if "slug" in updates:
            slug = _normalize_slug(updates["slug"])
            existing_id = session.scalar(
                select(Mission.id).where(
                    Mission.slug == slug,
                    Mission.id != mission.id,
                )
            )
            if existing_id is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Миссия с таким slug уже существует.",
                )
            mission.slug = slug
            changed_fields.append("slug")

        if "chapter_id" in updates:
            mission.chapter_id = updates["chapter_id"]
            changed_fields.append("chapterId")

        if "story_node_id" in updates:
            mission.story_node_id = updates["story_node_id"]
            changed_fields.append("storyNodeId")

        _validate_references(
            session,
            chapter_id=mission.chapter_id,
            story_node_id=mission.story_node_id,
        )

        if "mission_category" in updates:
            category_value = updates["mission_category"]
            if category_value is not None:
                _validate_mission_category(category_value)
                mission.mission_category = category_value
                changed_fields.append("missionCategory")

        scalar_fields = {
            "mission_type": "missionType",
            "title": "title",
            "description": "description",
            "content": "content",
            "validation_config": "validationConfig",
            "sort_order": "sortOrder",
        }

        for field_name, audit_name in scalar_fields.items():
            if field_name not in updates:
                continue

            value = updates[field_name]

            if field_name in {"mission_type", "title"}:
                value = value.strip()

            if field_name == "description" and value is not None:
                value = value.strip() or None

            setattr(mission, field_name, value)
            changed_fields.append(audit_name)

        if "rewards" in updates:
            _validate_rewards(session, payload.rewards or [])
            _replace_rewards(
                session,
                mission_id=mission.id,
                rewards=payload.rewards or [],
            )
            changed_fields.append("rewards")

        if (
            mission.status == "published"
            and {"content", "mission_type", "validation_config"} & set(updates)
        ):
            _validate_for_publish(session, mission)

        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission.updated",
            mission_id=mission.id,
            metadata={
                "changedFields": changed_fields,
                # Never store validation_config itself; it may contain answers.
                "validationConfigChanged": "validation_config" in updates,
                "rewardCount": (
                    len(payload.rewards)
                    if "rewards" in updates and payload.rewards is not None
                    else None
                ),
            },
            request=request,
        )

        return {"mission": _serialize_mission(session, mission)}


@router.post("/{mission_id}/publish")
def publish_admin_mission(
    mission_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(MISSION_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)

        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        if mission.status == "published":
            return {"mission": _serialize_mission(session, mission)}

        _validate_for_publish(session, mission)
        mission.status = "published"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission.published",
            mission_id=mission.id,
            metadata={"slug": mission.slug, "previousStatus": "draft"},
            request=request,
        )

        return {"mission": _serialize_mission(session, mission)}


@router.post("/{mission_id}/unpublish")
def unpublish_admin_mission(
    mission_id: str,
    request: Request,
    admin: AdminUser = Depends(require_permission(MISSION_MANAGE_PERMISSION)),
):
    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)

        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        if mission.status == "draft":
            return {"mission": _serialize_mission(session, mission)}

        previous_status = mission.status
        mission.status = "draft"
        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission.unpublished",
            mission_id=mission.id,
            metadata={
                "slug": mission.slug,
                "previousStatus": previous_status,
            },
            request=request,
        )

        return {"mission": _serialize_mission(session, mission)}
