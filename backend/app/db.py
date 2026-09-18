from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

DATABASE_URL = settings.database_url

engine_options: dict = {
    "pool_pre_ping": True,
}

# SQLite требует эту опцию для работы FastAPI в нескольких потоках.
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
