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
    get_bootstrap as get_engine_bootstrap,
    reset_demo_engine_progress,
    submit_mission,
)
from app.models import GamePlayer
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
    revoke_admin_session,
)
from app.admin_management import router as admin_management_router
from app.admin_missions import router as admin_missions_router

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

class MissionSubmitPayload(BaseModel):
    answer: str | None = None
    sequence: list[str] | None = None

class TelegramAuthPayload(BaseModel):
    init_data: str = Field(
        min_length=1,
        max_length=8192,
        description="Original Telegram.WebApp.initData string.",
    )

class AdminAuthPayload(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=12)

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

@limiter.limit("5/minute")
@app.post("/api/v1/engine/reset-demo-progress")
def reset_engine_demo_progress_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """
    Development-only test endpoint.

    Production intentionally does not expose a route capable of wiping a
    player's game state.
    """
    if settings.app_env == "production":
        raise HTTPException(status_code=404, detail="Not found.")

    try:
        return reset_demo_engine_progress(player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


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
            ip_address=request.client.host if request.client else None,
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

@limiter.limit("10/minute")
@app.post("/api/v1/admin/auth/logout")
def admin_logout(request: Request, response: Response):
    """Revoke admin session."""
    raw_token = request.cookies.get(ADMIN_SESSION_COOKIE_NAME, "")
    revoke_admin_session(
        raw_token=raw_token,
        ip_address=request.client.host if request.client else None,
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
app.include_router(admin_missions_router)
