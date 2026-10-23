import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Загружаем backend/.env независимо от текущей рабочей директории.
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

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
)
