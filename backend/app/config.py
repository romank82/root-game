import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Загружаем backend/.env независимо от текущей рабочей директории.
BACKEND_DIR = Path(__file__).resolve().parent.parent

# Диагностика: откуда взялось значение (env vs backend/.env vs дефолт).
# Значение (username) — не секрет, токены/секреты НЕ логировать.
_env_username_before = os.environ.get("TELEGRAM_BOT_USERNAME")
load_dotenv(BACKEND_DIR / ".env")
_env_username_after = os.environ.get("TELEGRAM_BOT_USERNAME")
if _env_username_before:
    # override=False: переменная окружения (shell, uvicorn --env-file,
    # docker compose) имеет приоритет над backend/.env.
    logger.warning(
        "TELEGRAM_BOT_USERNAME взят из окружения (%s), backend/.env не "
        "переопределил (override=False); итоговое значение: %s",
        _env_username_before,
        _env_username_after,
    )

def _csv_env(name: str, default: str) -> list[str]:
    raw_value = os.getenv(name, default)
    return [
        value.strip().rstrip("/")
        for value in raw_value.split(",")
        if value.strip()
    ]

@dataclass(frozen=True)
class Settings:
    app_env: str
    database_url: str
    cors_origins: list[str]
    telegram_bot_token: str
    telegram_bot_username: str
    telegram_initdata_max_age_seconds: int
    telegram_webhook_secret: str
    game_session_secret: str
    game_session_lifetime_seconds: int
    admin_session_lifetime_seconds: int
    # TON (testnet): мнемоника «спец» payout-кошелька и сеть.
    ton_payout_mnemonic: str = ""
    ton_network: str = "testnet"
    ton_api_endpoint: str = ""
    # API-ключ TonCenter: без него анонимный лимит ~1 запрос/сек, а батч
    # выплат делает по запросу на каждого получателя (адрес jetton-кошелька).
    ton_api_key: str = ""
    # Индексер для поиска транзакций: TonCenter v2 getTransactions на тестнете
    # возвращает 500 (lite server «cannot locate transaction»), а tonapi.io
    # отдаёт историю стабильно. Пусто — выводится из TON_NETWORK.
    ton_indexer_endpoint: str = ""
    # Адрес минтера ROOT (Jetton master) — для Jetton transfer.
    ton_root_jetton_master: str = ""
    # Sentry/GlitchTip (Sprint 13.6): DSN пустой = no-op.
    sentry_dsn: str = ""
    sentry_environment: str = ""
    sentry_traces_sample_rate: float = 0.0
    sentry_release: str = ""

DEFAULT_SQLITE_PATH = BACKEND_DIR / "chimera.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

settings = Settings(
    app_env=os.getenv("APP_ENV", "development"),
    database_url=os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL),
    cors_origins=_csv_env(
        "CORS_ORIGINS",
        (
            "http://localhost:5173,"
            "http://localhost:5174,"
            "http://127.0.0.1:5173,"
            "http://127.0.0.1:5174"
        ),
    ),
    telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
    telegram_bot_username=os.getenv("TELEGRAM_BOT_USERNAME", ""),
    telegram_initdata_max_age_seconds=int(
        os.getenv("TELEGRAM_INITDATA_MAX_AGE_SECONDS", "3600")
    ),
    telegram_webhook_secret=os.getenv("TELEGRAM_WEBHOOK_SECRET", ""),
    game_session_secret=os.getenv("GAME_SESSION_SECRET", ""),
    game_session_lifetime_seconds=int(
        os.getenv("GAME_SESSION_LIFETIME_SECONDS", "86400")
    ),
    admin_session_lifetime_seconds=int(
        os.getenv("ADMIN_SESSION_LIFETIME_SECONDS", "86400")
    ),
    ton_payout_mnemonic=os.getenv("TON_PAYOUT_MNEMONIC", ""),
    ton_network=os.getenv("TON_NETWORK", "testnet"),
    ton_api_endpoint=os.getenv("TON_API_ENDPOINT", ""),
    ton_api_key=os.getenv("TON_API_KEY", ""),
    ton_indexer_endpoint=os.getenv("TON_INDEXER_ENDPOINT", ""),
    ton_root_jetton_master=os.getenv("TON_ROOT_JETTON_MASTER", ""),
    sentry_dsn=os.getenv("SENTRY_DSN", ""),
    sentry_environment=os.getenv(
        "SENTRY_ENVIRONMENT", os.getenv("APP_ENV", "development")
    ),
    sentry_traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0")),
    sentry_release=os.getenv("SENTRY_RELEASE", ""),
)


def _validate_settings(settings: Settings) -> None:
    """Fail fast on unsafe production configuration (A2+C6a).

    An empty webhook secret in production would make /webhook/telegram accept
    unauthenticated updates (Stars payments). Development keeps the legacy
    behaviour: an empty secret disables header verification only in dev.
    """
    if settings.app_env == "production" and not settings.telegram_webhook_secret:
        raise RuntimeError(
            "TELEGRAM_WEBHOOK_SECRET is required in production "
            "(webhook would be unauthenticated)."
        )


_validate_settings(settings)
