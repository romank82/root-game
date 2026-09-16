import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Локально используем уже существующую SQLite-базу:
# root-game/backend/chimera.db
#
# В production значение будет переопределено, например:
# DATABASE_URL=postgresql+psycopg://user:password@host:5432/chimera
DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent.parent / "chimera.db"
DEFAULT_DATABASE_URL = f"sqlite:///{DEFAULT_SQLITE_PATH}"

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)

engine_options: dict = {
    "pool_pre_ping": True,
}

# SQLite требует эту опцию для работы через FastAPI в нескольких потоках.
if DATABASE_URL.startswith("sqlite"):
    engine_options["connect_args"] = {
        "check_same_thread": False,
        # Ждём освобождения write-lock вместо немедленного SQLITE_BUSY.
        "timeout": 10,
    }

engine = create_engine(DATABASE_URL, **engine_options)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Базовый класс для всех SQLAlchemy-моделей CHIMERA."""


def get_db():
    """FastAPI dependency для получения и закрытия DB-сессии."""
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
