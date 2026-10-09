"""Admin Teams API (шаг 6.7.a — только команды, без чата).

Read-эндпоинты (permission ``teams.read``, direct):
  GET  /api/v1/admin/teams                            — list с фильтрами
  GET  /api/v1/admin/teams/{team_id}                  — карточка команды
  GET  /api/v1/admin/teams/{team_id}/members          — состав
  GET  /api/v1/admin/teams/{team_id}/history          — immutable-история
  GET  /api/v1/admin/teams/{team_id}/invitations      — приглашения
  GET  /api/v1/admin/teams/{team_id}/join-requests    — заявки на вступление

Мутирующие эндпоинты (permission ``teams.manage``, direct ИЛИ approval):
  POST /api/v1/admin/teams/{team_id}/force-disband
  POST /api/v1/admin/teams/{team_id}/members/{player_id}/force-kick

При execution_mode гранта ``requires_super_admin_approval`` создаётся
immutable AdminApprovalRequest (202 + approvalRequestId), иначе операция
выполняется немедленно. Исполнение approved-заявок — только супер-админом,
через dedicated executor (никакого generic execute по action_type):

  POST /api/v1/admin/teams/force-disband-requests/{approval_id}/execute
  POST /api/v1/admin/teams/force-kick-requests/{approval_id}/execute

Чат-модерация (teams.moderate_chat, модель TeamMessage) — шаг 6.6/6.7.b,
в этом модуле НЕ реализуется.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin_access import (
    APPROVAL_EXECUTION_MODE,
    get_admin_user,
    get_permission_execution_mode,
    require_permission,
    require_super_admin,
)
from app.admin_audit import write_admin_audit
from app.db import SessionLocal
from app.geo_team_runtime_models import TeamSession, TeamSessionMember
from app.models import (
    AdminApprovalRequest,
    AdminUser,
    GamePlayer,
    Team,
    TeamInvitation,
    TeamJoinRequest,
    TeamMember,
    TeamMembershipHistory,
)
from app.teams_service import (
    INVITATION_STATUS_PENDING,
    JOIN_REQUEST_STATUS_PENDING,
    MEMBER_STATUS_ACTIVE,
    MEMBER_STATUS_LEFT,
    ROLE_LEADER,
    SESSION_BLOCKING_STATUSES,
    TEAM_STATUS_ACTIVE,
    _record_history,
    _serialize_invitation,
    _serialize_join_request,
)

router = APIRouter(prefix="/api/v1/admin/teams", tags=["admin-teams"])

TEAMS_READ_PERMISSION = "teams.read"
TEAMS_MANAGE_PERMISSION = "teams.manage"

ACTION_TYPE_FORCE_DISBAND = "teams.force_disband"
ACTION_TYPE_FORCE_KICK = "teams.force_kick"

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200

REASON_MAX = 2000

VALID_MEMBER_STATUS_FILTERS = {"active", "left", "all"}
VALID_TEAM_STATUS_FILTERS = {"active", "disbanded", "all"}

APPROVAL_STATUS_PENDING = "pending"
APPROVAL_STATUS_APPROVED = "approved"
APPROVAL_STATUS_EXECUTED = "executed"


class TeamAdminError(Exception):
    """Доменная ошибка admin-командных операций (machine-readable code)."""

    def __init__(self, status_code: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.code = code
        self.detail = detail


class ForceDisbandPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=REASON_MAX)


class ForceKickPayload(BaseModel):
    reason: str = Field(min_length=1, max_length=REASON_MAX)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _normalize_reason(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise HTTPException(
            status_code=422,
            detail="reason не может состоять только из пробелов.",
        )
    return normalized


def _get_team_or_404(session: Session, team_id: str) -> Team:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Команда не найдена.")
    return team


def _raise_team_error(status_code: int, code: str, detail: str) -> None:
    raise TeamAdminError(status_code, code, detail)


def _has_blocking_session_for_players(
    session: Session,
    player_ids,
) -> bool:
    """Правило 5.3: любой из игроков задействован в активной командной миссии."""
    blocker = session.scalar(
        select(TeamSessionMember.id)
        .join(TeamSession, TeamSession.id == TeamSessionMember.team_session_id)
        .where(
            TeamSessionMember.player_id.in_(player_ids),
            TeamSession.status.in_(SESSION_BLOCKING_STATUSES),
        )
        .limit(1)
    )
    return blocker is not None


def _has_blocking_session_for_player(session: Session, player_id: str) -> bool:
    return _has_blocking_session_for_players(session, [player_id])


def _member_count(session: Session, team_id: str) -> int:
    return (
        session.scalar(
            select(func.count())
            .select_from(TeamMember)
            .where(
                TeamMember.team_id == team_id,
                TeamMember.status == MEMBER_STATUS_ACTIVE,
            )
        )
        or 0
    )


# ---- Сериализация ----------------------------------------------------------


def _serialize_team_item(
    team: Team,
    member_count: int,
) -> dict[str, Any]:
    return {
        "id": team.id,
        "name": team.name,
        "leaderId": team.leader_id,
        "status": team.status,
        "joinPolicy": team.join_policy,
        "maxMembers": team.max_members,
        "memberCount": member_count,
        "createdAt": team.created_at.isoformat() if team.created_at else None,
    }


def _serialize_team_card(session: Session, team: Team) -> dict[str, Any]:
    """Карточка команды для админа (disbanded тоже отдаётся)."""
    members = session.scalars(
        select(TeamMember)
        .where(
            TeamMember.team_id == team.id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
        .order_by(TeamMember.joined_at, TeamMember.id)
    ).all()
    leader = session.get(GamePlayer, team.leader_id)

    return {
        **{
            "id": team.id,
            "name": team.name,
            "description": team.description,
            "emblemUrl": team.emblem_url,
            "leaderId": team.leader_id,
            "status": team.status,
            "joinPolicy": team.join_policy,
            "maxMembers": team.max_members,
            "createdAt": team.created_at.isoformat() if team.created_at else None,
        },
        "memberCount": len(members),
        "leader": {
            "id": team.leader_id,
            "displayName": leader.display_name if leader is not None else None,
        },
        "members": [
            {
                "id": member.player_id,
                "role": member.role,
                "joinedAt": member.joined_at.isoformat() if member.joined_at else None,
            }
            for member in members
        ],
    }


def _serialize_membership(member: TeamMember) -> dict[str, Any]:
    return {
        "id": member.id,
        "teamId": member.team_id,
        "playerId": member.player_id,
        "role": member.role,
        "status": member.status,
        "joinedAt": member.joined_at.isoformat() if member.joined_at else None,
        "leftAt": member.left_at.isoformat() if member.left_at else None,
    }


def _serialize_history(row: TeamMembershipHistory) -> dict[str, Any]:
    return {
        "id": row.id,
        "teamId": row.team_id,
        "playerId": row.player_id,
        "eventType": row.event_type,
        "actorPlayerId": row.actor_player_id,
        "metadataJson": row.metadata_json,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }
def _serialize_approval(approval: AdminApprovalRequest) -> dict[str, Any]:
    return {
        "id": approval.id,
        "status": approval.status,
        "requestedByAdminId": approval.requested_by_admin_id,
        "requiredPermissionCode": approval.required_permission_code,
        "actionType": approval.action_type,
        "targetEntityType": approval.target_entity_type,
        "targetEntityId": approval.target_entity_id,
        "payloadSnapshot": approval.payload_snapshot,
        "reason": approval.reason,
        "requestId": approval.request_id,
        "expiresAt": (
            approval.expires_at.isoformat() if approval.expires_at else None
        ),
        "approvedByAdminId": approval.approved_by_admin_id,
        "approvedAt": (
            approval.approved_at.isoformat() if approval.approved_at else None
        ),
        "executedByAdminId": approval.executed_by_admin_id,
        "executedAt": (
            approval.executed_at.isoformat() if approval.executed_at else None
        ),
        "executionResult": approval.execution_result,
        "createdAt": approval.created_at.isoformat() if approval.created_at else None,
    }


def _audit_approval(
    session: Session,
    *,
    actor: AdminUser,
    action: str,
    approval: AdminApprovalRequest,
    before: dict[str, Any],
    after: dict[str, Any],
    request: Request,
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
        before=before,
        after=after,
        metadata={
            "actionType": approval.action_type,
            "targetEntityType": approval.target_entity_type,
            "targetEntityId": approval.target_entity_id,
        },
    )


def _mark_execution_failed(
    *,
    session: Session,
    actor: AdminUser,
    approval: AdminApprovalRequest,
    error_code: str,
    request: Request,
) -> JSONResponse:
    before = _serialize_approval(approval)
    approval.status = "execution_failed"
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
        request=request,
    )

    return JSONResponse(
        status_code=409,
        content={
            "approval": after,
            "idempotent": False,
            "error": error_code,
        },
    )


def _create_force_request(
    *,
    session: Session,
    admin: AdminUser,
    action_type: str,
    target_entity_type: str,
    target_entity_id: str,
    reason: str,
    snapshot: dict[str, Any],
    request: Request,
) -> JSONResponse:
    """Создать immutable заявку на чувствительную командную операцию.

    Идемпотентность на уровне «одна pending заявка на того же админа,
    ту же операцию и ту же цель»: повторный вызов возвращает существующую
    заявку (202 + idempotent). request_id генерируется сервером — клиент
    его не предоставляет (в отличие от 5.x).
    """
    existing = session.scalar(
        select(AdminApprovalRequest)
        .where(
            AdminApprovalRequest.requested_by_admin_id == admin.id,
            AdminApprovalRequest.action_type == action_type,
            AdminApprovalRequest.target_entity_type == target_entity_type,
            AdminApprovalRequest.target_entity_id == target_entity_id,
            AdminApprovalRequest.status == APPROVAL_STATUS_PENDING,
        )
        .with_for_update()
    )
    if existing is not None:
        return JSONResponse(
            status_code=202,
            content={
                "approvalRequestId": existing.id,
                "approval": _serialize_approval(existing),
                "idempotent": True,
            },
        )

    approval = AdminApprovalRequest(
        id=_new_id("admin-approval"),
        status=APPROVAL_STATUS_PENDING,
        requested_by_admin_id=admin.id,
        required_permission_code=TEAMS_MANAGE_PERMISSION,
        action_type=action_type,
        target_entity_type=target_entity_type,
        target_entity_id=target_entity_id,
        payload_snapshot=snapshot,
        reason=reason,
        request_id=f"{action_type.replace('.', '-')}-{uuid4().hex}",
        expires_at=None,
        execution_result={},
    )
    session.add(approval)
    session.flush()

    serialized = _serialize_approval(approval)
    _audit_approval(
        session=session,
        actor=admin,
        approval=approval,
        action="admin_approval_request.created",
        before={},
        after=serialized,
        request=request,
    )
    return JSONResponse(
        status_code=202,
        content={
            "approvalRequestId": approval.id,
            "approval": serialized,
            "idempotent": False,
        },
    )
# ---- Read-эндпоинты (teams.read) -------------------------------------------


@router.get("")
def list_admin_teams(
    status: str = "active",
    join_policy: str | None = None,
    leader_id: str | None = None,
    q: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(TEAMS_READ_PERMISSION)),
):
    """Список команд с фильтрами и пагинацией.
    status: active (по умолчанию) | disbanded | all.
    """
    if status not in VALID_TEAM_STATUS_FILTERS:
        raise HTTPException(
            status_code=422,
            detail="status должен быть одним из: active, disbanded, all.",
        )

    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)

    conditions = []
    if status != "all":
        conditions.append(Team.status == status)
    if join_policy:
        conditions.append(Team.join_policy == join_policy)
    if leader_id:
        conditions.append(Team.leader_id == leader_id)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        conditions.append(Team.name.ilike(pattern))

    with SessionLocal() as session:  # read-only, не begin()
        total = (
            session.scalar(
                select(func.count())
                .select_from(Team)
                .where(*conditions)
            )
            or 0
        )

        teams = session.scalars(
            select(Team)
            .where(*conditions)
            .order_by(Team.created_at.desc(), Team.id)
            .offset(offset)
            .limit(limit)
        ).all()

        items = [_serialize_team_item(t, _member_count(session, t.id)) for t in teams]

    return {"teams": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{team_id}")
def get_admin_team_detail(
    team_id: str,
    _admin: AdminUser = Depends(require_permission(TEAMS_READ_PERMISSION)),
):
    """Карточка команды; disbanded-команды тоже отдаются админу."""
    with SessionLocal() as session:
        team = _get_team_or_404(session, team_id)
        return {"team": _serialize_team_card(session, team)}


@router.get("/{team_id}/members")
def list_admin_team_members(
    team_id: str,
    status: str = MEMBER_STATUS_ACTIVE,
    _admin: AdminUser = Depends(require_permission(TEAMS_READ_PERMISSION)),
):
    """Состав команды: active (по умолчанию), left или all."""
    if status not in VALID_MEMBER_STATUS_FILTERS:
        raise HTTPException(
            status_code=422,
            detail="status должен быть одним из: active, left, all.",
        )

    with SessionLocal() as session:
        team = _get_team_or_404(session, team_id)
        conditions = [TeamMember.team_id == team.id]
        if status != "all":
            conditions.append(TeamMember.status == status)

        members = session.scalars(
            select(TeamMember)
            .where(*conditions)
            .order_by(TeamMember.joined_at, TeamMember.id)
        ).all()

        return {"teamId": team.id, "members": [_serialize_membership(m) for m in members]}


@router.get("/{team_id}/history")
def list_admin_team_history(
    team_id: str,
    limit: int = DEFAULT_LIST_LIMIT,
    offset: int = 0,
    _admin: AdminUser = Depends(require_permission(TEAMS_READ_PERMISSION)),
):
    """Immutable-история изменений состава (новые сверху)."""
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    offset = max(0, offset)

    with SessionLocal() as session:
        team = _get_team_or_404(session, team_id)
        rows = session.scalars(
            select(TeamMembershipHistory)
            .where(TeamMembershipHistory.team_id == team.id)
            .order_by(TeamMembershipHistory.created_at.desc(), TeamMembershipHistory.id)
            .offset(offset)
            .limit(limit)
        ).all()

        return {"teamId": team.id, "history": [_serialize_history(r) for r in rows]}


@router.get("/{team_id}/invitations")
def list_admin_team_invitations(
    team_id: str,
    status: str = INVITATION_STATUS_PENDING,
    _admin: AdminUser = Depends(require_permission(TEAMS_READ_PERMISSION)),
):
    """Приглашения команды (по умолчанию — только pending)."""
    with SessionLocal() as session:
        team = _get_team_or_404(session, team_id)
        invitations = session.scalars(
            select(TeamInvitation)
            .where(TeamInvitation.team_id == team.id, TeamInvitation.status == status)
            .order_by(TeamInvitation.created_at.desc(), TeamInvitation.id)
        ).all()

        return {
            "teamId": team.id,
            "invitations": [_serialize_invitation(inv) for inv in invitations],
        }


@router.get("/{team_id}/join-requests")
def list_admin_team_join_requests(
    team_id: str,
    status: str = JOIN_REQUEST_STATUS_PENDING,
    _admin: AdminUser = Depends(require_permission(TEAMS_READ_PERMISSION)),
):
    """Заявки на вступление в команду (по умолчанию — только pending)."""
    with SessionLocal() as session:
        team = _get_team_or_404(session, team_id)
        requests = session.scalars(
            select(TeamJoinRequest)
            .where(TeamJoinRequest.team_id == team.id, TeamJoinRequest.status == status)
            .order_by(TeamJoinRequest.created_at.desc(), TeamJoinRequest.id)
        ).all()

        return {
            "teamId": team.id,
            "joinRequests": [_serialize_join_request(req) for req in requests],
        }
# ---- Мутирующие операции (teams.manage) ------------------------------------


def _ensure_force_disband_allowed(session: Session, team_id: str) -> Team:
    """404/409-проверки для force-disband (используется и в direct, и в approval)."""
    team = _get_team_or_404(session, team_id)
    if team.status != TEAM_STATUS_ACTIVE:
        _raise_team_error(409, "team_not_active", "Команда уже расформирована.")
    if _has_blocking_session_for_players(
        session,
        select(TeamMember.player_id).where(
            TeamMember.team_id == team.id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        ),
    ):
        _raise_team_error(
            409,
            "team_busy",
            "Нельзя расформировать команду, пока участник в активной командной миссии.",
        )
    return team


def _ensure_force_kick_allowed(
    session: Session, team_id: str, player_id: str
) -> TeamMember:
    """404/409-проверки для force-kick."""
    team = _get_team_or_404(session, team_id)
    if team.status != TEAM_STATUS_ACTIVE:
        _raise_team_error(
            409,
            "team_not_active",
            "Команда расформирована — исключение невозможно.",
        )
    membership = session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.player_id == player_id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    )
    if membership is None:
        _raise_team_error(
            404,
            "membership_not_found",
            "Активное членство игрока в команде не найдено.",
        )
    if membership.role == ROLE_LEADER:
        _raise_team_error(
            409,
            "cannot_kick_leader",
            "Исключить лидера нельзя: команда останется без лидера. "
            "Смените лидера (transfer) или расформируйте команду.",
        )
    if _has_blocking_session_for_player(session, membership.player_id):
        _raise_team_error(
            409,
            "member_busy",
            "Игрок участвует в активной командной миссии — исключение невозможно.",
        )
    return membership


def _apply_force_disband(
    session: Session,
    *,
    admin: AdminUser,
    team_id: str,
    reason: str,
    request: Request,
    approval: AdminApprovalRequest | None = None,
) -> dict[str, Any]:
    """Расформировать команду от имени админа (actor в history metadata).

    По паттерну teams_service._disband_team, но без требования лидера.
    Guard 5.3 сохраняется полностью: активная командная миссия любого
    участника блокирует disband (модерация не ломает runtime).
    """
    team = _ensure_force_disband_allowed(session, team_id)

    members = session.scalars(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.status == MEMBER_STATUS_ACTIVE,
        )
    ).all()

    before = _serialize_team_item(team, len(members))
    team.status = "disbanded"
    now = _now()
    for member in members:
        member.status = MEMBER_STATUS_LEFT
        member.left_at = now
        _record_history(
            session,
            team_id=team.id,
            player_id=member.player_id,
            event_type="disbanded",
            actor_player_id=None,
            metadata={"via": "admin", "adminId": admin.id, "reason": reason},
        )
    session.flush()
    after = _serialize_team_item(team, 0)

    write_admin_audit(
        session,
        actor=admin,
        action=(
            ACTION_TYPE_FORCE_DISBAND
            if approval is None
            else f"{ACTION_TYPE_FORCE_DISBAND}.via_approval"
        ),
        entity_type="team",
        entity_id=team.id,
        request=request,
        permission_code=TEAMS_MANAGE_PERMISSION,
        approval_request_id=approval.id if approval is not None else None,
        before=before,
        after=after,
        metadata={
            "actionType": ACTION_TYPE_FORCE_DISBAND,
            "teamId": team.id,
            "reason": reason,
            "disbandedMemberCount": len(members),
        },
    )
    return {"teamId": team.id, "disbanded": True, "team": after}
def _apply_force_kick(
    session: Session,
    *,
    admin: AdminUser,
    team_id: str,
    player_id: str,
    reason: str,
    request: Request,
    approval: AdminApprovalRequest | None = None,
) -> dict[str, Any]:
    """Исключить игрока из команды от имени админа.

    Лидера не исключаем: смена лидера — только через transfer (6.4) или
    force-disband, иначе команда останется без лидера.
    """
    membership = _ensure_force_kick_allowed(session, team_id, player_id)

    before = _serialize_membership(membership)
    membership.status = MEMBER_STATUS_LEFT
    membership.left_at = _now()
    _record_history(
        session,
        team_id=team_id,
        player_id=membership.player_id,
        event_type="kicked",
        actor_player_id=None,
        metadata={"via": "admin", "adminId": admin.id, "reason": reason},
    )
    session.flush()
    after = _serialize_membership(membership)

    write_admin_audit(
        session,
        actor=admin,
        action=(
            ACTION_TYPE_FORCE_KICK
            if approval is None
            else f"{ACTION_TYPE_FORCE_KICK}.via_approval"
        ),
        entity_type="team_member",
        entity_id=membership.id,
        request=request,
        permission_code=TEAMS_MANAGE_PERMISSION,
        approval_request_id=approval.id if approval is not None else None,
        before=before,
        after=after,
        metadata={
            "actionType": ACTION_TYPE_FORCE_KICK,
            "teamId": team_id,
            "playerId": membership.player_id,
            "reason": reason,
        },
    )
    return {"teamId": team_id, "playerId": player_id, "kicked": True}
@router.post("/{team_id}/force-disband", response_model=None)
def create_force_disband(
    team_id: str,
    payload: ForceDisbandPayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
):
    """Расформировать команду: прямое исполнение или approval-заявка.

    НЕ использует require_permission: для approval-ветки execution_mode
    гранта teams.manage считается через get_permission_execution_mode
    (паттерн 5.6 admin_player_mission).
    """
    reason = _normalize_reason(payload.reason)

    with SessionLocal.begin() as session:
        try:
            _ensure_force_disband_allowed(session, team_id)
        except TeamAdminError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from error

        execution_mode = get_permission_execution_mode(admin, TEAMS_MANAGE_PERMISSION)
        if execution_mode is None:
            raise HTTPException(
                status_code=403,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        if execution_mode == APPROVAL_EXECUTION_MODE:
            return _create_force_request(
                session=session,
                admin=admin,
                action_type=ACTION_TYPE_FORCE_DISBAND,
                target_entity_type="team",
                target_entity_id=team_id,
                reason=reason,
                snapshot={"teamId": team_id, "reason": reason},
                request=request,
            )

        try:
            return _apply_force_disband(
                session=session,
                admin=admin,
                team_id=team_id,
                reason=reason,
                request=request,
            )
        except TeamAdminError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from error


@router.post("/{team_id}/members/{player_id}/force-kick", response_model=None)
def create_force_kick(
    team_id: str,
    player_id: str,
    payload: ForceKickPayload,
    request: Request,
    admin: AdminUser = Depends(get_admin_user),
):
    """Исключить игрока из команды: прямое исполнение или approval-заявка."""
    reason = _normalize_reason(payload.reason)

    with SessionLocal.begin() as session:
        try:
            _ensure_force_kick_allowed(session, team_id, player_id)
        except TeamAdminError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from error

        execution_mode = get_permission_execution_mode(admin, TEAMS_MANAGE_PERMISSION)
        if execution_mode is None:
            raise HTTPException(
                status_code=403,
                detail="Недостаточно прав для выполнения этого действия.",
            )

        if execution_mode == APPROVAL_EXECUTION_MODE:
            return _create_force_request(
                session=session,
                admin=admin,
                action_type=ACTION_TYPE_FORCE_KICK,
                target_entity_type="team_member",
                target_entity_id=f"{team_id}:{player_id}",
                reason=reason,
                snapshot={"teamId": team_id, "playerId": player_id, "reason": reason},
                request=request,
            )

        try:
            return _apply_force_kick(
                session=session,
                admin=admin,
                team_id=team_id,
                player_id=player_id,
                reason=reason,
                request=request,
            )
        except TeamAdminError as error:
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from error


# ---- Dedicated executors approved-заявок (только супер-админ) ---------------


@router.post("/force-disband-requests/{approval_id}/execute", response_model=None)
def execute_force_disband(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
):
    """Исполнить approved заявку teams.force_disband.

    Никакого generic executor: принимается исключительно
    action_type == teams.force_disband.
    """
    with SessionLocal.begin() as session:
        approval = session.scalar(
            select(AdminApprovalRequest)
            .where(AdminApprovalRequest.id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена.")

        if approval.action_type != ACTION_TYPE_FORCE_DISBAND:
            raise HTTPException(
                status_code=422,
                detail="Executor принимает только teams.force_disband.",
            )

        if approval.status == APPROVAL_STATUS_EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        if approval.status != APPROVAL_STATUS_APPROVED:
            raise HTTPException(
                status_code=409,
                detail="Исполнять можно только approved заявку.",
            )

        team_id = approval.target_entity_id or ""
        reason = approval.reason or ""
        try:
            result = _apply_force_disband(
                session=session,
                admin=admin,
                team_id=team_id,
                reason=reason,
                request=request,
                approval=approval,
            )
        except TeamAdminError as error:
            return _mark_execution_failed(
                session=session,
                actor=admin,
                approval=approval,
                error_code=error.code,
                request=request,
            )

        before_approval = _serialize_approval(approval)
        approval.status = APPROVAL_STATUS_EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "teamId": team_id,
            "disbanded": True,
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
            request=request,
        )
        return {"approval": after_approval, **result}


@router.post("/force-kick-requests/{approval_id}/execute", response_model=None)
def execute_force_kick(
    approval_id: str,
    request: Request,
    admin: AdminUser = Depends(require_super_admin),
):
    """Исполнить approved заявку teams.force_kick.

    Никакого generic executor: принимается исключительно
    action_type == teams.force_kick.
    """
    with SessionLocal.begin() as session:
        approval = session.scalar(
            select(AdminApprovalRequest)
            .where(AdminApprovalRequest.id == approval_id)
            .with_for_update()
        )
        if approval is None:
            raise HTTPException(status_code=404, detail="Заявка не найдена.")

        if approval.action_type != ACTION_TYPE_FORCE_KICK:
            raise HTTPException(
                status_code=422,
                detail="Executor принимает только teams.force_kick.",
            )

        if approval.status == APPROVAL_STATUS_EXECUTED:
            return {"approval": _serialize_approval(approval), "idempotent": True}

        if approval.status != APPROVAL_STATUS_APPROVED:
            raise HTTPException(
                status_code=409,
                detail="Исполнять можно только approved заявку.",
            )

        snapshot = approval.payload_snapshot or {}
        team_id = snapshot.get("teamId") or ""
        player_id = snapshot.get("playerId") or ""
        reason = approval.reason or snapshot.get("reason") or ""
        try:
            result = _apply_force_kick(
                session=session,
                admin=admin,
                team_id=team_id,
                player_id=player_id,
                reason=reason,
                request=request,
                approval=approval,
            )
        except TeamAdminError as error:
            return _mark_execution_failed(
                session=session,
                actor=admin,
                approval=approval,
                error_code=error.code,
                request=request,
            )

        before_approval = _serialize_approval(approval)
        approval.status = APPROVAL_STATUS_EXECUTED
        approval.executed_by_admin_id = admin.id
        approval.executed_at = _now()
        approval.execution_result = {
            "status": "executed",
            "teamId": team_id,
            "playerId": player_id,
            "kicked": True,
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
            request=request,
        )
        return {"approval": after_approval, **result}
