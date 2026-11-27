from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.country_policy import is_blocked
from app.db import SessionLocal
from app.app_errors import record_app_error
from app.player_events import record_player_event
from app.mission_engine import (
    _new_id,
    MissionEngineError,
    accept_mission,
    expire_mission,
    get_bootstrap as get_engine_bootstrap,
    get_mission_qr_payload,
    process_qr_scan,
    submit_mission,
    submit_solo_location_proof_entrypoint,
)
from app.risk_service import (
    RiskError,
    resolve_state as resolve_risk_state,
    unlock_with_gas,
)
from app.models import GamePlayer, GasWallet, TonWallet
from app.fallback_shop import get_fallback_offers, purchase_fallback_offer_entrypoint
from app.shop_service import list_catalog_items, purchase_catalog_item
from app.referral_service import (
    DEFAULT_REFERRAL_REWARD_ROOT,
    NANO_PER_ROOT,
    REFERRAL_ENABLED_KEY,
    REFERRAL_REWARD_ROOT_KEY,
    TELEGRAM_BOT_USERNAME_KEY,
    _read_bool_setting,
    _read_int_setting,
    _read_string_setting,
    assign_referrer,
)
from app.slug_utils import generate_nickname
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
    join_team_session,
    last_terminal_team_session_entrypoint,
    leave_team_session,
    list_active_team_sessions_entrypoint,
    list_my_team_sessions_entrypoint,
    mark_ready_entrypoint,
    submit_location_entrypoint,
    submit_wave_answer_entrypoint,
)
from app.team_session_chat_service import (
    list_messages_entrypoint,
    send_message_entrypoint,
)
from app.transfer_service import transfer_root_entrypoint
from app.stars_service import (
    create_invoice_link,
    handle_pre_checkout_query,
    handle_successful_payment,
    send_gas_invoice,
)
from app.ton_service import validate_ton_address
from app.withdrawal_service import (
    create_withdrawal_request,
    list_player_withdrawals,
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
from app.admin_key_rules import router as admin_key_rules_router
from app.admin_reward_pools import router as admin_reward_pools_router
from app.admin_geo_zones import router as admin_geo_zones_router
from app.admin_ar_objects import router as admin_ar_objects_router
from app.admin_minigame_profiles import router as admin_minigame_profiles_router
from app.admin_seasons import router as admin_seasons_router
from app.admin_mission_runtime_policies import (
    router as admin_mission_runtime_policies_router,
    router_missions as admin_mission_runtime_policies_missions_router,
)
from app.admin_system_settings import router as admin_system_settings_router
from app.admin_players import (
    PlayerProfileUpdatePayload,
    VALID_GENDERS,
    router as admin_players_router,
)
from app.admin_player_wallet import router as admin_player_wallet_router
from app.admin_economy import router as admin_economy_router
from app.admin_player_inventory import router as admin_player_inventory_router
from app.admin_player_mission import router as admin_player_mission_router
from app.admin_player_restrictions import router as admin_player_restrictions_router
from app.admin_country_policies import router as admin_country_policies_router
from app.admin_monitoring import router as admin_monitoring_router
from app.admin_geo_audit import router as admin_geo_audit_router
from app.admin_withdrawals import router as admin_withdrawals_router
from app.admin_teams import router as admin_teams_router

SESSION_COOKIE_NAME = "chimera_session"

logger = logging.getLogger(__name__)

# Sprint 13.6: Sentry/GlitchTip. DSN пустой → полный no-op (игра работает как обычно).
# Инициализация должна быть ДО создания app, чтобы интеграции пропатчили middleware.
if settings.sentry_dsn:
    import sentry_sdk
    from sentry_sdk.integrations.starlette import StarletteIntegration
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment or None,
        release=settings.sentry_release or None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        send_default_pii=False,
        integrations=[
            StarletteIntegration(),
            FastApiIntegration(),
            # Логи не уходят в Sentry автоматически — только явный capture_exception.
            LoggingIntegration(level=None, event_level=None),
        ],
    )

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Retention 30 дней (Sprint DB-Audit-2): стартуем планировщик при
    # запуске приложения и останавливаем при его завершении. Сам планировщик
    # (BackgroundScheduler) запускает отдельный поток, поэтому здесь нет
    # блокирующего I/O.
    from app.retention import start_scheduler, stop_scheduler

    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(
    title="CHIMERA Protocol API",
    version="0.6.0",
    description="Backend API for the CHIMERA game.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Correlation-ID"],
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.middleware("http")
async def app_errors_middleware(request: Request, call_next):
    """13.4-b: необработанные 5xx пишем в app_errors и пробрасываем.

    4xx (HTTPException) — не логируем (raise). Исключения миссий endpoint'ы
    уже конвертируют в HTTPException — сюда такие не долетают. Запись — в
    отдельной короткой транзакции: сбой журнала не должен маскировать
    исходную ошибку (паттерн auth.login, 13.3). Зарегистрирован ДО
    correlation_id_middleware: в стеке Starlette (LIFO add_middleware) он
    остаётся ВНУТРЕННИМ слоем, поэтому audit_context (correlation_id) уже
    установлен внешним correlation_id_middleware.
    """
    try:
        return await call_next(request)
    except HTTPException:
        raise  # 4xx — не логируем
    except Exception as exc:  # noqa: BLE001 — необработанный 5xx
        correlation_id = (
            getattr(getattr(request, "state", None), "audit_context", {}).get(
                "correlation_id"
            )
            or uuid4().hex
        )
        endpoint = request.url.path
        player_id = getattr(
            getattr(request, "state", None), "audit_context", {}
        ).get("player_id")
        try:
            with SessionLocal.begin() as session:
                record_app_error(
                    session,
                    correlation_id=correlation_id,
                    severity="error",
                    error_type=type(exc).__name__,
                    # A12: message/stack НЕ сохраняем. str(exc) и traceback
                    # могут содержать внутренние URL, SQL-фрагменты и
                    # секреты. Полный контекст ошибки уходит только в Sentry
                    # (ниже); в БД остаются тип, endpoint, correlation_id,
                    # status_code и player_id. AppError.message NOT NULL —
                    # пишем пустую строку (миграция для default — отдельно).
                    message="",
                    safe_context={
                        "method": request.method,
                    },
                    endpoint=endpoint,
                    status_code=500,
                    player_id=player_id,
                    stack=None,
                )
            # Sprint 13.6: явный capture_exception, т.к. кастомный handler(Exception)
            # перехватывает 500 и не пробрасывает exc наружу (Sentry сам не увидит).
            if settings.sentry_dsn:
                import sentry_sdk

                with sentry_sdk.push_scope() as scope:
                    scope.set_tag("correlation_id", correlation_id)
                    scope.set_tag("endpoint", endpoint)
                    if player_id:
                        scope.set_tag("player_id", str(player_id))
                    sentry_sdk.capture_exception(exc)
            # В обычный лог — без текста исключения (A12): только тип и
            # correlation_id, чтобы связать с Sentry/app_errors.
            logger.warning(
                "unhandled 500 at %s: %s (correlation %s)",
                endpoint,
                type(exc).__name__,
                correlation_id,
            )
        except Exception as log_error:  # noqa: BLE001 — лог не важнее ответа
            logger.warning("app_error record failed: %s", log_error)
        raise


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    """
    Create one server-side trace identifier per HTTP request.

    Incoming correlation headers are deliberately ignored: clients must not
    control an authoritative audit trace identifier.
    """
    correlation_id = uuid4().hex

    # M-2c: player_id из подписанной cookie — для журнала ошибок и аудита.
    # verify_session_token без побочных эффектов (HMAC, без БД/commit/raise):
    # при отсутствии/невалидности cookie player_id = None.
    player_id = None
    session_token = request.cookies.get(SESSION_COOKIE_NAME, "")
    if session_token:
        try:
            player_id = verify_session_token(
                session_token=session_token,
                session_secret=settings.game_session_secret,
            )
        except TelegramAuthError:
            player_id = None

    request.state.audit_context = {
        "correlation_id": correlation_id,
        # Do not trust X-Forwarded-For unless a separately configured trusted
        # reverse-proxy policy is introduced.
        "ip_address": request.client.host if request.client else None,
        "user_agent": (request.headers.get("user-agent") or "")[:512] or None,
        "player_id": player_id,
    }

    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


def _correlation_id_of(request: Request) -> str | None:
    """Достать correlation_id из request.state.audit_context (E-0.1).

    Устанавливается correlation_id_middleware ДО обработчиков ошибок, поэтому
    здесь он всегда доступен; fallback на None нужен лишь для запросов,
    которые по какой-то причине миновали middleware.
    """
    return (
        getattr(getattr(request, "state", None), "audit_context", {}).get(
            "correlation_id"
        )
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
):
    """422 (Pydantic) — не отдавать массив, отдать русскую строку + correlation_id."""
    correlation_id = _correlation_id_of(request)
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Проверьте введённые данные.",
            "correlation_id": correlation_id,
        },
        headers={"X-Correlation-ID": correlation_id} if correlation_id else None,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """4xx/5xx от HTTPException — русские дефолтные строки + correlation_id.

    Зарегистрирован на starlette.exceptions.HTTPException, а не на
    fastapi.HTTPException: именно starlette-вариант бросает роутер для
    дефолтных 404 «Not Found» / 405 «Method Not Allowed». fastapi.HTTPException
    — его подкласс, поэтому оба случая покрываются одним handler'ом.

    Кастомные русские detail (MissionEngineError → «Недостаточно ROOT» и др.)
    проходят как есть — не ломаем существующие тексты игровых endpoint'ов.
    """
    correlation_id = _correlation_id_of(request)
    detail = exc.detail
    if isinstance(detail, (list, dict)):
        detail = "Проверьте введённые данные."
    if detail == "Not Found":
        detail = "Не найдено."
    elif detail == "Method Not Allowed":
        detail = "Действие недоступно."
    elif detail == "Internal Server Error":
        detail = "Сервер занят. Попробуйте ещё раз."
    # Сохраняем заголовки исходного исключения (например, Retry-After), если они есть.
    headers = dict(exc.headers) if exc.headers else {}
    if correlation_id:
        headers["X-Correlation-ID"] = correlation_id
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": detail, "correlation_id": correlation_id},
        headers=headers or None,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Необработанный 500 — русский текст + correlation_id в теле.

    Логирование в AppError выполняет app_errors_middleware (13.4-b) ДО этого
    handler'а (middleware стоит над exception handlers), поэтому здесь запись
    НЕ дублируется — только формируем ответ игроку.
    """
    correlation_id = _correlation_id_of(request)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Сервер занят. Попробуйте ещё раз.",
            "correlation_id": correlation_id,
        },
        headers={"X-Correlation-ID": correlation_id} if correlation_id else None,
    )


class MissionSubmitPayload(BaseModel):
    answer: str | None = None
    sequence: list[str] | None = None

class AcceptMissionPayload(BaseModel):
    latitude: float
    longitude: float
    accuracy: float | None = None

class TransferPayload(BaseModel):
    """POST /api/v1/players/transfer (10.1-b).

    Sprint 8.x-fractional-transfer (шаг A1): additive-приём ``amount_nano``
    (целое наноROOT, 1 ROOT = 10^8). Старый ``amount`` (целый ROOT) работает
    как раньше — достаточно передать ровно одно из двух полей. Если пришли
    оба, приоритет у ``amount_nano`` (решение в transfer_service).
    """
    to_player_id: str = Field(..., min_length=1)
    amount: int | None = Field(default=None, gt=0)
    amount_nano: int | None = Field(default=None, gt=0)
    request_id: str = Field(..., min_length=1, max_length=64)

    @model_validator(mode="after")
    def _require_amount(self) -> "TransferPayload":
        """Хотя бы одна сумма: amount (ROOT) или amount_nano (наноROOT)."""
        if self.amount is None and self.amount_nano is None:
            raise ValueError("amount or amount_nano required")
        return self

class TonWalletPayload(BaseModel):
    """POST /api/v1/me/ton-wallet (11.0-a): сохранение TON-адреса игрока."""
    model_config = ConfigDict(extra="forbid")
    address: str = Field(..., min_length=1, max_length=128)

class WithdrawalPayload(BaseModel):
    """POST /api/v1/me/withdrawals (11.5-a): заявка на вывод ROOT в TON."""
    model_config = ConfigDict(extra="forbid")
    amount_root: int = Field(..., gt=0)
    to_address: str = Field(..., min_length=1, max_length=128)
    # A10: client idempotency key. Повторный POST с тем же request_id
    # возвращает уже созданную заявку (без второго списания ROOT).
    request_id: str = Field(..., min_length=1, max_length=64)

class GasInvoicePayload(BaseModel):
    """POST /api/v1/engine/gas/invoice (10.4-j-0)."""
    gas_amount: int = Field(..., gt=0)

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
    """POST /api/v1/engine/team-missions/sessions (create).

    Sprint 8.x-4-join-proximity: GPS обязателен — по нему определяется
    страна/город создателя и проверяется «рядом» при вступлении.
    """

    mission_id: str = Field(min_length=1, max_length=64)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, gt=0, le=100000)


class TeamSessionJoinPayload(BaseModel):
    """POST /api/v1/engine/team-missions/sessions/{id}/join.

    Sprint 8.x-4-join-proximity: GPS обязателен — до списания entry fee
    проверяются «одна страна» и «рядом ≤ 50 км до всех участников».
    """

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, gt=0, le=100000)

class LocationSubmitPayload(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy_meters: float = Field(gt=0, le=100000)

class TeamWaveSubmitPayload(BaseModel):
    sequence: list[str] | None = Field(default=None, max_length=32)

class TeamSessionMessagePayload(BaseModel):
    """POST /api/v1/engine/team-missions/sessions/{id}/messages (6.6-a)."""
    text: str = Field(min_length=1, max_length=1000)


# --- A3: Pydantic-схемы поддерживаемых Telegram update types ----------------
# extra="ignore": Telegram присылает много полей (from/chat/date/…), которые
# webhook не использует. Обязательными помечены только те поля, которые
# реально читают обработчики stars_service — неполный payload отклоняется 400.
class TelegramUser(BaseModel):
    """Подмножество Telegram User, нужное webhook."""

    model_config = ConfigDict(extra="ignore")

    id: int
    first_name: str | None = None
    username: str | None = None


class PreCheckoutQuery(BaseModel):
    """pre_checkout_query: поля, которые читает stars_service."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = Field(..., min_length=1)
    # В Telegram поле называется "from".
    from_user: TelegramUser | None = Field(default=None, alias="from")
    currency: str | None = None
    total_amount: int | None = None
    invoice_payload: str = Field(..., min_length=1)


class PreCheckoutQueryUpdate(BaseModel):
    """Update с pre_checkout_query (валидируется A3)."""

    model_config = ConfigDict(extra="ignore")

    update_id: int | None = None
    pre_checkout_query: PreCheckoutQuery


class SuccessfulPayment(BaseModel):
    """successful_payment: поля, которые читает stars_service."""

    model_config = ConfigDict(extra="ignore")

    currency: str | None = None
    total_amount: int | None = None
    invoice_payload: str = Field(..., min_length=1)
    telegram_payment_charge_id: str = Field(..., min_length=1)
    provider_payment_charge_id: str | None = None


class TelegramMessage(BaseModel):
    """Сообщение Telegram с успешным платежом."""

    model_config = ConfigDict(extra="ignore")

    message_id: int | None = None
    successful_payment: SuccessfulPayment | None = None


class SuccessfulPaymentUpdate(BaseModel):
    """Update с message.successful_payment (валидируется A3)."""

    model_config = ConfigDict(extra="ignore")

    update_id: int | None = None
    message: TelegramMessage


def _new_player_id() -> str:
    return f"player-{uuid4().hex}"

def _upsert_telegram_player(
    telegram_id: str,
    first_name: str,
    last_name: str | None,
    username: str | None,
    photo_url: str | None,
    start_param: str | None = None,
) -> GamePlayer:
    """Find or create a profile by immutable Telegram user.id.

    start_param — подписанный Telegram ``start_param`` из initData
    (``ref_<player_id>``). Учитывается ТОЛЬКО при создании нового профиля:
    уже существующий игрок никогда не переатрибутируется другому рефереру.
    Значение приходит только из verify_init_data (покрыто подписью), из тела
    запроса его не принимаем.
    """
    normalized_username = normalize_telegram_username(username)

    with SessionLocal.begin() as session:
        def _nickname_is_taken(candidate_lower: str) -> bool:
            """Занят ли ник (по nickname_lower) в текущей транзакции."""
            return (
                session.scalar(
                    select(GamePlayer.id).where(
                        GamePlayer.nickname_lower == candidate_lower.lower()
                    )
                )
                is not None
            )

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

            nickname = generate_nickname(
                first_name or "player", _nickname_is_taken
            )
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
                nickname=nickname,
                nickname_lower=nickname.lower(),
                status="active",
            )
            session.add(player)
            session.flush()

            # Referral-5: привязка пригласившего — только для нового профиля,
            # в той же транзакции регистрации. assign_referrer возвращает None
            # вместо исключений (плохой ref_/нет реферера/повтор), поэтому
            # вход игрока не ломается никогда.
            if start_param:
                assign_referrer(session, player.id, start_param)
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

            if player.nickname is None:
                # Генерация ника для старых записей без ника (пред-34-B2;
                # backfill-миграция 884a02f1a72d уже покрыла существующие на
                # момент миграции записи, это страховка для созданных после).
                # Уже присвоенный ник НЕ перезаписываем: игроки получают его
                # один раз и больше не меняют (10.0, ник immutable).
                nickname = generate_nickname(
                    first_name or "player", _nickname_is_taken
                )
                player.nickname = nickname
                player.nickname_lower = nickname.lower()

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

        # 13.7-b: последний визит — при каждом запросе игрока, включая
        # неактивных (зашёл — значит, был онлайн). Без throttle (пока).
        # Обычная (не begin) сессия: изменение фиксируем явно.
        player.last_seen_at = datetime.now(timezone.utc)
        session.commit()

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

        # 13.2-b-1: блокировка по стране (blocked → 403; NULL → пропуск).
        # Проверка после last_seen_at и status-рикавери (та же сессия):
        # визит зафиксирован, но доступ из blocked-страны запрещён.
        if is_blocked(session, player.country):
            raise HTTPException(
                status_code=403,
                detail="Доступ из вашей страны ограничен.",
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
    # Окружение наружу не отдаём: /health открыт без авторизации и не должен
    # подсказывать, что за сервис и в каком режиме работает (аудит, F-06).
    return {
        "status": "ok",
        "service": "chimera-api",
        "version": "0.6.0",
        "storage": "sqlalchemy",
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
            # Referral-5: атрибуция реферера — только из подписанного initData
            # (verified.start_param), не из тела запроса.
            start_param=telegram_user.start_param,
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

    # 13.3-b-1: лог auth.login (PlayerEvent, модерация/антифрод/аналитика).
    # Успешный вход уже зафиксирован: _upsert_telegram_player открывает и
    # коммитит свою транзакцию самостоятельно, поэтому открытой сессии здесь
    # нет и событие пишется в отдельной короткой транзакции (rollback при
    # ошибке — за счёт контекстного менеджера, т.е. журнал не трогает уже
    # закоммиченный апсерт игрока). Логин важнее лога: любая ошибка журнала
    # НЕ должна ломать вход — только logger.warning.
    try:
        correlation_id = getattr(
            getattr(request, "state", None), "audit_context", {}
        ).get("correlation_id")
        with SessionLocal.begin() as session:
            record_player_event(
                session,
                player.id,
                "auth.login",
                payload={"authProvider": "telegram"},
                correlation_id=correlation_id,
            )
    except Exception as error:  # noqa: BLE001 — лог не важнее входа
        logger.warning("player_event auth.login failed: %s", error)

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
    lang: str = Query("ru", max_length=8),
):
    try:
        bootstrap = get_engine_bootstrap(player_id, lang=lang)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error
    # 10.4-j-0: баланс газа для фронта. GasWallet может отсутствовать
    # (игрок ещё не покупал газ) -> "0". Строка: дробный Numeric(18,4).
    with SessionLocal() as session:
        gas_wallet = session.scalar(
            select(GasWallet).where(GasWallet.player_id == player_id)
        )
    bootstrap["gasBalance"] = (
        str(gas_wallet.balance) if gas_wallet is not None else "0"
    )
    return bootstrap


@app.get("/api/v1/engine/me/profile")
def get_my_profile_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Мой профиль (10.0.6-a): чтение country/gender/age."""
    with SessionLocal() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(status_code=404, detail="Игрок не найден.")
        return {
            "player": {
                "id": player.id,
                "nickname": player.nickname,
                "country": player.country,
                "country_source": player.country_source,
                "gender": player.gender,
                "age": player.age,
            }
        }


@app.get("/api/v1/engine/me/referral")
def get_my_referral_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Моя рефералка (Sprint Referral R-5): флаг, награда, share-ссылка.

    Только чтение: enabled/rewardRoot берутся из CMS (system_settings, с
    фолбэком на каталог), shareLink собирается из имени бота — CMS-first
    (``telegram.bot_username``) с фолбэком на env ``TELEGRAM_BOT_USERNAME``;
    фронт имя бота не знает и не хардкодит.
    referredBy — кто пригласил игрока (None, если без реферальной ссылки).
    """
    with SessionLocal() as session:
        enabled = _read_bool_setting(session, REFERRAL_ENABLED_KEY, False)
        reward_root = _read_int_setting(
            session, REFERRAL_REWARD_ROOT_KEY, DEFAULT_REFERRAL_REWARD_ROOT
        )
        player = session.get(GamePlayer, player_id)
        # Sprint 8.x-ref-link-cms: CMS-first, фолбэк на env. Читаем внутри
        # сессии — вне её ORM-запрос к system_settings уже не выполнить.
        cms_bot_username = _read_string_setting(
            session, TELEGRAM_BOT_USERNAME_KEY, ""
        )
        bot_username = (
            cms_bot_username or settings.telegram_bot_username
        ).strip()
        # Нормализация: username в Telegram без @, админ может ввести с ним.
        if bot_username.startswith("@"):
            bot_username = bot_username[1:].strip()

    share_link = (
        f"https://t.me/{bot_username}?start=ref_{player_id}"
        if bot_username
        else None
    )

    return {
        "enabled": enabled,
        "rewardRoot": reward_root,
        # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
        "rewardRootNano": reward_root * NANO_PER_ROOT,
        "shareLink": share_link,
        "referredBy": (
            player.referred_by_player_id if player is not None else None
        ),
    }


@app.patch("/api/v1/engine/me/profile")
def update_my_profile_route(
    request: Request,
    payload: PlayerProfileUpdatePayload,
    player_id: str = Depends(get_current_player_id),
):
    """Моя анкета (10.0.6-a): корректировка country/gender/age (без админ-аудита)."""
    updates = payload.model_dump(exclude_unset=True)

    if not updates:
        raise HTTPException(
            status_code=422,
            detail="Передайте хотя бы одно поле для изменения.",
        )

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise HTTPException(status_code=404, detail="Игрок не найден.")

        if "country" in updates:
            # 10.0.5-b: при 'auto' блокировка до валидации country —
            # 422 про автоблокировку независимо от payload.
            if player.country_source == "auto":
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "Страна определена автоматически по координатам и не "
                        "может быть изменена в анкете."
                    ),
                )
            value = updates["country"]
            if value is not None:
                value = value.strip().upper()
                if len(value) != 2 or not value.isalpha():
                    raise HTTPException(
                        status_code=422,
                        detail="country должен быть ISO-2 (2 буквы).",
                    )
            player.country = value
            player.country_source = "manual"

        if "gender" in updates:
            value = updates["gender"]
            if value is not None and value not in VALID_GENDERS:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "gender должен быть одним из: "
                        f"{', '.join(sorted(VALID_GENDERS))}."
                    ),
                )
            player.gender = value

        if "age" in updates:
            player.age = updates["age"]

        session.commit()

        return {
            "player": {
                "id": player.id,
                "nickname": player.nickname,
                "country": player.country,
                "country_source": player.country_source,
                "gender": player.gender,
                "age": player.age,
            }
        }


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


# Sprint 8.5-2: solo location proof. Гейта нет (8.5-2b); создаёт LocationProof
# и возвращает {missionId, zoneId, verified, expiresAt}.
@limiter.limit("10/minute")
@app.post("/api/v1/engine/missions/{mission_id}/location-proof")
def submit_solo_location_proof_route(
    request: Request,
    mission_id: str,
    payload: LocationSubmitPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return submit_solo_location_proof_entrypoint(
            player_id=player_id,
            mission_id=mission_id,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy_meters=payload.accuracy_meters,
            request=request,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/players/transfer")
def transfer_root_route(
    request: Request,
    payload: TransferPayload,
    player_id: str = Depends(get_current_player_id),
):
    """Перевод ROOT другому игроку (10.1+). Идемпотентность — request_id."""
    try:
        return transfer_root_entrypoint(
            from_player_id=player_id,
            to_player_id=payload.to_player_id,
            amount=payload.amount,
            request_id=payload.request_id,
            amount_nano=payload.amount_nano,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.get("/api/v1/me/ton-wallet")
def get_my_ton_wallet_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Мой активный TON-адрес (11.0-a): {address, status} или null."""
    with SessionLocal() as session:
        wallet = session.scalar(
            select(TonWallet).where(
                TonWallet.player_id == player_id,
                TonWallet.status == "active",
            )
        )
    if wallet is None:
        return {"address": None, "status": None}
    return {"address": wallet.address, "status": wallet.status}


@limiter.limit("10/minute")
@app.post("/api/v1/me/ton-wallet")
def save_my_ton_wallet_route(
    request: Request,
    payload: TonWalletPayload,
    player_id: str = Depends(get_current_player_id),
):
    """Сохранить/заменить мой TON-адрес (11.0-a) — upsert одной строки.

    TonWallet имеет unique(player_id) и unique(address) в схеме, поэтому
    вторая строка для игрока невозможна (models/migration не меняются).
    Upsert: если строка уже есть — обновляем address и status='active',
    иначе создаём. История адресов не хранится (одна строка на игрока).
    Валидация TON-адреса — pytoniq (ton_service.validate_ton_address,
    422 на невалид).
    """
    try:
        normalized = validate_ton_address(payload.address)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error

    with SessionLocal.begin() as session:
        wallet = session.scalar(
            select(TonWallet).where(TonWallet.player_id == player_id)
        )
        if wallet is None:
            wallet = TonWallet(
                id=_new_id("ton-wallet"),
                player_id=player_id,
                address=normalized,
                status="active",
            )
            session.add(wallet)
        else:
            wallet.address = normalized
            wallet.status = "active"
        session.flush()
        return {"address": normalized, "status": "active"}


@limiter.limit("10/minute")
@app.delete("/api/v1/me/ton-wallet")
def delete_my_ton_wallet_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Удалить мой TON-адрес (11.0-a): активный помечается 'removed'."""
    with SessionLocal.begin() as session:
        wallet = session.scalar(
            select(TonWallet).where(
                TonWallet.player_id == player_id,
                TonWallet.status == "active",
            )
        )
        if wallet is None:
            raise HTTPException(status_code=404, detail="TON-кошелёк не найден.")
        wallet.status = "removed"
        session.flush()
        return {"deleted": True}


@limiter.limit("10/minute")
@app.post("/api/v1/me/withdrawals")
def create_my_withdrawal_route(
    request: Request,
    payload: WithdrawalPayload,
    player_id: str = Depends(get_current_player_id),
):
    """Подать заявку на вывод ROOT → TON (11.5-a).

    ROOT списывается сразу в холд (immutable-проводка withdrawal_hold);
    возвращает {withdrawalId, amountRoot, toAddress, status:"pending"}.
    requestId — обязательный idempotency key (повтор не создаёт дубль).
    Валидации и коды ошибок — в withdrawal_service.create_withdrawal_request.
    """
    try:
        return create_withdrawal_request(
            player_id,
            payload.amount_root,
            payload.to_address,
            payload.request_id,
        )
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.get("/api/v1/me/withdrawals")
def list_my_withdrawals_route(
    request: Request,
    limit: int = 50,
    offset: int = 0,
    player_id: str = Depends(get_current_player_id),
) -> dict:
    """Список заявок игрока (11.7-a): свои, новее сверху.

    {withdrawals: [...], total, limit, offset}. Поля — только игровые
    (withdrawalId/amountRoot/toAddress/status/tonTxHash/reason/createdAt/
    updatedAt), без id/playerId/batchId/adminId. Read-only, без мутаций.
    """
    try:
        return list_player_withdrawals(player_id, limit, offset)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/gas/invoice")
def create_gas_invoice_route(
    request: Request,
    payload: GasInvoicePayload,
    player_id: str = Depends(get_current_player_id),
):
    """Создать инвойс Stars на покупку газа (10.4-j-0)."""
    try:
        return create_invoice_link(player_id, payload.gas_amount)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/gas/invoice/send")
def send_gas_invoice_route(
    request: Request,
    payload: GasInvoicePayload,
    player_id: str = Depends(get_current_player_id),
):
    """Отправить инвойс Stars в чат с ботом (10.4-fix, sendInvoice)."""
    try:
        return send_gas_invoice(player_id, payload.gas_amount)
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


@limiter.limit("20/minute")
@app.get("/api/v1/risk/state")
def get_risk_state_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Состояние раздела «Риск» для игрока (docs/risk-section-contract.md).

    state: hidden — раздел скрыт; locked — виден, требует оплаты газом;
    unlocked — доступен. Стоимость и баланс газа отдаются строками, потому
    что газ — Numeric(18,4).
    """
    with SessionLocal() as session:
        return resolve_risk_state(session, player_id)


@limiter.limit("5/minute")
@app.post("/api/v1/risk/unlock")
def post_risk_unlock_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Разовая оплата газом: постоянный доступ к разделу «Риск».

    Атомарно списывает газ immutable-проводкой GasTransaction
    (reference_type='risk_unlock') и создаёт запись постоянного доступа.
    Повторный вызов после успеха газ не двигает.
    """
    try:
        with SessionLocal.begin() as session:
            return unlock_with_gas(session, player_id)
    except RiskError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


def _serialize_player_for_search(player: GamePlayer) -> dict[str, str | None]:
    """Минимальная публичная карточка для поиска игроков (10.0.1).

    Намеренно НЕ отдаём display_name/telegram_*/auth_provider/external_id/
    balance/status/age/gender/country_source — лишние private data.
    """
    return {
        "id": player.id,
        "nickname": player.nickname,
        "country": player.country,
    }


# 10.0.1: игровой поиск игроков по нику (для переводов 10.1+).
# Минимум полей в выдаче, q >= 3 символа, только status='active',
# сам игрок в выдачу не попадает. rate limit — как у соседних ручек.
@limiter.limit("10/minute")
@app.get("/api/v1/players/search")
def search_players_route(
    request: Request,
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=50),
    player_id: str = Depends(get_current_player_id),
):
    """Поиск игроков по нику (ilike по nickname_lower), публичная выдача."""
    query = (q or "").strip()
    if len(query) < 3:
        raise HTTPException(
            status_code=422,
            detail="Введите минимум 3 символа для поиска.",
        )

    pattern = f"%{query.lower()}%"
    conditions = [
        GamePlayer.nickname_lower.ilike(pattern),
        GamePlayer.status == "active",
        GamePlayer.id != player_id,
    ]

    with SessionLocal() as session:  # read-only, не begin()
        total = session.scalar(
            select(func.count())
            .select_from(GamePlayer)
            .where(*conditions)
        ) or 0
        rows = session.execute(
            select(GamePlayer)
            .where(*conditions)
            .order_by(GamePlayer.nickname_lower)
            .limit(limit)
        ).scalars()
        players = [_serialize_player_for_search(player) for player in rows]

    return {
        "players": players,
        "total": total,
        "limit": limit,
    }


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
@app.get("/api/v1/engine/team-missions/sessions/last")
def last_team_session_route(
    request: Request,
    player_id: str = Depends(get_current_player_id),
):
    """Последняя терминальная сессия игрока (succeeded/failed) + его награды.

    Sprint 8.x-4-final-status-2: регистрируется ПОСЛЕ /sessions/me и ДО любых
    будущих /sessions/{id} (правило main.py:1508), чтобы «last» не
    сопоставилось с {id}. GET /sessions/{id} сейчас нет — безопасно.
    """
    try:
        return last_terminal_team_session_entrypoint(player_id)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.get("/api/v1/engine/team-missions/sessions/active")
def list_active_team_sessions_route(
    request: Request,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    player_id: str = Depends(get_current_player_id),
):
    """Чужие лобби «Активные»: свободные места, одна страна, «рядом» ≤ 50 км.

    Sprint 8.x-4-join-gps: GPS игрока — query-параметрами (в БД не пишется;
    по нему считаются страна и максимальное расстояние до участников).
    Регистрируется ПОСЛЕ /sessions/me и /sessions/last и ДО любых будущих
    GET /sessions/{id}, чтобы «active» не сопоставилось с {id}.
    """
    try:
        return list_active_team_sessions_entrypoint(player_id, latitude, longitude)
    except MissionEngineError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail=error.detail,
        ) from error


@limiter.limit("10/minute")
@app.post("/api/v1/engine/team-missions/sessions", status_code=201)
def create_team_session_route(
    request: Request,
    payload: TeamSessionCreatePayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return create_team_session_entrypoint(
            player_id,
            payload.mission_id,
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
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/join")
def join_team_session_route(
    request: Request,
    session_id: str,
    payload: TeamSessionJoinPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return join_team_session(
            player_id,
            session_id,
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
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/leave")
def leave_team_session_route(
    request: Request,
    session_id: str,
    player_id: str = Depends(get_current_player_id),
):
    """Выйти из командной сессии в сборе; возвращает {left, refunded}."""
    try:
        return leave_team_session(player_id, session_id)
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
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/submit-wave")
def submit_wave_route(
    request: Request,
    session_id: str,
    payload: TeamWaveSubmitPayload,
    player_id: str = Depends(get_current_player_id),
):
    try:
        return submit_wave_answer_entrypoint(
            player_id, session_id, payload.sequence
        )
    except MissionEngineError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


@limiter.limit("10/minute")
@app.get("/api/v1/engine/team-missions/sessions/{session_id}/messages")
def list_session_messages_route(
    request: Request,
    session_id: str,
    limit: int = 50,
    before: str | None = None,
    player_id: str = Depends(get_current_player_id),
):
    """Чат сессии (6.6-a): только участники, только пока сессия активна."""
    try:
        return list_messages_entrypoint(player_id, session_id, limit, before)
    except MissionEngineError as error:
        raise HTTPException(status_code=error.status_code, detail=error.detail)


@limiter.limit("10/minute")
@app.post("/api/v1/engine/team-missions/sessions/{session_id}/messages")
def send_session_message_route(
    request: Request,
    session_id: str,
    payload: TeamSessionMessagePayload,
    player_id: str = Depends(get_current_player_id),
):
    """Отправка сообщения в чат сессии (6.6-a)."""
    try:
        return send_message_entrypoint(player_id, session_id, payload.text)
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
app.include_router(admin_key_rules_router)
app.include_router(admin_reward_pools_router)
app.include_router(admin_geo_zones_router)
app.include_router(admin_ar_objects_router)
app.include_router(admin_minigame_profiles_router)
app.include_router(admin_seasons_router)
app.include_router(admin_mission_runtime_policies_router)
app.include_router(admin_mission_runtime_policies_missions_router)
app.include_router(admin_system_settings_router)
app.include_router(admin_players_router)
app.include_router(admin_player_wallet_router)
app.include_router(admin_economy_router)
app.include_router(admin_player_inventory_router)
app.include_router(admin_player_mission_router)
app.include_router(admin_player_restrictions_router)
app.include_router(admin_country_policies_router)
app.include_router(admin_monitoring_router)
app.include_router(admin_geo_audit_router)
app.include_router(admin_withdrawals_router)
app.include_router(admin_teams_router)


# ============================================================================
# 10.4-h: Telegram webhook — покупка газа за Stars.
# Без Depends(get_current_player_id) и без @limiter.limit: Telegram не шлёт
# нашу сессионную куку и не является игроком. Защита — секрет в заголовке
# X-Telegram-Bot-Api-Secret-Token (пустой TELEGRAM_WEBHOOK_SECRET — dev-режим
# без проверки, см. config.py).
# ============================================================================
@app.post("/webhook/telegram")
def telegram_webhook(request: Request, update: dict):
    """Обработка Telegram-обновлений: pre_checkout_query / successful_payment.

    Сервис вызывается вне сессии игрока; успех подтверждается в stars_service
    (StarsPayment). Иные типы update намеренно игнорируются (200).
    """
    expected_secret = settings.telegram_webhook_secret
    if not expected_secret:
        # Defense in depth (A2+C6a): config._validate_settings must already
        # block production startup without a webhook secret. If that guard was
        # bypassed or settings changed after start, never process an
        # unauthenticated update. Dev keeps the legacy no-check behaviour.
        # getattr: test doubles/legacy settings objects may expose only the
        # fields the endpoint needs; they model dev, while the real production
        # Settings dataclass always carries app_env.
        if getattr(settings, "app_env", "development") == "production":
            raise HTTPException(
                status_code=403,
                detail="Webhook secret not configured.",
            )
    else:
        provided_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if provided_secret != expected_secret:
            raise HTTPException(status_code=403, detail="Forbidden.")

    # A3: структурная валидация поддерживаемых update types. Неизвестные типы
    # по-прежнему игнорируются (200); неполный/битый payload поддерживаемого
    # типа отклоняется 400, и обработчики stars_service не вызываются.
    try:
        if update.get("pre_checkout_query"):
            normalized = PreCheckoutQueryUpdate.model_validate(
                update
            ).model_dump(by_alias=True, exclude_none=True)
        elif (
            isinstance(update.get("message"), dict)
            and update["message"].get("successful_payment")
        ):
            normalized = SuccessfulPaymentUpdate.model_validate(
                update
            ).model_dump(by_alias=True, exclude_none=True)
        else:
            # Прочие типы update (text, callback_query, my_chat_member, ...).
            return {"ok": True}
    except ValidationError:
        raise HTTPException(
            status_code=400, detail="Invalid Telegram update"
        ) from None

    try:
        if "pre_checkout_query" in normalized:
            handle_pre_checkout_query(normalized)
        else:
            handle_successful_payment(normalized)
    except Exception as error:  # noqa: BLE001 — webhook не должен падать
        logger.exception("Telegram webhook error: %s", error)
        # Всегда 200: Telegram ретраит не-2xx бесконечно, а successful_payment
        # идемпотентен (status=completed + unique GasTransaction) — повторная
        # доставка безопасна, бесконечный ретрай-цикл не нужен. 500/4xx дали бы
        # именно ретрай-цикл из push-очереди Telegram.
    return {"ok": True}
