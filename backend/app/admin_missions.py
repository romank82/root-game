from __future__ import annotations

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
    ARObject,
    Chapter,
    GeoZone,
    Item,
    Mission,
    MinigameProfile,
    MissionReward,
    StoryNode,
    SystemSetting,
)
from app.slug_utils import _normalize_slug, _slugify_title, unique_slug
from app.system_settings_catalog import get_definition


router = APIRouter(prefix="/api/v1/admin/missions", tags=["admin-missions"])

MISSION_READ_PERMISSION = "missions.read"
MISSION_MANAGE_PERMISSION = "missions.manage"
VALID_MISSION_STATUSES = {"draft", "published"}
VALID_REWARD_TYPES = {"currency", "item", "story_node"}

# Sprint Trans-2b-2: ручной перевод контента миссии (Mission.translations).
# Источник истины по языкам — CMS-настройка content.supported_languages
# (Trans-2b-1); базовый язык ru — оригинал контента и не переводится.
SUPPORTED_LANGUAGES_SETTING_KEY = "content.supported_languages"
BASE_CONTENT_LANGUAGE = "ru"
TRANSLATION_STATUS_NONE = "none"
TRANSLATION_STATUS_PARTIAL = "partial"
TRANSLATION_STATUS_COMPLETE = "complete"
TRANSLATION_TITLE_MAX_LENGTH = 255
TRANSLATION_DESCRIPTION_MAX_LENGTH = 20_000
TRANSLATION_UI_TEXT_MAX_LENGTH = 20_000
TRANSLATION_UI_BLOCKS_MAX_ITEMS = 100
TRANSLATION_UI_BLOCK_MAX_LENGTH = 2_000
TRANSLATION_ALLOWED_FIELDS = frozenset({"title", "description", "contentUi"})
# Текстовые content.ui-ключи всех типов миссий по контракту
# app.content_contract.validate_mission_content (без технических:
# drumCount/alphabet/falseChoicesPerDrum/combination/timeLimitSeconds/
# maxBlocks/rewardPreview — они не переводятся).
TRANSLATABLE_UI_TEXT_KEYS = (
    "label",
    "question",
    "inputPlaceholder",
    "successTitle",
    "successText",
    "instruction",
    "wrongAnswerText",
    "lineNumber",
    "placeholder",
    "joinTitle",
    "joinText",
    "waitingText",
    "readyText",
    "activeText",
    "failureText",
)
TRANSLATABLE_UI_KEYS = frozenset(TRANSLATABLE_UI_TEXT_KEYS) | {"blocks"}
TRANSLATABLE_UI_KEY_ORDER = (*TRANSLATABLE_UI_TEXT_KEYS, "blocks")


def _validate_public_mission_content(
    mission_type: str, content: Any, *, require_full_cipher_ui: bool = True
) -> None:
    """Do not expose submitted content or protected values in validation errors."""
    try:
        validate_mission_content(
            mission_type,
            content,
            require_full_cipher_ui=require_full_cipher_ui,
        )
    except PublicContentValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Публичный content Mission не соответствует опубликованному контракту.",
        ) from exc


def _mission_has_published_profile(session: Session, mission: Mission) -> bool:
    """Sprint 8.17.16: есть ли у миссии published-профиль мини-игры.

    Зеркало gate из mission_engine._resolve_minigame_settings:
    published-профиль = источник настроек; draft/archived/None = legacy content.ui.
    """
    profile_id = getattr(mission, "minigame_profile_id", None)
    if not profile_id:
        return False
    profile = session.get(MinigameProfile, profile_id)
    return profile is not None and profile.status == "published"


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
    geo_zone_id: str | None = Field(default=None, max_length=64)
    ar_object_id: str | None = Field(default=None, max_length=64)
    minigame_profile_id: str | None = Field(default=None, max_length=64)
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    mission_type: str = Field(min_length=1, max_length=64)
    mission_category: str = Field(default="solo", min_length=1, max_length=32)
    mission_layer: str = Field(default="solo", min_length=1, max_length=32)
    execution_time_limit_seconds: int | None = Field(
        default=None,
        ge=0,
        le=7 * 24 * 3600,
    )
    reentry_cooldown_seconds: int = Field(
        default=0,
        ge=0,
        le=7 * 24 * 3600,
    )
    unlock_after_mission_id: str | None = Field(default=None, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    content: dict[str, Any] = Field(default_factory=dict)
    validation_config: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0, le=100_000)
    rewards: list[AdminMissionRewardPayload] = Field(default_factory=list)


class AdminMissionUpdatePayload(BaseModel):
    chapter_id: str | None = Field(default=None, min_length=1, max_length=64)
    story_node_id: str | None = Field(default=None, max_length=64)
    geo_zone_id: str | None = Field(default=None, max_length=64)
    ar_object_id: str | None = Field(default=None, max_length=64)
    minigame_profile_id: str | None = Field(default=None, max_length=64)
    slug: str | None = Field(default=None, min_length=3, max_length=128)
    mission_type: str | None = Field(default=None, min_length=1, max_length=64)
    mission_category: str | None = Field(default=None, max_length=32)
    mission_layer: str | None = Field(default=None, max_length=32)
    execution_time_limit_seconds: int | None = Field(
        default=None,
        ge=0,
        le=7 * 24 * 3600,
    )
    reentry_cooldown_seconds: int | None = Field(
        default=None,
        ge=0,
        le=7 * 24 * 3600,
    )
    unlock_after_mission_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20_000)
    content: dict[str, Any] | None = None
    validation_config: dict[str, Any] | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)
    rewards: list[AdminMissionRewardPayload] | None = None


class MissionTranslationsPayload(BaseModel):
    """Полная карта переводов контента: {language: {title, description, contentUi}}.

    PUT заменяет карту целиком. Пустые строки означают «нет перевода» и
    отбрасываются при нормализации (см. _normalize_translations_payload),
    чтобы translation_status не зависел от формата ввода.
    """

    translations: dict[str, dict[str, Any]] = Field(default_factory=dict)


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
        "geoZoneId": mission.geo_zone_id,
        "arObjectId": mission.ar_object_id,
        "minigameProfileId": mission.minigame_profile_id,
        "slug": mission.slug,
        "missionType": mission.mission_type,
        "missionCategory": mission.mission_category,
        "missionLayer": mission.mission_layer,
        "executionTimeLimitSeconds": mission.execution_time_limit_seconds,
        "reentryCooldownSeconds": mission.reentry_cooldown_seconds,
        "unlockAfterMissionId": mission.unlock_after_mission_id,
        "title": mission.title,
        "description": mission.description,
        "content": mission.content,
        "validationConfig": mission.validation_config,
        "translationStatus": (
            mission.translation_status or TRANSLATION_STATUS_NONE
        ),
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


def _validate_references(
    session: Session,
    *,
    chapter_id: str,
    story_node_id: str | None,
    geo_zone_id: str | None,
    ar_object_id: str | None,
) -> None:
    if session.get(Chapter, chapter_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Указанная глава (chapter_id) не существует.",
        )

    if story_node_id is not None:
        story_node = session.get(StoryNode, story_node_id)
        if story_node is None:
            raise HTTPException(
                status_code=422,
                detail="Указанный story_node_id не существует.",
            )
        if story_node.chapter_id != chapter_id:
            raise HTTPException(
                status_code=422,
                detail=(
                    "StoryNode должен принадлежать той же главе, "
                    "что и миссия."
                ),
            )

    if geo_zone_id is not None and session.get(GeoZone, geo_zone_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Указанная геозона (geo_zone_id) не существует.",
        )

    if ar_object_id is not None and session.get(ARObject, ar_object_id) is None:
        raise HTTPException(
            status_code=422,
            detail="Указанный AR-объект (ar_object_id) не существует.",
        )


def _validate_unlock_chain(
    session: Session,
    *,
    mission_id: str | None,
    unlock_after_mission_id: str | None,
    chapter_id: str,
) -> None:
    """Проверить, что unlock_after_mission_id не создаёт self-ref, cross-chapter или цикл."""
    if unlock_after_mission_id is None or unlock_after_mission_id == "":
        return

    # Self-reference
    if mission_id is not None and unlock_after_mission_id == mission_id:
        raise HTTPException(
            status_code=422,
            detail="Миссия не может разблокироваться после самой себя.",
        )

    # Существует?
    target = session.get(Mission, unlock_after_mission_id)
    if target is None:
        raise HTTPException(
            status_code=422,
            detail="Указанная миссия для разблокировки (unlock_after_mission_id) не существует.",
        )

    # Та же глава?
    if target.chapter_id != chapter_id:
        raise HTTPException(
            status_code=422,
            detail="Разблокирующая миссия должна быть в той же главе.",
        )

    # Цикл — пройти по цепочке вверх, до 20 шагов
    seen: set[str] = set()
    cursor: Mission | None = target
    steps = 0
    while cursor is not None and steps < 20:
        if cursor.id in seen:
            break
        seen.add(cursor.id)
        if mission_id is not None and cursor.id == mission_id:
            raise HTTPException(
                status_code=422,
                detail="Обнаружен цикл в цепочке разблокировки.",
            )
        if cursor.unlock_after_mission_id is None:
            break
        cursor = session.get(Mission, cursor.unlock_after_mission_id)
        steps += 1


def _validate_rewards(
    session: Session,
    *,
    chapter_id: str,
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

            story_node = session.get(StoryNode, reward.story_node_id)
            if story_node is None:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Награда story_node ссылается на несуществующий "
                        "story_node_id."
                    ),
                )

            if story_node.chapter_id != chapter_id:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "StoryNode награды должен принадлежать той же "
                        "главе, что и миссия."
                    ),
                )


def _read_supported_languages(session: Session) -> list[str]:
    """Языки контента из CMS (content.supported_languages) либо дефолт каталога.

    Порядок: строка system_settings -> default_value код-каталога -> базовый ru.
    Значения фильтруются: пустые и нестроковые элементы игнорируются, дубликаты
    схлопываются (валидация CMS уже запрещает и то, и другое — это защита от
    ручных правок в БД).
    """
    row = session.get(SystemSetting, SUPPORTED_LANGUAGES_SETTING_KEY)
    if row is not None and isinstance(row.value_json, list):
        languages = [
            item.strip()
            for item in row.value_json
            if isinstance(item, str) and item.strip()
        ]
        if languages:
            return list(dict.fromkeys(languages))

    definition = get_definition(SUPPORTED_LANGUAGES_SETTING_KEY)
    defaults = definition.default_value if definition is not None else None
    if isinstance(defaults, list):
        fallback = [
            item for item in defaults if isinstance(item, str) and item.strip()
        ]
        if fallback:
            return list(dict.fromkeys(fallback))

    return [BASE_CONTENT_LANGUAGE]


def _required_content_ui_keys(mission: Mission) -> tuple[str, ...]:
    """content.ui-ключи миссии, которые нужно повторить в каждом переводе."""
    content = mission.content if isinstance(mission.content, dict) else {}
    ui = content.get("ui") if isinstance(content, dict) else None
    if not isinstance(ui, dict):
        return ()
    return tuple(key for key in TRANSLATABLE_UI_KEY_ORDER if key in ui)


def _translation_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=detail,
    )


def _translation_text(value: Any, *, field: str, maximum: int) -> str:
    """Строковое поле перевода без внешних пробелов (пустая строка = нет перевода)."""
    if not isinstance(value, str):
        raise _translation_error(f"Поле перевода {field} должно быть строкой.")
    text = value.strip()
    if len(text) > maximum:
        raise _translation_error(
            f"Поле перевода {field} длиннее {maximum} символов."
        )
    return text


def _translation_blocks(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise _translation_error(
            f"Поле перевода {field} должно быть непустым массивом строк."
        )
    if len(value) > TRANSLATION_UI_BLOCKS_MAX_ITEMS:
        raise _translation_error(
            f"Поле перевода {field} содержит больше "
            f"{TRANSLATION_UI_BLOCKS_MAX_ITEMS} блоков."
        )
    blocks: list[str] = []
    for index, block in enumerate(value):
        if not isinstance(block, str) or not block.strip():
            raise _translation_error(
                f"Поле перевода {field}[{index}] должно быть непустой строкой."
            )
        if len(block.strip()) > TRANSLATION_UI_BLOCK_MAX_LENGTH:
            raise _translation_error(
                f"Поле перевода {field}[{index}] длиннее "
                f"{TRANSLATION_UI_BLOCK_MAX_LENGTH} символов."
            )
        blocks.append(block.strip())
    return blocks


def _normalize_translations_payload(
    translations: dict[str, dict[str, Any]],
    supported_languages: list[str],
) -> dict[str, dict[str, Any]]:
    """Проверить карту переводов и отбросить пустые значения.

    Язык обязан быть в CMS-списке; поля — только title/description/contentUi;
    contentUi — только переводимые ключи контракта content_contract
    (+ blocks для code_repair). Пустые строки в карту не попадают.
    """
    normalized: dict[str, dict[str, Any]] = {}

    for language, entry in translations.items():
        if language not in supported_languages:
            raise _translation_error(
                f"Язык '{language}' не поддерживается "
                f"({SUPPORTED_LANGUAGES_SETTING_KEY})."
            )
        if not isinstance(entry, dict):
            raise _translation_error(
                f"Перевод языка '{language}' должен быть объектом."
            )

        unknown_fields = sorted(set(entry) - TRANSLATION_ALLOWED_FIELDS)
        if unknown_fields:
            raise _translation_error(
                f"Неизвестные поля перевода для '{language}': "
                f"{', '.join(unknown_fields)}."
            )

        payload: dict[str, Any] = {}

        if "title" in entry:
            title = _translation_text(
                entry["title"],
                field=f"translations.{language}.title",
                maximum=TRANSLATION_TITLE_MAX_LENGTH,
            )
            if title:
                payload["title"] = title

        if "description" in entry:
            description = _translation_text(
                entry["description"],
                field=f"translations.{language}.description",
                maximum=TRANSLATION_DESCRIPTION_MAX_LENGTH,
            )
            if description:
                payload["description"] = description

        if "contentUi" in entry:
            ui = entry["contentUi"]
            if not isinstance(ui, dict):
                raise _translation_error(
                    f"Перевод translations.{language}.contentUi "
                    "должен быть объектом."
                )
            unknown_ui_keys = sorted(set(ui) - TRANSLATABLE_UI_KEYS)
            if unknown_ui_keys:
                raise _translation_error(
                    f"Неизвестные ключи contentUi для '{language}': "
                    f"{', '.join(unknown_ui_keys)}."
                )
            ui_payload: dict[str, Any] = {}
            for key, value in ui.items():
                field = f"translations.{language}.contentUi.{key}"
                if key == "blocks":
                    ui_payload["blocks"] = _translation_blocks(value, field=field)
                    continue
                text = _translation_text(
                    value,
                    field=field,
                    maximum=TRANSLATION_UI_TEXT_MAX_LENGTH,
                )
                if text:
                    ui_payload[key] = text
            if ui_payload:
                payload["contentUi"] = ui_payload

        if payload:
            normalized[language] = payload

    return normalized


def _compute_translation_status(
    translations: dict[str, dict[str, Any]],
    supported_languages: list[str],
    required_content_ui_keys: tuple[str, ...],
) -> str:
    """none / partial / complete по непустым переводам не-базовых языков.

    complete = каждый язык из CMS-списка, кроме базового ru, имеет title,
    description и все required_content_ui_keys (если content.ui миссии непустой).
    ru — оригинал контента (mission.title/description), перевод на него не нужен.
    """
    target_languages = [
        language
        for language in supported_languages
        if language != BASE_CONTENT_LANGUAGE
    ]
    if not target_languages:
        return TRANSLATION_STATUS_COMPLETE

    def _is_complete(language: str) -> bool:
        entry = translations.get(language)
        if not isinstance(entry, dict):
            return False
        if not entry.get("title") or not entry.get("description"):
            return False
        if not required_content_ui_keys:
            return True
        ui = entry.get("contentUi")
        if not isinstance(ui, dict):
            return False
        return all(key in ui for key in required_content_ui_keys)

    if all(_is_complete(language) for language in target_languages):
        return TRANSLATION_STATUS_COMPLETE
    if any(language in translations for language in target_languages):
        return TRANSLATION_STATUS_PARTIAL
    return TRANSLATION_STATUS_NONE


def _ensure_translations_complete(session: Session, mission: Mission) -> None:
    """Publish gate: миссия публикуется только с полным переводом контента."""
    if (
        mission.translation_status or TRANSLATION_STATUS_NONE
    ) == TRANSLATION_STATUS_COMPLETE:
        return

    supported_languages = _read_supported_languages(session)
    target_languages = [
        language
        for language in supported_languages
        if language != BASE_CONTENT_LANGUAGE
    ]
    suffix = f" ({', '.join(target_languages)})" if target_languages else ""
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=(
            f"Перевод не завершён. Заполните переводы для всех языков{suffix} "
            "перед публикацией."
        ),
    )


def _validate_for_publish(
    session: Session,
    mission: Mission,
    *,
    require_complete_translations: bool = False,
) -> None:
    """Reject publishing a mission that the current game engine cannot validate.

    require_complete_translations=True используется точкой публикации
    (POST /{mission_id}/publish): без полного перевода миссия не публикуется.
    По умолчанию False, чтобы точечные тесты контент-контракта
    (_validate_for_publish в test_admin_content_validation и
    test_minigame_profile_cipher_publish) оставались про контент, а не про
    переводы.
    """
    if require_complete_translations:
        _ensure_translations_complete(session, mission)

    # Sprint 8.17.16: для cipher-миссий с published-профилем старые поля
    # content.ui (drumCount/alphabet/combination) не обязательны — настройки
    # мини-игры берутся из profile.settings (см. _resolve_minigame_settings).
    has_published_profile = _mission_has_published_profile(session, mission)
    _validate_public_mission_content(
        mission.mission_type,
        mission.content,
        require_full_cipher_ui=not has_published_profile,
    )
    _validate_references(
        session,
        chapter_id=mission.chapter_id,
        story_node_id=mission.story_node_id,
        geo_zone_id=mission.geo_zone_id,
        ar_object_id=mission.ar_object_id,
    )

    if mission.geo_zone_id is None:
        raise HTTPException(
            status_code=422,
            detail="Для публикации миссии обязательна привязка геозоны (geo_zone_id).",
        )
    if mission.ar_object_id is None:
        raise HTTPException(
            status_code=422,
            detail="Для публикации миссии обязательна привязка AR-объекта (ar_object_id).",
        )

    # Sprint 8.17.19 + Memory-2c: для cipher- и memory-миссии профиль мини-игры
    # обязателен. Legacy-published без профиля не ломаем задним числом, но любая
    # новая публикация / редактирование content или validation_config требует
    # профиль (см. docs/roadmap-detailed.md, расхождение №2).
    if (
        mission.mission_type in ("cipher", "memory")
        and not mission.minigame_profile_id
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Для {mission.mission_type}-миссии обязателен профиль мини-игры. "
                "Выберите профиль в форме миссии перед публикацией."
            ),
        )

    if mission.mission_layer not in ("story", "team", "solo"):
        raise HTTPException(
            status_code=422,
            detail="mission_layer должен быть одним из: story, team, solo.",
        )

    # Согласованность: слой team ↔ mission_type team.
    if mission.mission_layer == "team" and mission.mission_type != "team":
        raise HTTPException(
            status_code=422,
            detail="Слой team требует mission_type=team.",
        )
    if mission.mission_layer != "team" and mission.mission_type == "team":
        raise HTTPException(
            status_code=422,
            detail="mission_type=team требует mission_layer=team.",
        )

    if mission.mission_type == "team":
        _validate_team_mission_config(mission.validation_config)
    else:
        validator = mission.validation_config.get("validator")

        # Проверка совместимости mission_type ↔ validator.
        # См. Sprint 8.13 (fix): без этой проверки можно опубликовать
        # cipher с normalized_text_match, и миссия станет нерешаемой.
        expected_validator_by_type = {
            "text_answer": "normalized_text_match",
            "code_repair": "ordered_blocks_match",
            "cipher": "cipher_match",
            # Sprint Memory-2c: memory проверяется сервером по сессии
            # (progress.memory_session), validator фиксирован.
            "memory": "memory_match",
        }
        expected_validator = expected_validator_by_type.get(mission.mission_type)
        if expected_validator is not None and validator != expected_validator:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Миссия типа {mission.mission_type} требует validator="
                    f"{expected_validator}, получено: {validator or 'не задан'}."
                ),
            )

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

        elif validator == "cipher_match":
            correct_combination = mission.validation_config.get("correctCombination")

            # Sprint 8.17.18-hotfix: для published-профиля correctCombination
            # не требуется — правильный код генерируется на backend, и форма
            # его больше не отправляет (8.17.18). Для legacy-миссий без
            # профиля проверка остаётся обязательной, как раньше.
            if not has_published_profile:
                if (
                    not isinstance(correct_combination, list)
                    or not correct_combination
                    or not all(
                        isinstance(symbol, str) and symbol.strip()
                        for symbol in correct_combination
                    )
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Для validator=cipher_match требуется непустой "
                            "список validation_config.correctCombination."
                        ),
                    )

                # Sprint 8.17.16: согласованность correctCombination c legacy
                # content.ui (drumCount/alphabet) проверяем только для миссий без
                # published-профиля. Для профильных настройки живут в
                # profile.settings, а content.ui может быть пустым.
                ui = mission.content.get("ui", {}) if isinstance(mission.content, dict) else {}
                drum_count = ui.get("drumCount")
                alphabet = ui.get("alphabet")

                if len(correct_combination) != drum_count:
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "Для validator=cipher_match длина correctCombination "
                            "должна совпадать с content.ui.drumCount."
                        ),
                    )

                if isinstance(alphabet, list):
                    alphabet_set = set(alphabet)
                    for symbol in correct_combination:
                        if symbol not in alphabet_set:
                            raise HTTPException(
                                status_code=422,
                                detail=(
                                    "Для validator=cipher_match все символы correctCombination "
                                    "должны присутствовать в content.ui.alphabet."
                                ),
                            )

        elif validator == "memory_match":
            # Sprint Memory-Validation-Fix-2: memory валидируется по серверной
            # сессии (progress.memory_session) при проверке ответа;
            # validation_config не требуется — no-op.
            pass

        else:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Миссию нельзя опубликовать: validation_config.validator "
                    "должен быть normalized_text_match, ordered_blocks_match, "
                    "cipher_match или memory_match."
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
    _validate_rewards(
        session,
        chapter_id=mission.chapter_id,
        rewards=reward_payloads,
    )


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
    chapter_id: str | None = None,
    _admin: AdminUser = Depends(require_permission(MISSION_READ_PERMISSION)),
):
    with SessionLocal.begin() as session:
        # Sprint 8.23 (Этап 1, часть 2b): опциональный фильтр chapter_id —
        # только миссии этой главы. Без параметра поведение не меняется
        # (обратная совместимость). Несуществующая глава -> 404; валидатор
        # _validate_references отдаёт 422 и используется create/update, поэтому
        # здесь проверка через сессию с литералом 404 (без затенения
        # fastapi.status параметром функции).
        if chapter_id is not None and session.get(Chapter, chapter_id) is None:
            raise HTTPException(
                status_code=404,
                detail="Глава не найдена.",
            )

        query = select(Mission).order_by(Mission.status, Mission.sort_order, Mission.id)
        if chapter_id is not None:
            query = query.where(Mission.chapter_id == chapter_id)

        missions = session.scalars(query).all()

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
        title = payload.title.strip()
        slug = (
            _normalize_slug(payload.slug)
            if payload.slug is not None
            else _slugify_title(title)
        )

        if payload.slug is None:
            slug = unique_slug(
                slug,
                lambda s: session.scalar(
                    select(Mission.id).where(Mission.slug == s)
                ) is not None,
            )
        elif session.scalar(select(Mission.id).where(Mission.slug == slug)):
            raise HTTPException(
                status_code=409,
                detail="Миссия с таким slug уже существует.",
            )

        _validate_references(
            session,
            chapter_id=payload.chapter_id,
            story_node_id=payload.story_node_id,
            geo_zone_id=payload.geo_zone_id,
            ar_object_id=payload.ar_object_id,
        )
        if (
            payload.minigame_profile_id is not None
            and session.get(MinigameProfile, payload.minigame_profile_id) is None
        ):
            raise HTTPException(
                status_code=422,
                detail="Указанный профиль мини-игры (minigame_profile_id) не существует.",
            )
        _validate_unlock_chain(
            session,
            mission_id=None,
            unlock_after_mission_id=payload.unlock_after_mission_id,
            chapter_id=payload.chapter_id,
        )
        _validate_rewards(
            session,
            chapter_id=payload.chapter_id,
            rewards=payload.rewards,
        )
        _validate_mission_category(payload.mission_category)

        mission = Mission(
            id=_new_id("mission"),
            chapter_id=payload.chapter_id,
            story_node_id=payload.story_node_id,
            geo_zone_id=payload.geo_zone_id,
            ar_object_id=payload.ar_object_id,
            minigame_profile_id=payload.minigame_profile_id,
            slug=slug,
            mission_type=payload.mission_type.strip(),
            mission_category=payload.mission_category,
            mission_layer=payload.mission_layer,
            execution_time_limit_seconds=(
                payload.execution_time_limit_seconds
                if payload.execution_time_limit_seconds
                and payload.execution_time_limit_seconds > 0
                else None
            ),
            reentry_cooldown_seconds=payload.reentry_cooldown_seconds,
            unlock_after_mission_id=payload.unlock_after_mission_id or None,
            title=title,
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

        if "slug" in updates and updates["slug"] is not None:
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

        if "geo_zone_id" in updates:
            mission.geo_zone_id = updates["geo_zone_id"]
            changed_fields.append("geoZoneId")

        if "ar_object_id" in updates:
            mission.ar_object_id = updates["ar_object_id"]
            changed_fields.append("arObjectId")

        if "minigame_profile_id" in updates:
            minigame_profile_id = updates["minigame_profile_id"]
            if minigame_profile_id is not None and session.get(
                MinigameProfile, minigame_profile_id
            ) is None:
                raise HTTPException(
                    status_code=422,
                    detail="Указанный профиль мини-игры (minigame_profile_id) не существует.",
                )
            mission.minigame_profile_id = minigame_profile_id
            changed_fields.append("minigameProfileId")

        _validate_references(
            session,
            chapter_id=mission.chapter_id,
            story_node_id=mission.story_node_id,
            geo_zone_id=mission.geo_zone_id,
            ar_object_id=mission.ar_object_id,
        )

        if "mission_category" in updates:
            category_value = updates["mission_category"]
            if category_value is not None:
                _validate_mission_category(category_value)
                mission.mission_category = category_value
                changed_fields.append("missionCategory")

        if "mission_layer" in updates:
            mission.mission_layer = updates["mission_layer"]
            changed_fields.append("missionLayer")

        if "execution_time_limit_seconds" in updates:
            raw = updates["execution_time_limit_seconds"]
            mission.execution_time_limit_seconds = (
                raw if raw and raw > 0 else None
            )
            changed_fields.append("executionTimeLimitSeconds")

        if "reentry_cooldown_seconds" in updates:
            raw = updates["reentry_cooldown_seconds"]
            mission.reentry_cooldown_seconds = raw if raw is not None and raw >= 0 else 0
            changed_fields.append("reentryCooldownSeconds")

        if "unlock_after_mission_id" in updates:
            raw = updates["unlock_after_mission_id"]
            mission.unlock_after_mission_id = raw if raw else None
            changed_fields.append("unlockAfterMissionId")

        _validate_unlock_chain(
            session,
            mission_id=mission.id,
            unlock_after_mission_id=mission.unlock_after_mission_id,
            chapter_id=mission.chapter_id,
        )

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
            _validate_rewards(
                session,
                chapter_id=mission.chapter_id,
                rewards=payload.rewards or [],
            )
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

        _validate_for_publish(
            session,
            mission,
            require_complete_translations=True,
        )
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


@router.get("/{mission_id}/translations")
def get_mission_translations(
    mission_id: str,
    _admin: AdminUser = Depends(require_permission(MISSION_READ_PERMISSION)),
):
    """Карта переводов контента миссии и вычисленный translation_status.

    Sprint Trans-2b-2. Языки берутся из CMS (content.supported_languages),
    поэтому новый язык появляется в контракте без деплоя.
    """
    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        supported_languages = _read_supported_languages(session)

        return {
            "missionId": mission.id,
            "translations": mission.translations or {},
            "translationStatus": (
                mission.translation_status or TRANSLATION_STATUS_NONE
            ),
            "supportedLanguages": supported_languages,
            # Подсказка админке: какие content.ui-ключи миссии нужно повторить,
            # чтобы перевод считался complete.
            "requiredContentUiKeys": list(_required_content_ui_keys(mission)),
        }


@router.put("/{mission_id}/translations")
def put_mission_translations(
    mission_id: str,
    payload: MissionTranslationsPayload,
    request: Request,
    admin: AdminUser = Depends(require_permission(MISSION_MANAGE_PERMISSION)),
):
    """Полная замена карты переводов миссии (Sprint Trans-2b-2).

    Валидирует языки по CMS (content.supported_languages, ru обязателен как
    оригинал), поля title/description/contentUi по контракту content_contract,
    пересчитывает translation_status на сервере и пишет immutable audit.
    Текст перевода в audit не попадает — только языки, статус и required-ключи.
    """
    with SessionLocal.begin() as session:
        mission = session.get(Mission, mission_id)
        if mission is None:
            raise HTTPException(status_code=404, detail="Миссия не найдена.")

        supported_languages = _read_supported_languages(session)
        if BASE_CONTENT_LANGUAGE not in supported_languages:
            raise _translation_error(
                "Базовый язык ru обязателен в "
                f"{SUPPORTED_LANGUAGES_SETTING_KEY}: он не переводится, "
                "а служит оригиналом контента миссии."
            )

        translations = _normalize_translations_payload(
            payload.translations or {},
            supported_languages,
        )
        required_content_ui_keys = _required_content_ui_keys(mission)
        translation_status = _compute_translation_status(
            translations,
            supported_languages,
            required_content_ui_keys,
        )

        mission.translations = translations
        mission.translation_status = translation_status
        session.flush()

        _audit(
            session,
            admin=admin,
            action="mission.translations_updated",
            mission_id=mission.id,
            metadata={
                "languages": sorted(translations),
                "translationStatus": translation_status,
                "requiredContentUiKeys": list(required_content_ui_keys),
            },
            request=request,
        )

        return {
            "missionId": mission.id,
            "translations": mission.translations,
            "translationStatus": mission.translation_status,
            "supportedLanguages": supported_languages,
            "requiredContentUiKeys": list(required_content_ui_keys),
        }
