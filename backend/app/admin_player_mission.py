"""Админ-операции игровых миссий игрока: ручная отмена (5.6.a)
и принудительное завершение (5.6.b).

- POST /api/v1/admin/players/{player_id}/missions/{mission_id}/mission-cancel
  Прямое исполнение при direct-grant; при approval-grant создаёт
  AdminApprovalRequest (action_type player.mission_cancel) и отвечает 201.
- POST /api/v1/admin/players/{player_id}/missions/{mission_id}/mission-force-complete
  Завершение из available/in_progress/locked с опциональной выдачей наград
  (awardRewards; ROOT — ledger-idempotent). Порог-магнитуда — суммарные
  ROOT-награды миссии >= economy.mission_force_complete_approval_threshold
  (super-admin исполняет напрямую, заявка не создаётся).
- POST /api/v1/admin/players/mission-cancel-requests/{approval_id}/execute
  Dedicated executor для супер-админа (только player.mission_cancel).

Статус "cancelled" — новый терминальный статус PlayerMission:
CheckConstraint на status у PlayerMission нет -> миграция не нужна.
Отмена НЕ возвращает вложенные ресурсы (ROOT/предметы/ключи):
компенсация — отдельными ручными операциями 5.4/5.5. Fallback-entitlement
независим от статуса миссии и отключается только при явном
invalidate_fallback_entitlement=true (available -> disabled).

Идемпотентность по request_id: у PlayerMission нет reference_id, как у
WalletTransaction, поэтому признаком «данный request_id уже применили к этой
миссии» служит immutable admin_audit_log (entity_type=player_mission,
entity_id=player_mission.id, request_id, outcome=success). Повтор того же
request_id на уже отменённой миссии -> 200 idempotent; отмена отменённой
миссии другим request_id -> 409.

Тот же идемпотентный механизм для force-complete (5.6.b): признаком
«request_id уже применили» служит запись в immutable admin_audit_log
(action player.mission_force_complete[.via_approval]). Replay отдаёт
исторические awardedRoot/awardedItems/awardedStoryNodeIds/rewardSkipped/
entryConsumed из metadata_json audit-записи.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.admin_access import (
    APPROVAL_EXECUTION_MODE,
    get_admin_user,
    get_permission_execution_mode,
    require_super_admin,
)
from app.admin_approvals import (
    APPROVED,
    EXECUTED,
    EXECUTION_FAILED,
    PENDING,
    _serialize as _serialize_approval,
)
from app.admin_audit import (
    build_admin_approval_audit_snapshot,
    sanitize_audit_data,
    write_admin_audit,
)
from app.datetime_utils import ensure_utc
from app.db import SessionLocal
from app.mission_engine import ROOT_CURRENCY, _award_mission_rewards
from app.models import (
    AdminApprovalRequest,
    AdminAuditLog,
    AdminUser,
    GamePlayer,
    Mission,
    MissionReward,
    PlayerFallbackEntitlement,
    PlayerMission,
    SystemSetting,
)
from app.system_settings_catalog import get_definition

router = APIRouter(prefix="/api/v1/admin/players", tags=["admin-player-missions"])

# --- Доменные константы -----------------------------------------------------
PLAYERS_MANAGE_PERMISSION = "players.manage"
ACTION_TYPE_CANCEL = "player.mission_cancel"
CANCELLED_STATUS = "cancelled"
# Терминальные статусы PlayerMission: повторный cancel запрещён.
TERMINAL_STATUSES = frozenset({"completed", "cancelled"})
ENTITLEMENT_ACTIVE_STATUS = "available"
ENTITLEMENT_DISABLED_STATUS = "disabled"
# --- 5.6.b: mission-force-complete ---------------------------------
ACTION_TYPE_FORCE_COMPLETE = "player.mission_force_complete"
FORCE_COMPLETE_THRESHOLD_KEY = "economy.mission_force_complete_approval_threshold"
DEFAULT_FORCE_COMPLETE_THRESHOLD = 5000
COMPLETED_STATUS = "completed"
ACTIVE_SETTING_STATUS = "active"
# --- 5.6.c: mission attempts adjustment ------------------------------
ACTION_TYPE_ATTEMPTS_ADJUST = "player.mission_attempts_adjust"
ATTEMPTS_MIN = 0
ATTEMPTS_MAX = 1000


class MissionCancelError(Exception):
    """Доменная ошибка mission-cancel с machine-readable code."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class MissionCancelPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=4_000)
    # Идемпотентный ключ операции. Повтор того же request_id на уже
    # отменённой миссии -> 200 idempotent (см. docstring выше).
    request_id: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None
    invalidate_fallback_entitlement: bool = False


class MissionForceCompletePayload(BaseModel):
    reason: str = Field(min_length=1, max_length=4_000)
    # Идемпотентный ключ операции. Повтор того же request_id на уже
    # завершённой миссии -> 200 idempotent (см. docstring выше).
    request_id: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None
    # Выдавать ли награды миссии при принудительном завершении. ROOT-выдача
    # идемпотентна на уровне ledger (wallet_id + mission_reward + mission.id).
    award_rewards: bool = True


class MissionAttemptsAdjustPayload(BaseModel):
    """Абсолютная ручная корректировка attempt_count (5.6.c).

    Устанавливает исторический счётчик попыток в new_attempt_count
    ([ATTEMPTS_MIN, ATTEMPTS_MAX]); это не дельта. request_id —
    идемпотентный ключ: повтор на обработанной миссии -> 200 idempotent.
    """

    new_attempt_count: int = Field(ge=ATTEMPTS_MIN, le=ATTEMPTS_MAX)
    reason: str = Field(min_length=1, max_length=4_000)
    request_id: str = Field(min_length=1, max_length=64)
    expires_at: datetime | None = None


# --- Вспомогательные хелперы -------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:24]}"


def _client_ip_address(request: Request) -> str | None:
    return request.client.host if request.client is not None else None


def _normalize_required(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} не может состоять только из пробелов.",
        )
    return normalized


def _validate_expiry(expires_at: datetime) -> datetime:
    if expires_at.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiresAt должен содержать timezone.",
        )
    if expires_at <= _now():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="expiresAt должен быть в будущем.",
        )
    return expires_at


def _find_player_mission(session: Any, player_id: str, mission_id: str) -> PlayerMission | None:
    return session.scalar(
        select(PlayerMission)
        .where(
            PlayerMission.player_id == player_id,
            PlayerMission.mission_id == mission_id,
        )
        .with_for_update()
    )


def _find_cancel_audit(session: Any, player_mission_id: str, request_id: str) -> AdminAuditLog | None:
    """Успешная отмена этой миссии с этим request_id уже записана в audit."""
    return session.scalar(
        select(AdminAuditLog).where(
            AdminAuditLog.entity_type == "player_mission",
            AdminAuditLog.entity_id == player_mission_id,
            AdminAuditLog.request_id == request_id,
            AdminAuditLog.outcome == "success",
            AdminAuditLog.action.in_(
                (ACTION_TYPE_CANCEL, f"{ACTION_TYPE_CANCEL}.via_approval")
            ),
        )
    )


def _read_force_complete_threshold(session: Any) -> int:
    """Порог approval для mission-force-complete (5.6.b, CMS-first).

    Приоритет: активная SystemSetting-запись -> default каталога ->
    DEFAULT_FORCE_COMPLETE_THRESHOLD.
    """
    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == FORCE_COMPLETE_THRESHOLD_KEY,
            SystemSetting.status == ACTIVE_SETTING_STATUS,
        )
    )
    if (
        setting is not None
        and getattr(setting, "status", None) == ACTIVE_SETTING_STATUS
        and isinstance(setting.value_json, int)
        and setting.value_json >= 0
    ):
        return setting.value_json
    definition = get_definition(FORCE_COMPLETE_THRESHOLD_KEY)
    if definition is not None:
        return definition.default_value
    return DEFAULT_FORCE_COMPLETE_THRESHOLD


def _compute_reward_magnitude(session: Any, mission_id: str) -> int:
    """Суммарные ROOT-награды миссии (магнитуда для approval-порога).

    Считаются только currency-награды в ROOT с amount > 0 — те же, что
    реально выдаёт _award_mission_rewards. Предметы/стори-ноды не имеют
    ROOT-магнитуды и в порог не входят.
    """
    rewards = session.scalars(
        select(MissionReward).where(MissionReward.mission_id == mission_id)
    ).all()
    total = 0
    for reward in rewards:
        if (
            reward.reward_type == "currency"
            and (reward.reward_value or {}).get("currency") == ROOT_CURRENCY
            and reward.amount
            and reward.amount > 0
        ):
            total += reward.amount
    return total


def _has_mission_rewards(session: Any, mission_id: str) -> bool:
    """Есть ли у миссии хотя бы одна награда (для rewardSkipped-семантики)."""
    return (
        session.scalar(
            select(MissionReward)
            .where(MissionReward.mission_id == mission_id)
            .limit(1)
        )
        is not None
    )


def _find_force_complete_audit(
    session: Any, player_mission_id: str, request_id: str
) -> AdminAuditLog | None:
    """Успешное force-complete этой миссии с этим request_id уже в audit."""
    return session.scalar(
        select(AdminAuditLog).where(
            AdminAuditLog.entity_type == "player_mission",
            AdminAuditLog.entity_id == player_mission_id,
            AdminAuditLog.request_id == request_id,
            AdminAuditLog.outcome == "success",
            AdminAuditLog.action.in_(
                (
                    ACTION_TYPE_FORCE_COMPLETE,
                    f"{ACTION_TYPE_FORCE_COMPLETE}.via_approval",
                )
            ),
        )
    )


def _find_attempts_adjust_audit(
    session: Any, player_mission_id: str, request_id: str
) -> AdminAuditLog | None:
    """Успешная корректировка attempt_count этой миссии с request_id в audit."""
    return session.scalar(
        select(AdminAuditLog).where(
            AdminAuditLog.entity_type == "player_mission",
            AdminAuditLog.entity_id == player_mission_id,
            AdminAuditLog.request_id == request_id,
            AdminAuditLog.outcome == "success",
            AdminAuditLog.action.in_(
                (
                    ACTION_TYPE_ATTEMPTS_ADJUST,
                    f"{ACTION_TYPE_ATTEMPTS_ADJUST}.via_approval",
                )
            ),
        )
    )


def _apply_mission_cancel(
    session: Any,
    *,
    player_id: str,
    mission_id: str,
    reason: str,
    request_id: str,
    admin: AdminUser,
    request: Request,
    invalidate_entitlement: bool,
    approval: AdminApprovalRequest | None = None,
    player_mission: PlayerMission | None = None,
) -> tuple[PlayerMission, bool]:
    """Перевести PlayerMission в терминальный статус cancelled + аудит.

    Возвращает (player_mission, entitlement_invalidated). Entitlement'ы
    отключаются только при явном invalidate_entitlement=true и статусе
    available (exhausted/disabled не трогаем — это другие семантики);
    инвалидируются ВСЕ записи игрока по миссии (Sprint 8.16: у миссии может
    быть несколько fallback-entitlement'ов — по одному на ключ-награду).
    Ресурсы не возвращаются. Аудит пишется только после успешного flush.
    """
    if player_mission is None:
        player_mission = _find_player_mission(session, player_id, mission_id)
        if player_mission is None:
            raise MissionCancelError(
                status.HTTP_404_NOT_FOUND,
                "player_mission_not_found",
                "Прогресс по миссии не найден.",
            )
    if player_mission.status in TERMINAL_STATUSES:
        raise MissionCancelError(
            status.HTTP_409_CONFLICT,
            "mission_already_terminated",
            "Миссия уже завершена или отменена.",
        )

    def _snapshot(target: PlayerMission) -> dict[str, Any]:
        return {
            "status": target.status,
            "attemptCount": target.attempt_count,
            "startedAt": (
                target.started_at.isoformat()
                if getattr(target, "started_at", None)
                else None
            ),
        }

    before = _snapshot(player_mission)
    player_mission.status = CANCELLED_STATUS

    entitlement_invalidated = False
    if invalidate_entitlement:
        # Sprint 8.16: у миссии может быть несколько fallback-entitlement'ов
        # (по одному на каждый ключ-награду). Отключаем ВСЕ записи для
        # (player, mission), а не только первую.
        entitlements = session.scalars(
            select(PlayerFallbackEntitlement).where(
                PlayerFallbackEntitlement.player_id == player_id,
                PlayerFallbackEntitlement.mission_id == mission_id,
            )
        ).all()
        for entitlement in entitlements:
            if entitlement.status == ENTITLEMENT_ACTIVE_STATUS:
                entitlement.status = ENTITLEMENT_DISABLED_STATUS
                entitlement_invalidated = True
            elif entitlement.status == ENTITLEMENT_DISABLED_STATUS:
                # Уже disabled (предыдущей операцией/CMS): контракт
                # «инвалидировать» выполнен, состояние введено ранее.
                entitlement_invalidated = True
    session.flush()

    after = _snapshot(player_mission)
    metadata: dict[str, Any] = {
        "missionId": mission_id,
        "playerId": player_id,
        "requestId": request_id,
        "entitlementInvalidated": entitlement_invalidated,
        "fullReason": reason,
    }
    if approval is not None:
        metadata["approvalRequestId"] = approval.id

    write_admin_audit(
        session,
        actor=admin,
        action=(
            ACTION_TYPE_CANCEL
            if approval is None
            else f"{ACTION_TYPE_CANCEL}.via_approval"
        ),
        entity_type="player_mission",
        entity_id=player_mission.id,
        request=request,
        permission_code=PLAYERS_MANAGE_PERMISSION,
        approval_request_id=approval.id if approval is not None else None,
        request_id=request_id,
        before=before,
        after=after,
        # Двойная защита: recursive redaction и в audit-module, и здесь.
        metadata=sanitize_audit_data(metadata),
    )
    return player_mission, entitlement_invalidated


def _apply_mission_force_complete(
    session: Any,
    *,
    player_id: str,
    mission_id: str,
    reason: str,
    request_id: str,
    admin: AdminUser,
    request: Request,
    award_rewards: bool,
    approval: AdminApprovalRequest | None = None,
    player_mission: PlayerMission | None = None,
) -> tuple[PlayerMission, dict[str, Any], bool, bool]:
    """Перевести PlayerMission в терминальный статус completed + аудит.

    Возвращает (player_mission, reward_outcome, reward_skipped, entry_consumed):
    - entrée-ресурсы не возвращаются (компенсация — 5.4/5.5);
    - награды выдаются только при award_rewards=true через движковый
      _award_mission_rewards (ROOT — ledger-idempotent);
    - при award_rewards=false и наличии наград reward_skipped=true фиксирует
      осознанный пропуск выдачи в аудите;
    - entitlement остаётся available и не трогается;
    - attempt_count не меняется; started_at выставляется (если None);
    - guard: табличного статуса completed/available/in_progress/locked
      достаточно, CheckConstraint на status у PlayerMission нет.
    """
    if player_mission is None:
        player_mission = _find_player_mission(session, player_id, mission_id)
        if player_mission is None:
            raise MissionCancelError(
                status.HTTP_404_NOT_FOUND,
                "player_mission_not_found",
                "Прогресс по миссии не найден.",
            )
    if player_mission.status in TERMINAL_STATUSES:
        raise MissionCancelError(
            status.HTTP_409_CONFLICT,
            "mission_already_terminated",
            "Миссия уже завершена или отменена.",
        )

    def _snapshot(target: PlayerMission) -> dict[str, Any]:
        return {
            "status": target.status,
            "attemptCount": target.attempt_count,
            "startedAt": (
                target.started_at.isoformat()
                if getattr(target, "started_at", None)
                else None
            ),
        }

    before = _snapshot(player_mission)
    entry_consumed = before["status"] == "in_progress"
    now_ts = _now()
    if getattr(player_mission, "started_at", None) is None:
        player_mission.started_at = now_ts
    player_mission.status = COMPLETED_STATUS
    player_mission.completed_at = now_ts

    reward_outcome: dict[str, Any] = {"root": 0, "items": [], "storyNodeIds": []}
    reward_skipped = False
    if award_rewards:
        mission = session.get(Mission, mission_id)
        if mission is None:
            raise MissionCancelError(
                status.HTTP_404_NOT_FOUND,
                "mission_not_found",
                "Миссия не найдена.",
            )
        reward_outcome = _award_mission_rewards(session, player_id, mission)
    elif _has_mission_rewards(session, mission_id):
        reward_skipped = True

    session.flush()

    after = _snapshot(player_mission)
    metadata: dict[str, Any] = {
        "missionId": mission_id,
        "playerId": player_id,
        "requestId": request_id,
        "awardedRoot": reward_outcome["root"],
        "awardedItems": reward_outcome["items"],
        "awardedStoryNodeIds": reward_outcome["storyNodeIds"],
        "rewardSkipped": reward_skipped,
        "entryConsumed": entry_consumed,
        "fullReason": reason,
    }
    if approval is not None:
        metadata["approvalRequestId"] = approval.id

    write_admin_audit(
        session,
        actor=admin,
        action=(
            ACTION_TYPE_FORCE_COMPLETE
            if approval is None
            else f"{ACTION_TYPE_FORCE_COMPLETE}.via_approval"
        ),
        entity_type="player_mission",
        entity_id=player_mission.id,
        request=request,
        permission_code=PLAYERS_MANAGE_PERMISSION,
        approval_request_id=approval.id if approval is not None else None,
        request_id=request_id,
        before=before,
        after=after,
        # Двойная защита: recursive redaction и в audit-module, и здесь.
        metadata=sanitize_audit_data(metadata),
    )
    return player_mission, reward_outcome, reward_skipped, entry_consumed


def _apply_mission_attempts_adjustment(
    session: Any,
    *,
    player_id: str,
    mission_id: str,
    new_attempt_count: int,
    reason: str,
    request_id: str,
    admin: AdminUser,
    request: Request,
    approval: AdminApprovalRequest | None = None,
    player_mission: PlayerMission | None = None,
) -> tuple[PlayerMission, int, bool]:
    """Абсолютная ручная корректировка attempt_count (5.6.c).

    Возвращает (player_mission, old_value, changed). Меняется только
    attempt_count: status/started_at/progress не трогаются. Терминальные
    статусы -> 409 (mission_already_terminated). new == old -> changed=False,
    аудит пишется в любом случае. Fallback-семантика: установка 0 при
    отсутствии активного entitlement — следующий неверный submit может
    создать новое fallback-предложение (guard attempt_count_before == 0
    в create_first_failure_entitlement); при существующем entitlement
    эффекта нет (unique (player_id, mission_id)).
    """
    if player_mission is None:
        player_mission = _find_player_mission(session, player_id, mission_id)
        if player_mission is None:
            raise MissionCancelError(
                status.HTTP_404_NOT_FOUND,
                "player_mission_not_found",
                "Прогресс по миссии не найден.",
            )
    if player_mission.status in TERMINAL_STATUSES:
        raise MissionCancelError(
            status.HTTP_409_CONFLICT,
            "mission_already_terminated",
            "Миссия уже завершена или отменена.",
        )

    def _snapshot(target: PlayerMission) -> dict[str, Any]:
        return {"attemptCount": target.attempt_count}

    old_value = player_mission.attempt_count
    changed = old_value != new_attempt_count

    before = _snapshot(player_mission)
    player_mission.attempt_count = new_attempt_count
    session.flush()
    after = _snapshot(player_mission)

    metadata: dict[str, Any] = {
        "missionId": mission_id,
        "playerId": player_id,
        "requestId": request_id,
        "oldValue": old_value,
        "newValue": new_attempt_count,
        "changed": changed,
        "fullReason": reason,
    }
    if approval is not None:
        metadata["approvalRequestId"] = approval.id

    write_admin_audit(
        session,
        actor=admin,
        action=(
            ACTION_TYPE_ATTEMPTS_ADJUST
            if approval is None
            else f"{ACTION_TYPE_ATTEMPTS_ADJUST}.via_approval"
        ),
        entity_type="player_mission",
        entity_id=player_mission.id,
        request=request,
        permission_code=PLAYERS_MANAGE_PERMISSION,
        approval_request_id=approval.id if approval is not None else None,
        request_id=request_id,
        before=before,
        after=after,
        metadata=sanitize_audit_data(metadata),
    )
    return player_mission, old_value, changed


def _serialize_player_mission(player_mission: PlayerMission) -> dict[str, Any]:
    return {
        "id": player_mission.id,
        "playerId": player_mission.player_id,
        "missionId": player_mission.mission_id,
        "status": player_mission.status,
        "attemptCount": player_mission.attempt_count,
        "startedAt": (
            player_mission.started_at.isoformat()
            if getattr(player_mission, "started_at", None)
            else None
        ),
        "completedAt": (
            player_mission.completed_at.isoformat()
            if getattr(player_mission, "completed_at", None)
            else None
        ),
    }


def _serialize_cancel_result(
    player_mission: PlayerMission, entitlement_invalidated: bool, idempotent: bool
) -> dict[str, Any]:
    return {
        "playerMission": _serialize_player_mission(player_mission),
        # Идемпотентный replay не переприменяет операцию, поэтому текущий
        # эффект на entitlement известен только из исторического audit-снапшота.
        "entitlementInvalidated": entitlement_invalidated,
        "idempotent": idempotent,
    }


def _serialize_force_complete_result(
    player_mission: PlayerMission,
    reward_outcome: dict[str, Any],
    reward_skipped: bool,
    entry_consumed: bool,
    idempotent: bool,
) -> dict[str, Any]:
    return {
        "playerMission": _serialize_player_mission(player_mission),
        "rewardOutcome": {
            "awardedRoot": reward_outcome.get("root", 0),
            "awardedItems": reward_outcome.get("items", []),
            "awardedStoryNodeIds": reward_outcome.get("storyNodeIds", []),
        },
        "rewardSkipped": reward_skipped,
        "entryConsumed": entry_consumed,
        "idempotent": idempotent,
    }


def _serialize_attempts_adjust_result(
    player_mission: PlayerMission, changed: bool, idempotent: bool
) -> dict[str, Any]:
    return {
        "playerMission": _serialize_player_mission(player_mission),
        "changed": changed,
        "idempotent": idempotent,
    }


def _audit_approval(
    *,
    session: Any,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    outcome: str,
    request: Request,
    metadata: dict[str, Any] | None = None,
) -> None:
    write_admin_audit(
        session,
        actor=actor,
        action=action,
        entity_type="admin_approval_request",
        entity_id=approval.id,
        request=request,
        permission_code=approval.required_permission_code,
        approval_request_id=approval.id,
        request_id=approval.request_id,
        before=build_admin_approval_audit_snapshot(before),
        after=build_admin_approval_audit_snapshot(after),
        outcome=outcome,
        metadata=metadata
        or {
            "actionType": approval.action_type,
            "targetEntityType": approval.target_entity_type,
            "targetEntityId": approval.target_entity_id,
        },
    )


def _mark_execution_failed(
    *,
    session: Any,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    error_code: str,
    request: Request,
) -> dict[str, Any]:
    """Финальный consumed-статус EXECUTION_FAILED с аудитом (паттерн 5.x)."""
    before = _serialize_approval(approval)
    approval.status = EXECUTION_FAILED
    approval.executed_by_admin_id = actor.id
    approval.executed_at = _now()
    approval.execution_result = {"status": "failed", "errorCode": error_code}
    approval.execution_error = error_code
    session.flush()

    after = _serialize_approval(approval)
    _audit_approval(
        session=session,
        actor=actor,
        approval=approval,
        action="admin_approval_request.execution_failed",
        before=before,
        after=after,
        outcome="failure",
        request=request,
        metadata={
            "actionType": approval.action_type,
            "targetEntityType": approval.target_entity_type,
            "targetEntityId": approval.target_entity_id,
            "errorCode": error_code,
        },
    )
    return after


def _execution_failed_response(
    *,
    session: Any,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    error_code: str,
    request: Request,
) -> JSONResponse:
    after = _mark_execution_failed(
        session=session,
        actor=actor,
        approval=approval,
        error_code=error_code,
        request=request,
    )
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"approval": after, "idempotent": False, "error": error_code},
    )

def _create_cancel_request(
    *,
    session: Any,
    admin: AdminUser,
    player_id: str,
    player_mission: PlayerMission,
    mission_id: str,
    reason: str,
    request_id: str,
    expires_at: datetime | None,
    invalidate_entitlement: bool,
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на отмену миссии (idempotency по request_id).

    При повторном request_id с тем же содержимым отвечает 200 + idempotent,
    с другим содержимым — 409.
    """
    snapshot = {
        "playerId": player_id,
        "missionId": mission_id,
        "reason": reason,
        "invalidateFallbackEntitlement": invalidate_entitlement,
    }
    expected = {
        "required_permission_code": PLAYERS_MANAGE_PERMISSION,
        "action_type": ACTION_TYPE_CANCEL,
        "target_entity_type": "player_mission",
        "target_entity_id": player_mission.id,
        "payload_snapshot": snapshot,
        "reason": reason,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
    }

    existing = session.scalar(
        select(AdminApprovalRequest)
        .where(
            AdminApprovalRequest.requested_by_admin_id == admin.id,
            AdminApprovalRequest.request_id == request_id,
        )
        .with_for_update()
    )
    if existing is not None:
        current = {
            "required_permission_code": existing.required_permission_code,
            "action_type": existing.action_type,
            "target_entity_type": existing.target_entity_type,
            "target_entity_id": existing.target_entity_id,
            "payload_snapshot": existing.payload_snapshot,
            "reason": existing.reason,
            "expires_at": (
                existing.expires_at.isoformat() if existing.expires_at is not None else None
            ),
        }
        if current != expected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="requestId уже использован с другим содержимым заявки.",
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"approval": _serialize_approval(existing), "idempotent": True},
        )

    approval = AdminApprovalRequest(
        id=_new_id("admin-approval"),
        status=PENDING,
        requested_by_admin_id=admin.id,
        required_permission_code=PLAYERS_MANAGE_PERMISSION,
        action_type=ACTION_TYPE_CANCEL,
        target_entity_type="player_mission",
        target_entity_id=player_mission.id,
        payload_snapshot=snapshot,
        reason=reason,
        request_ip_address=_client_ip_address(request),
        request_id=request_id,
        expires_at=expires_at,
        execution_result={},
    )
    try:
        session.add(approval)
        session.flush()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Конфликт идемпотентности заявки.",
        ) from error

    serialized = _serialize_approval(approval)
    _audit_approval(
        session=session,
        actor=admin,
        approval=approval,
        action="admin_approval_request.created",
        before={},
        after=serialized,
        outcome="success",
        request=request,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"approval": serialized, "idempotent": False},
    )


def _create_force_complete_request(
    *,
    session: Any,
    admin: AdminUser,
    player_id: str,
    player_mission: PlayerMission,
    mission_id: str,
    reason: str,
    request_id: str,
    expires_at: datetime | None,
    award_rewards: bool,
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на принудительное завершение миссии.

    При повторном request_id с тем же содержимым отвечает 200 + idempotent,
    с другим содержимым — 409.
    """
    snapshot = {
        "playerId": player_id,
        "missionId": mission_id,
        "reason": reason,
        "awardRewards": award_rewards,
    }
    expected = {
        "required_permission_code": PLAYERS_MANAGE_PERMISSION,
        "action_type": ACTION_TYPE_FORCE_COMPLETE,
        "target_entity_type": "player_mission",
        "target_entity_id": player_mission.id,
        "payload_snapshot": snapshot,
        "reason": reason,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
    }

    existing = session.scalar(
        select(AdminApprovalRequest)
        .where(
            AdminApprovalRequest.requested_by_admin_id == admin.id,
            AdminApprovalRequest.request_id == request_id,
        )
        .with_for_update()
    )
    if existing is not None:
        current = {
            "required_permission_code": existing.required_permission_code,
            "action_type": existing.action_type,
            "target_entity_type": existing.target_entity_type,
            "target_entity_id": existing.target_entity_id,
            "payload_snapshot": existing.payload_snapshot,
            "reason": existing.reason,
            "expires_at": (
                existing.expires_at.isoformat() if existing.expires_at is not None else None
            ),
        }
        if current != expected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="requestId уже использован с другим содержимым заявки.",
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"approval": _serialize_approval(existing), "idempotent": True},
        )

    approval = AdminApprovalRequest(
        id=_new_id("admin-approval"),
        status=PENDING,
        requested_by_admin_id=admin.id,
        required_permission_code=PLAYERS_MANAGE_PERMISSION,
        action_type=ACTION_TYPE_FORCE_COMPLETE,
        target_entity_type="player_mission",
        target_entity_id=player_mission.id,
        payload_snapshot=snapshot,
        reason=reason,
        request_ip_address=_client_ip_address(request),
        request_id=request_id,
        expires_at=expires_at,
        execution_result={},
    )
    try:
        session.add(approval)
        session.flush()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Конфликт идемпотентности заявки.",
        ) from error

    serialized = _serialize_approval(approval)
    _audit_approval(
        session=session,
        actor=admin,
        approval=approval,
        action="admin_approval_request.created",
        before={},
        after=serialized,
        outcome="success",
        request=request,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"approval": serialized, "idempotent": False},
    )


def _create_attempts_adjust_request(
    *,
    session: Any,
    admin: AdminUser,
    player_id: str,
    player_mission: PlayerMission,
    mission_id: str,
    new_attempt_count: int,
    reason: str,
    request_id: str,
    expires_at: datetime | None,
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на корректировку attempt_count.

    При повторном request_id с тем же содержимым отвечает 200 + idempotent,
    с другим содержимым — 409.
    """
    snapshot = {
        "playerId": player_id,
        "missionId": mission_id,
        "newAttemptCount": new_attempt_count,
        "reason": reason,
    }
    expected = {
        "required_permission_code": PLAYERS_MANAGE_PERMISSION,
        "action_type": ACTION_TYPE_ATTEMPTS_ADJUST,
        "target_entity_type": "player_mission",
        "target_entity_id": player_mission.id,
        "payload_snapshot": snapshot,
        "reason": reason,
        "expires_at": expires_at.isoformat() if expires_at is not None else None,
    }

    existing = session.scalar(
        select(AdminApprovalRequest)
        .where(
            AdminApprovalRequest.requested_by_admin_id == admin.id,
            AdminApprovalRequest.request_id == request_id,
        )
        .with_for_update()
    )
    if existing is not None:
        current = {
            "required_permission_code": existing.required_permission_code,
            "action_type": existing.action_type,
            "target_entity_type": existing.target_entity_type,
            "target_entity_id": existing.target_entity_id,
            "payload_snapshot": existing.payload_snapshot,
            "reason": existing.reason,
            "expires_at": (
                existing.expires_at.isoformat()
                if existing.expires_at is not None
                else None
            ),
        }
        if current != expected:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="requestId уже использован с другим содержимым заявки.",
            )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"approval": _serialize_approval(existing), "idempotent": True},
        )

    approval = AdminApprovalRequest(
        id=_new_id("admin-approval"),
        status=PENDING,
        requested_by_admin_id=admin.id,
        required_permission_code=PLAYERS_MANAGE_PERMISSION,
        action_type=ACTION_TYPE_ATTEMPTS_ADJUST,
        target_entity_type="player_mission",
        target_entity_id=player_mission.id,
        payload_snapshot=snapshot,
        reason=reason,
        request_ip_address=_client_ip_address(request),
        request_id=request_id,
        expires_at=expires_at,
        execution_result={},
    )
    try:
        session.add(approval)
        session.flush()
    except IntegrityError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Конфликт идемпотентности заявки.",
        ) from error

    serialized = _serialize_approval(approval)
    _audit_approval(
        session=session,
        actor=admin,
        approval=approval,
        action="admin_approval_request.created",
        before={},
        after=serialized,
        outcome="success",
        request=request,
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content={"approval": serialized, "idempotent": False},
    )


@router.post("/{player_id}/missions/{mission_id}/mission-cancel", response_model=None)
def create_player_mission_cancel(
    player_id: str,
    mission_id: str,
    payload: MissionCancelPayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
) -> dict[str, Any] | JSONResponse:
    """Снять/отменить миссию: прямое исполнение либо approval-заявка.

    НЕ использует require_permission: для approval-ветки нужно самим считать
    execution_mode через get_permission_execution_mode (как 5.4/5.5).
    Порога-магнитуды здесь нет: отмена — бинарная операция без суммы,
    чувствительность задаётся execution-режимом гранта players.manage
    (direct / requires_super_admin_approval).
    """
    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")
    expires_at = (
        _validate_expiry(payload.expires_at) if payload.expires_at is not None else None
    )

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Игрок не найден.",
            )

        execution_mode = get_permission_execution_mode(admin, PLAYERS_MANAGE_PERMISSION)
        if execution_mode is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        player_mission = _find_player_mission(session, player_id, mission_id)
        if player_mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Прогресс по миссии не найден.",
            )

        if player_mission.status in TERMINAL_STATUSES:
            # Идемпотентный replay: тот же request_id -> 200 idempotent.
            replay = _find_cancel_audit(session, player_mission.id, request_id)
            if replay is not None:
                return _serialize_cancel_result(
                    player_mission,
                    entitlement_invalidated=False,
                    idempotent=True,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Миссия уже завершена или отменена.",
            )

        if execution_mode == APPROVAL_EXECUTION_MODE:
            return _create_cancel_request(
                session=session,
                admin=admin,
                player_id=player_id,
                player_mission=player_mission,
                mission_id=mission_id,
                reason=reason,
                request_id=request_id,
                expires_at=expires_at,
                invalidate_entitlement=payload.invalidate_fallback_entitlement,
                request=request,
            )

        try:
            updated, entitlement_invalidated = _apply_mission_cancel(
                session=session,
                player_id=player_id,
                mission_id=mission_id,
                reason=reason,
                request_id=request_id,
                admin=admin,
                request=request,
                invalidate_entitlement=payload.invalidate_fallback_entitlement,
                player_mission=player_mission,
            )
        except MissionCancelError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from error
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности отмены миссии.",
            ) from error

        return _serialize_cancel_result(updated, entitlement_invalidated, idempotent=False)


@router.post(
    "/{player_id}/missions/{mission_id}/mission-force-complete", response_model=None
)
def create_player_mission_force_complete(
    player_id: str,
    mission_id: str,
    payload: MissionForceCompletePayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
) -> dict[str, Any] | JSONResponse:
    """Принудительно завершить миссию игрока (5.6.b).

    direct-grant: исполнение сразу, если admin — super-admin ИЛИ суммарные
    ROOT-награды миссии меньше economy.mission_force_complete_approval_threshold.
    Иначе создаётся AdminApprovalRequest (player.mission_force_complete) -> 201.
    """
    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")
    expires_at = (
        _validate_expiry(payload.expires_at) if payload.expires_at is not None else None
    )

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Игрок не найден.",
            )

        execution_mode = get_permission_execution_mode(admin, PLAYERS_MANAGE_PERMISSION)
        if execution_mode is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        player_mission = _find_player_mission(session, player_id, mission_id)
        if player_mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Прогресс по миссии не найден.",
            )

        if player_mission.status in TERMINAL_STATUSES:
            # Идемпотентный replay: тот же request_id -> 200 idempotent.
            replay = _find_force_complete_audit(session, player_mission.id, request_id)
            if replay is not None:
                meta = replay.metadata_json or {}
                return _serialize_force_complete_result(
                    player_mission,
                    {
                        "root": meta.get("awardedRoot", 0),
                        "items": meta.get("awardedItems", []),
                        "storyNodeIds": meta.get("awardedStoryNodeIds", []),
                    },
                    reward_skipped=bool(meta.get("rewardSkipped", False)),
                    entry_consumed=bool(meta.get("entryConsumed", False)),
                    idempotent=True,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Миссия уже завершена или отменена.",
            )

        threshold = _read_force_complete_threshold(session)
        magnitude = _compute_reward_magnitude(session, mission_id)
        needs_approval = execution_mode == APPROVAL_EXECUTION_MODE or (
            not admin.is_super_admin and magnitude >= threshold
        )
        if needs_approval:
            return _create_force_complete_request(
                session=session,
                admin=admin,
                player_id=player_id,
                player_mission=player_mission,
                mission_id=mission_id,
                reason=reason,
                request_id=request_id,
                expires_at=expires_at,
                award_rewards=payload.award_rewards,
                request=request,
            )

        try:
            updated, reward_outcome, reward_skipped, entry_consumed = (
                _apply_mission_force_complete(
                    session=session,
                    player_id=player_id,
                    mission_id=mission_id,
                    reason=reason,
                    request_id=request_id,
                    admin=admin,
                    request=request,
                    award_rewards=payload.award_rewards,
                    player_mission=player_mission,
                )
            )
        except MissionCancelError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from error
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности завершения миссии.",
            ) from error

        return _serialize_force_complete_result(
            updated, reward_outcome, reward_skipped, entry_consumed, idempotent=False
        )


@router.post(
    "/{player_id}/missions/{mission_id}/attempts-adjustment", response_model=None
)
def create_player_mission_attempts_adjustment(
    player_id: str,
    mission_id: str,
    payload: MissionAttemptsAdjustPayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
) -> dict[str, Any] | JSONResponse:
    """Ручная корректировка attempt_count миссии игрока (5.6.c).

    direct-grant: исполнение сразу, порога-магнитуды нет — super-admin
    в direct ничем не блокируется. approval-grant — создание
    AdminApprovalRequest (player.mission_attempts_adjust) -> 201.
    Терминальные completed/cancelled -> 409; повтор с тем же request_id —
    200 idempotent (replay из immutable admin_audit_log).
    """
    reason = _normalize_required(payload.reason, "reason")
    request_id = _normalize_required(payload.request_id, "requestId")
    expires_at = (
        _validate_expiry(payload.expires_at) if payload.expires_at is not None else None
    )

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Игрок не найден.",
            )

        execution_mode = get_permission_execution_mode(admin, PLAYERS_MANAGE_PERMISSION)
        if execution_mode is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        player_mission = _find_player_mission(session, player_id, mission_id)
        if player_mission is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Прогресс по миссии не найден.",
            )

        if player_mission.status in TERMINAL_STATUSES:
            # Идемпотентный replay: тот же request_id -> 200 idempotent.
            replay = _find_attempts_adjust_audit(session, player_mission.id, request_id)
            if replay is not None:
                meta = replay.metadata_json or {}
                return _serialize_attempts_adjust_result(
                    player_mission,
                    changed=meta.get("oldValue") != meta.get("newValue"),
                    idempotent=True,
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Миссия уже завершена или отменена.",
            )

        if execution_mode == APPROVAL_EXECUTION_MODE:
            return _create_attempts_adjust_request(
                session=session,
                admin=admin,
                player_id=player_id,
                player_mission=player_mission,
                mission_id=mission_id,
                new_attempt_count=payload.new_attempt_count,
                reason=reason,
                request_id=request_id,
                expires_at=expires_at,
                request=request,
            )

        try:
            updated, _old_value, changed = _apply_mission_attempts_adjustment(
                session=session,
                player_id=player_id,
                mission_id=mission_id,
                new_attempt_count=payload.new_attempt_count,
                reason=reason,
                request_id=request_id,
                admin=admin,
                request=request,
                player_mission=player_mission,
            )
        except MissionCancelError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from error
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности корректировки попыток.",
            ) from error

        return _serialize_attempts_adjust_result(updated, changed, idempotent=False)


@router.post("/mission-cancel-requests/{approval_id}/execute", response_model=None)
def execute_player_mission_cancel(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
) -> dict[str, Any] | JSONResponse:
    """Исполнить approved заявку на отмену миссии только супер-админом.

    Никакого generic executor: принимается исключительно
    action_type == player.mission_cancel.
    """
    with SessionLocal.begin() as session:
        approval = session.scalar(
            select(AdminApprovalRequest)
            .where(AdminApprovalRequest.id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Заявка не найдена.",
            )

        if approval.action_type != ACTION_TYPE_CANCEL:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Executor принимает только player.mission_cancel.",
            )

        if approval.status == EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        expires_at = ensure_utc(approval.expires_at)
        if expires_at is not None and expires_at <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Исполнять можно только approved заявку.",
            )

        snapshot = approval.payload_snapshot or {}
        player_id = snapshot.get("playerId") or approval.target_entity_id
        mission_id = snapshot.get("missionId")
        reason = approval.reason or snapshot.get("reason") or ""
        invalidate_entitlement = bool(snapshot.get("invalidateFallbackEntitlement"))

        if not isinstance(mission_id, str) or not mission_id:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="invalid_payload_snapshot",
                request=request,
            )

        player = session.get(GamePlayer, player_id)
        if player is None:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="player_not_found",
                request=request,
            )

        try:
            updated, entitlement_invalidated = _apply_mission_cancel(
                session=session,
                player_id=player_id,
                mission_id=mission_id,
                reason=reason,
                request_id=approval.request_id,
                admin=admin,
                request=request,
                invalidate_entitlement=invalidate_entitlement,
                approval=approval,
            )
        except MissionCancelError as error:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code=error.code,
                request=request,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности: заявка переиспользует requestId.",
            ) from error

        before_approval = _serialize_approval(approval)
        approval.status = EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "playerId": player_id,
            "missionId": mission_id,
            "playerMissionId": updated.id,
            "entitlementInvalidated": entitlement_invalidated,
        }
        approval.execution_error = None
        session.flush()

        after_approval = _serialize_approval(approval)
        _audit_approval(
            session=session,
            actor=admin,
            approval=approval,
            action="admin_approval_request.executed",
            before=before_approval,
            after=after_approval,
            outcome="success",
            request=request,
            metadata={
                "actionType": approval.action_type,
                "targetEntityType": approval.target_entity_type,
                "targetEntityId": approval.target_entity_id,
                "playerMissionId": updated.id,
                "entitlementInvalidated": entitlement_invalidated,
            },
        )

        result = _serialize_cancel_result(updated, entitlement_invalidated, idempotent=False)
        return {"approval": after_approval, **result}


@router.post("/mission-force-complete-requests/{approval_id}/execute", response_model=None)
def execute_player_mission_force_complete(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
) -> dict[str, Any] | JSONResponse:
    """Исполнить approved заявку на force-complete только супер-админом.

    Никакого generic executor: принимается исключительно
    action_type == player.mission_force_complete.
    """
    with SessionLocal.begin() as session:
        approval = session.scalar(
            select(AdminApprovalRequest)
            .where(AdminApprovalRequest.id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Заявка не найдена.",
            )

        if approval.action_type != ACTION_TYPE_FORCE_COMPLETE:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Executor принимает только player.mission_force_complete.",
            )

        if approval.status == EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        expires_at = ensure_utc(approval.expires_at)
        if expires_at is not None and expires_at <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Исполнять можно только approved заявку.",
            )

        snapshot = approval.payload_snapshot or {}
        player_id = snapshot.get("playerId") or approval.target_entity_id
        mission_id = snapshot.get("missionId")
        reason = approval.reason or snapshot.get("reason") or ""
        award_rewards = bool(snapshot.get("awardRewards", True))

        if not isinstance(mission_id, str) or not mission_id:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="invalid_payload_snapshot",
                request=request,
            )

        player = session.get(GamePlayer, player_id)
        if player is None:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="player_not_found",
                request=request,
            )

        try:
            (
                updated,
                reward_outcome,
                reward_skipped,
                entry_consumed,
            ) = _apply_mission_force_complete(
                session=session,
                player_id=player_id,
                mission_id=mission_id,
                reason=reason,
                request_id=approval.request_id,
                admin=admin,
                request=request,
                award_rewards=award_rewards,
                approval=approval,
            )
        except MissionCancelError as error:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code=error.code,
                request=request,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности: заявка переиспользует requestId.",
            ) from error

        before_approval = _serialize_approval(approval)
        approval.status = EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "playerId": player_id,
            "missionId": mission_id,
            "playerMissionId": updated.id,
            "awardedRoot": reward_outcome["root"],
            "rewardSkipped": reward_skipped,
            "entryConsumed": entry_consumed,
        }
        approval.execution_error = None
        session.flush()

        after_approval = _serialize_approval(approval)
        _audit_approval(
            session=session,
            actor=admin,
            approval=approval,
            action="admin_approval_request.executed",
            before=before_approval,
            after=after_approval,
            outcome="success",
            request=request,
            metadata={
                "actionType": approval.action_type,
                "targetEntityType": approval.target_entity_type,
                "targetEntityId": approval.target_entity_id,
                "playerMissionId": updated.id,
                "awardedRoot": reward_outcome["root"],
                "rewardSkipped": reward_skipped,
                "entryConsumed": entry_consumed,
            },
        )

        result = _serialize_force_complete_result(
            updated, reward_outcome, reward_skipped, entry_consumed, idempotent=False
        )
        return {"approval": after_approval, **result}


@router.post("/attempts-adjustment-requests/{approval_id}/execute", response_model=None)
def execute_player_mission_attempts_adjustment(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
) -> dict[str, Any] | JSONResponse:
    """Исполнить approved заявку на корректировку attempt_count (super-admin).

    Никакого generic executor: принимается исключительно
    action_type == player.mission_attempts_adjust.
    """
    with SessionLocal.begin() as session:
        approval = session.scalar(
            select(AdminApprovalRequest)
            .where(AdminApprovalRequest.id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Заявка не найдена.",
            )

        if approval.action_type != ACTION_TYPE_ATTEMPTS_ADJUST:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Executor принимает только player.mission_attempts_adjust.",
            )

        if approval.status == EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        expires_at = ensure_utc(approval.expires_at)
        if expires_at is not None and expires_at <= _now():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Срок действия заявки истёк.",
            )

        if approval.status != APPROVED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Исполнять можно только approved заявку.",
            )

        snapshot = approval.payload_snapshot or {}
        player_id = snapshot.get("playerId") or approval.target_entity_id
        mission_id = snapshot.get("missionId")
        reason = approval.reason or snapshot.get("reason") or ""
        new_attempt_count = snapshot.get("newAttemptCount")

        if (
            not isinstance(mission_id, str)
            or not mission_id
            or not isinstance(new_attempt_count, int)
            or isinstance(new_attempt_count, bool)
            or not (ATTEMPTS_MIN <= new_attempt_count <= ATTEMPTS_MAX)
        ):
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="invalid_payload_snapshot",
                request=request,
            )

        player = session.get(GamePlayer, player_id)
        if player is None:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code="player_not_found",
                request=request,
            )

        try:
            updated, _old_value, changed = _apply_mission_attempts_adjustment(
                session=session,
                player_id=player_id,
                mission_id=mission_id,
                new_attempt_count=new_attempt_count,
                reason=reason,
                request_id=approval.request_id,
                admin=admin,
                request=request,
                approval=approval,
            )
        except MissionCancelError as error:
            return _execution_failed_response(
                session=session,
                actor=admin,
                approval=approval,
                error_code=error.code,
                request=request,
            )
        except IntegrityError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Конфликт идемпотентности: заявка переиспользует requestId.",
            ) from error

        before_approval = _serialize_approval(approval)
        approval.status = EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "playerId": player_id,
            "missionId": mission_id,
            "playerMissionId": updated.id,
            "attemptCount": updated.attempt_count,
            "changed": changed,
        }
        approval.execution_error = None
        session.flush()

        after_approval = _serialize_approval(approval)
        _audit_approval(
            session=session,
            actor=admin,
            approval=approval,
            action="admin_approval_request.executed",
            before=before_approval,
            after=after_approval,
            outcome="success",
            request=request,
            metadata={
                "actionType": approval.action_type,
                "targetEntityType": approval.target_entity_type,
                "targetEntityId": approval.target_entity_id,
                "playerMissionId": updated.id,
                "attemptCount": updated.attempt_count,
                "changed": changed,
            },
        )

        result = _serialize_attempts_adjust_result(updated, changed, idempotent=False)
        return {"approval": after_approval, **result}