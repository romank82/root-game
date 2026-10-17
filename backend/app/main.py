from __future__ import annotations

from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.db import SessionLocal
from app.mission_engine import (
    MissionEngineError,
    accept_mission,
    expire_mission,
    get_bootstrap as get_engine_bootstrap,
    get_mission_qr_payload,
    process_qr_scan,
    submit_mission,
)
from app.models import GamePlayer
from app.fallback_shop import get_fallback_offers, purchase_fallback_offer_entrypoint
from app.shop_service import list_catalog_items, purchase_catalog_item
from app.teams_service import (
    accept_invitation_entrypoint,
    approve_join_request_entrypoint,
    cancel_invitation_entrypoint,
    cancel_join_request_entrypoint,
    create_join_request_entrypoint,
    create_team_entrypoint,
    disband_team_entrypoint,
    get_my_invitations,
    get_my_join_requests,
    get_my_team,
    get_team,
    get_team_join_requests,
    invite_player_entrypoint,
    join_team_entrypoint,
    kick_member_entrypoint,
    leave_team_entrypoint,
    reject_invitation_entrypoint,
    reject_join_request_entrypoint,
    transfer_leadership_entrypoint,
    update_team_entrypoint,
)
from app.team_missions_service import (
    activate_session_entrypoint,
    create_team_session_entrypoint,
    list_my_team_sessions_entrypoint,
    mark_ready_entrypoint,
    submit_answer_entrypoint,
    submit_location_entrypoint,
)
from app.player_restrictions_engine import recompute_player_status
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.telegram_auth import (
    TelegramAuthError,
    create_session_token,
    normalize_telegram_username,
    verify_init_data,
    verify_session_token,
)
from app.admin_auth import (
    ADMIN_SESSION_COOKIE_NAME,
    authenticate_admin,
    get_current_admin,
    revoke_admin_session,
)
from app.admin_approvals import router as admin_approvals_router
from app.admin_management import router as admin_management_router
from app.admin_missions import router as admin_missions_router
from app.admin_segments import router as admin_segments_router
from app.admin_key_rules import router as admin_key_rules_router
from app.admin_reward_pools import router as admin_reward_pools_router
from app.admin_geo_zones import router as admin_geo_zones_router
from app.admin_ar_objects import router as admin_ar_objects_router
from app.admin_mission_runtime_policies import (
    router as admin_mission_runtime_policies_router,
    router_missions as admin_mission_runtime_policies_missions_router,
)
from app.admin_system_settings import router as admin_system_settings_router
from app.admin_players import router as admin_players_router
from app.admin_player_wallet import router as admin_player_wallet_router
from app.admin_player_inventory import router as admin_player_inventory_router
from app.admin_player_mission import router as admin_player_mission_router
from app.admin_player_restrictions import router as admin_player_restrictions_router
from app.admin_teams import router as admin_teams_router

SESSION_COOKIE_NAME = "chimera_session"

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(
    title="CHIMERA Protocol API",
    version="0.6.0",
    description="Backend API for the CHIMERA game.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """
    Create one server-side trace identifier per HTTP request.

    Incoming correlation headers are deliberately ignored: clients must not
    control an authoritative audit trace identifier.
    """
    correlation_id = uuid4().hex
    request.state.audit_context = {
        "correlation_id": correlation_id,
        # Do not trust X-Forwarded-For unless a separately configured trusted
        # reverse-proxy policy is introduced.
        "ip_address": request.client.host if request.client else None,
        "user_agent": (request.headers.get("user-agent") or "")[:512] or None,
    }

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


class MissionSubmitPayload(BaseModel):
    answer: str | None = None
    sequence: list[str] | None = None

class AcceptMissionPayload(BaseModel):
    latitude: float
    longitude: float
    accuracy: float | None = None

class ScanQrPayload(BaseModel):
    payload_and_hmac: str = Field(min_length=10, max_length=1000)

class TelegramAuthPayload(BaseModel):
    init_data: str = Field(
        min_length=1,
        max_length=8192,
        description="Original Telegram.WebApp.initData string.",
    )

class AdminAuthPayload(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12)

class TeamCreatePayload(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=10_000)
    emblem_url: str | None = Field(default=None, max_length=2048)
    join_policy: str = "by_request"
    max_members: int | None = Field(default=None, ge=1)

class TeamUpdatePayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=10_000)
    emblem_url: str | None = Field(default=None, max_length=2048)
    join_policy: str | None = None
    max_members: int | None = Field(default=None, ge=1)

class TransferLeadershipPayload(BaseModel):
    new_leader_id: str = Field(min_length=1, max_length=64)

class InvitePayload(BaseModel):
    invited_player_id: str = Field(min_length=1, max_length=64)
    message: str | None = Field(default=None, max_length=2000)
    ttl_hours: int | None = Field(default=None, ge=1)

class JoinRequestPayload(BaseModel):
    message: str | None = Field(default=None, max_length=2000)

class TeamSessionCreatePayload(BaseModel):
    mission_id: str = Field(min_length=1, max_length=64)

class TeamAnswerSubmitPayload(BaseModel):
    answer: str | None = Field(default=None, max_length=2000)

class LocationSubmitPayload(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(gt=0, le=100000)

def _new_player_id() -> str:
    return f"player-{uuid4().hex}"

def _upsert_telegram_player(
    telegram_id: str,
    first_name: str,
    last_name: str | None,
    username: str | None,
    photo_url: str | None,
) -> GamePlayer:
    """Find or create a profile by immutable Telegram user.id."""
    normalized_username = normalize_telegram_username(username)

    with SessionLocal.begin() as session:
        player = session.scalar(
            select(GamePlayer).where(
                GamePlayer.auth_provider == "telegram",
                GamePlayer.external_id == telegram_id,
            )
        )

        if player is None:
            if normalized_username:
                username_owner = session.scalar(
                    select(GamePlayer).where(
                        GamePlayer.telegram_username_normalized
                        == normalized_username
                    )
                )
                if username_owner is not None:
                    username_owner.telegram_username = None
                    username_owner.telegram_username_normalized = None

            player = GamePlayer(
                id=_new_player_id(),
                display_name=first_name,
                auth_provider="telegram",
                external_id=telegram_id,
                telegram_username=normalized_username,
                telegram_username_normalized=normalized_username,
                telegram_first_name=first_name,
                telegram_last_name=last_name,
                telegram_photo_url=photo_url,
                status="active",
            )
            session.add(player)
            session.flush()
        else:
            if (
                normalized_username
                and normalized_username != player.telegram_username_normalized
            ):
                username_owner = session.scalar(
                    select(GamePlayer).where(
                        GamePlayer.telegram_username_normalized
                        == normalized_username,
                        GamePlayer.id != player.id,
                    )
                )
                if username_owner is not None:
                    username_owner.telegram_username = None
                    username_owner.telegram_username_normalized = None

            player.display_name = first_name
            player.telegram_username = normalized_username
            player.telegram_username_normalized = normalized_username
            player.telegram_first_name = first_name
            player.telegram_last_name = last_name
            player.telegram_photo_url = photo_url

        if player.status != "active":
            # Lazy-рикавери (шаг 5.7): истёкшие/снятые ограничения не должны
            # навсегда запирать игрока вне входа. PlayerRestriction — источник
            # истины, GamePlayer.status — синхронизируемый кэш.
            recompute_player_status(session, player)
            if player.status != "active":
                raise HTTPException(
                    status_code=403,
                    detail="Игровой профиль неактивен.",
                )

        return player

def get_current_player_id(request: Request) -> str:
    """FastAPI dependency: resolve player identity from signed HttpOnly cookie."""
    try:
        player_id = verify_session_token(
            session_token=request.cookies.get(SESSION_COOKIE_NAME, ""),
            session_secret=settings.game_session_secret,
        )
    except TelegramAuthError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    with SessionLocal() as session:
        player = session.get(GamePlayer, player_id)

        if player is None:
            raise HTTPException(status_code=401, detail="Игрок не найден.")

        if player.status != "active":
            # Lazy-рикавери (шаг 5.7): устаревший кэш не должен запирать
            # игрока вне входа после снятия/expiry ограничений.
            recompute_player_status(session, player)
            # Обычная (не begin) сессия: синхронизацию кэша фиксируем явно.
            session.commit()
            if player.status != "active":
                raise HTTPException(
                    status_code=403,
                    detail="Игровой профиль неактивен.",
                )

    return player_id

@app.get("/")
def root():
    return {
        "service": "chimera-api",
        "version": "0.6.0",
        "docs": "/docs",
    }

@app.get("/health")
def health_check(request: Request):
    return {
        "status": "ok",
        "service": "chimera-api",
        "version": "0.6.0",
        "storage": "sqlalchemy",
        "environment": settings.app_env,
    }

@limiter.limit("5/minute")
@app.post("/api/v1/auth/telegram")
def authenticate_telegram(
    request: Request,
    payload: TelegramAuthPayload,
    response: Response,
):
    """
    Verify original Telegram.WebApp.initData and issue a signed HttpOnly cookie.
    Never accept a standalone user ID or initDataUnsafe from the browser.
    """
    try:
        telegram_user = verify_init_data(
            init_data=payload.init_data,
            bot_token=settings.telegram_bot_token,
            max_age_seconds=settings.telegram_initdata_max_age_seconds,
        )
        player = _upsert_telegram_player(
            telegram_id=telegram_user.telegram_id,
            first_name=telegram_user.first_name,
            last_name=telegram_user.last_name,
            username=telegram_user.username,
            photo_url=telegram_user.photo_url,
        )
    except TelegramAuthError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    except IntegrityError as error:
        raise HTTPException(
            status_code=409,
            detail=(
                "Не удалось синхронизировать Telegram-профиль. "
                "Повторите попытку."
            ),
        ) from error

    session_token = create_session_token(
        player_id=player.id,
        session_secret=settings.game_session_secret,
        lifetime_seconds=settings.game_session_lifetime_seconds,
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=settings.game_session_lifetime_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )

    return {
        "authenticated": True,
        "player": {
            "id": player.id,
            "displayName": player.display_name,
            "telegramUsername": player.telegram_username,
        },
    }

@limiter.limit("10/minute")
@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response):
    response.delete_cookie(
        key=SESSION_COOKIE_NAME,
        path="/",
        secure=settings.app_env == "production",
        httponly=True,
        samesite="lax",
    )
    return {"authenticated": False}

@limiter.limit("10/minute")
@app.get("/api/v1/engine/bootstrap")
def get_engine_bootstrap_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return get_engine_bootstrap(player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

@limiter.limit("10/minute")
@app.post("/api/v1/engine/missions/{mission_id}/submit")
def submit_engine_mission(
    request: Request,
    mission_id: str,
    payload: MissionSubmitPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return submit_mission(
            player_id=player_id,
            mission_id=mission_id,
            answer=payload.answer,
            sequence=payload.sequence,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/missions/{mission_id}/accept")
def accept_engine_mission(
    request: Request,
    mission_id: str,
    payload: AcceptMissionPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return accept_mission(
            player_id=player_id,
            mission_id=mission_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy=payload.accuracy,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/missions/{mission_id}/expire")
def expire_engine_mission(
    request: Request,
    mission_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return expire_mission(player_id, mission_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


# 8.6.c: подписанный QR-payload для миссии в in_progress. Read-only,
# секреты и validation_config не отдаются; чужой QR не пройдёт проверку,
# потому что player_id входит в подписанный body (скан — шаг 8.8).
@limiter.limit("10/minute")
@app.get("/api/v1/engine/missions/{mission_id}/qr-payload")
def get_engine_mission_qr_payload(
    request: Request,
    mission_id: str,
    player_id: str = Depends(get_current_player_id),
):
    """DEPRECATED (Sprint 8.13): не используется в solo-flow."""
    try:
        return get_mission_qr_payload(
            player_id=player_id,
            mission_id=mission_id,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


# 8.6.f: приём отсканированного "payload.hmac". Подпись проверяется в
# qr_service.verify_qr_payload (player_id и mission_id входят в подписанный
# body), факт сканирования сохраняется в PlayerMission.progress, ответ — mini-game.
@limiter.limit("30/minute")
@app.post("/api/v1/engine/missions/{mission_id}/scan-qr")
def scan_qr_route(
    request: Request,
    mission_id: str,
    payload: ScanQrPayload,
    player_id: str = Depends(get_current_player_id),
):
    """DEPRECATED (Sprint 8.13): не используется в solo-flow."""
    try:
        return process_qr_scan(
            player_id,
            mission_id,
            payload.payload_and_hmac,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.get("/api/v1/engine/fallback-offers")
def get_engine_fallback_offers_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return get_fallback_offers(player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


# 4.4: покупка fallback-ключа. Путевой параметр {offer_id} намеренно назван
# offer_id из-за исторического URL, но адресует именно player_fallback_entitlements.id
# (см. та же оговорка в GET): у одного игрока несколько entitlement'ов могут иметь
# одинаковый offer_id, поэтому уникальный адрес — entitlement.id.
@limiter.limit("10/minute")
@app.post("/api/v1/engine/fallback-offers/{offer_id}/purchases")
def purchase_fallback_offer_route(
    request: Request,
    offer_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return purchase_fallback_offer_entrypoint(player_id, offer_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


# ============================================================================
# Shop (Sprint 8.16) — общий каталог ключей (shop.catalog).
# ============================================================================

@limiter.limit("10/minute")
@app.get("/api/v1/engine/shop/items")
def get_shop_items_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Список published KEY items из общего каталога (без квоты)."""
    try:
        with SessionLocal.begin() as session:
            items = list_catalog_items(session, player_id)
        return {"items": items}
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/shop/items/{item_id}/purchases")
def purchase_shop_item_route(
    request: Request,
    item_id: str,
    player_id: str = Depends(get_current_player_id),
):
    """Купить ключ из каталога за ROOT (идемпотентная ledger-проводка)."""
    try:
        with SessionLocal.begin() as session:
            return purchase_catalog_item(session, player_id, item_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


# ============================================================================
# Teams (этап 6.4) — player-facing endpoints.
# Важно: GET /teams/me регистрируется ДО GET /teams/{team_id}, иначе FastAPI
# сопоставит «me» с {team_id}.
# ============================================================================

@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams", status_code=201)
def create_team_route(
    request: Request,
    payload: TeamCreatePayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return create_team_entrypoint(
            player_id,
            name=payload.name,
            description=payload.description,
            emblem_url=payload.emblem_url,
            join_policy=payload.join_policy,
            max_members=payload.max_members,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.get("/api/v1/engine/teams/me")
def get_my_team_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    try:
        team = get_my_team(player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    if team is None:
        raise HTTPException(status_code=404, detail="Вы не состоите в команде.")
    return team


@limiter.limit("10/minute")
@app.get("/api/v1/engine/teams/{team_id}")
def get_team_route(
    request: Request,
    team_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return get_team(team_id, requester_id=player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.patch("/api/v1/engine/teams/{team_id}")
def update_team_route(
    request: Request,
    team_id: str,
    payload: TeamUpdatePayload,
    player_id: str = Depends(get_current_player_id),
):
    changes: dict = {}
    if payload.name is not None:
        changes["name"] = payload.name
    if payload.description is not None:
        changes["description"] = payload.description
    if payload.emblem_url is not None:
        changes["emblem_url"] = payload.emblem_url
    if payload.join_policy is not None:
        changes["join_policy"] = payload.join_policy
    if payload.max_members is not None:
        changes["max_members"] = payload.max_members
    try:
        return update_team_entrypoint(player_id, team_id, **changes)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/{team_id}/join")
def join_team_route(
    request: Request,
    team_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return join_team_entrypoint(player_id, team_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/{team_id}/leave", status_code=204)
def leave_team_route(
    request: Request,
    team_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        leave_team_entrypoint(player_id, team_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return Response(status_code=204)


@limiter.limit("10/minute")
@app.post(
    "/api/v1/engine/teams/{team_id}/members/{target_player_id}/kick",
    status_code=204,
)
def kick_member_route(
    request: Request,
    team_id: str,
    target_player_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        kick_member_entrypoint(player_id, team_id, target_player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return Response(status_code=204)


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/{team_id}/transfer-leadership")
def transfer_leadership_route(
    request: Request,
    team_id: str,
    payload: TransferLeadershipPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        transfer_leadership_entrypoint(player_id, team_id, payload.new_leader_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return get_team(team_id, requester_id=player_id)


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/{team_id}/disband", status_code=204)
def disband_team_route(
    request: Request,
    team_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        disband_team_entrypoint(player_id, team_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return Response(status_code=204)


# ============================================================================
# Teams (этап 6.5) — приглашения и заявки (player-facing endpoints).
# Важно: GET /teams/invitations/me и GET /teams/join-requests/me
# регистрируются ДО остальных маршрутов этого блока, чтобы FastAPI не
# сопоставил «me» с {team_id} (та же ловушка, что была с /teams/me в 6.4).
# ============================================================================

@limiter.limit("10/minute")
@app.get("/api/v1/engine/teams/invitations/me")
def get_my_invitations_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return get_my_invitations(player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.get("/api/v1/engine/teams/join-requests/me")
def get_my_join_requests_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return get_my_join_requests(player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/{team_id}/invitations", status_code=201)
def invite_player_route(
    request: Request,
    team_id: str,
    payload: InvitePayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return invite_player_entrypoint(
            player_id,
            team_id,
            payload.invited_player_id,
            message=payload.message,
            ttl_hours=payload.ttl_hours,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/invitations/{invitation_id}/accept")
def accept_invitation_route(
    request: Request,
    invitation_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return accept_invitation_entrypoint(player_id, invitation_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/invitations/{invitation_id}/reject", status_code=204)
def reject_invitation_route(
    request: Request,
    invitation_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        reject_invitation_entrypoint(player_id, invitation_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return Response(status_code=204)


@limiter.limit("10/minute")
@app.delete(
    "/api/v1/engine/teams/{team_id}/invitations/{invitation_id}",
    status_code=204,
)
def cancel_invitation_route(
    request: Request,
    team_id: str,
    invitation_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        cancel_invitation_entrypoint(player_id, team_id, invitation_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return Response(status_code=204)


@limiter.limit("10/minute")
@app.post("/api/v1/engine/teams/{team_id}/join-requests", status_code=201)
def create_join_request_route(
    request: Request,
    team_id: str,
    payload: JoinRequestPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return create_join_request_entrypoint(
            player_id,
            team_id,
            message=payload.message,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.delete(
    "/api/v1/engine/teams/join-requests/{request_id}",
    status_code=204,
)
def cancel_join_request_route(
    request: Request,
    request_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        cancel_join_request_entrypoint(player_id, request_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return Response(status_code=204)


@limiter.limit("10/minute")
@app.get("/api/v1/engine/teams/{team_id}/join-requests")
def get_team_join_requests_route(
    request: Request,
    team_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return get_team_join_requests(player_id, team_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post(
    "/api/v1/engine/teams/{team_id}/join-requests/{request_id}/approve",
)
def approve_join_request_route(
    request: Request,
    team_id: str,
    request_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return approve_join_request_entrypoint(player_id, team_id, request_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post(
    "/api/v1/engine/teams/{team_id}/join-requests/{request_id}/reject",
    status_code=204,
)
def reject_join_request_route(
    request: Request,
    team_id: str,
    request_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        reject_join_request_entrypoint(player_id, team_id, request_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    return Response(status_code=204)


# ============================================================================
# Team missions (этап 7.1) — player-facing endpoints.
# /sessions/me регистрируется ДО любых /sessions/{id} (стандартная ловушка
# FastAPI: иначе «me» сопоставится с {id}).
# ============================================================================

@limiter.limit("10/minute")
@app.get("/api/v1/engine/team-missions/sessions/me")
def list_my_team_sessions_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    return list_my_team_sessions_entrypoint(player_id)


@limiter.limit("10/minute")
@app.post("/api/v1/engine/team-missions/sessions", status_code=201)
def create_team_session_route(
    request: Request,
    payload: TeamSessionCreatePayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return create_team_session_entrypoint(player_id, payload.mission_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/ready")
def mark_ready_route(
    request: Request,
    session_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return mark_ready_entrypoint(player_id, session_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/location")
def submit_location_route(
    request: Request,
    session_id: str,
    payload: LocationSubmitPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return submit_location_entrypoint(
            player_id=player_id,
            session_id=session_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy_meters=payload.accuracy_meters,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/activate")
def activate_session_route(
    request: Request,
    session_id: str,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return activate_session_entrypoint(player_id, session_id)

    except MissionEngineError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


@limiter.limit("10/minute")
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/submit")
def submit_answer_route(
    request: Request,
    session_id: str,
    payload: TeamAnswerSubmitPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return submit_answer_entrypoint(player_id, session_id, payload.answer)
    except MissionEngineError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


# ============================================================================
# Admin Panel Routes
# ============================================================================

@limiter.limit("10/minute")
@app.post("/api/v1/admin/auth/login")
def admin_login(
    request: Request,
    response: Response,
    payload: AdminAuthPayload,
):
    """Authenticate admin and issue HttpOnly session cookie."""
    try:
        raw_token = authenticate_admin(
            username=payload.username,
            password=payload.password,
            request=request,
        )
    except Exception as error:
        raise HTTPException(
            status_code=getattr(error, "status_code", 401),
            detail=getattr(error, "detail", "Ошибка аутентификации."),
        ) from error

    response.set_cookie(
        key=ADMIN_SESSION_COOKIE_NAME,
        value=raw_token,
        max_age=settings.admin_session_lifetime_seconds,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        path="/",
    )

    return {"authenticated": True}

@limiter.limit("30/minute")
@app.get("/api/v1/admin/auth/me")
def admin_me(request: Request):
    """Return the authenticated admin without exposing credentials or sessions."""
    try:
        admin = get_current_admin(
            request.cookies.get(ADMIN_SESSION_COOKIE_NAME, "")
        )
    except Exception as error:
        raise HTTPException(
            status_code=getattr(error, "status_code", 401),
            detail=getattr(error, "detail", "Требуется вход в админ-панель."),
        ) from error

    return {
        "authenticated": True,
        "admin": {
            "id": admin.id,
            "username": admin.username,
            # Legacy display field; authorization must use isSuperAdmin/permissions.
            "role": admin.role,
            "isSuperAdmin": admin.is_super_admin,
        },
    }


@limiter.limit("10/minute")
@app.post("/api/v1/admin/auth/logout")
def admin_logout(request: Request, response: Response):
    """Revoke admin session."""
    raw_token = request.cookies.get(ADMIN_SESSION_COOKIE_NAME, "")
    revoke_admin_session(
        raw_token=raw_token,
        request=request,
    )
    response.delete_cookie(
        key=ADMIN_SESSION_COOKIE_NAME,
        path="/",
        secure=settings.app_env == "production",
        httponly=True,
        samesite="lax",
    )
    return {"authenticated": False}

# Include administrative routers
app.include_router(admin_management_router)
app.include_router(admin_approvals_router)
app.include_router(admin_missions_router)
app.include_router(admin_segments_router)
app.include_router(admin_key_rules_router)
app.include_router(admin_reward_pools_router)
app.include_router(admin_geo_zones_router)
app.include_router(admin_ar_objects_router)
app.include_router(admin_mission_runtime_policies_router)
app.include_router(admin_mission_runtime_policies_missions_router)
app.include_router(admin_system_settings_router)
app.include_router(admin_players_router)
app.include_router(admin_player_wallet_router)
app.include_router(admin_player_inventory_router)
app.include_router(admin_player_mission_router)
app.include_router(admin_player_restrictions_router)
app.include_router(admin_teams_router)
