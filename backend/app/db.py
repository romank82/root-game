from sqlalchemy import create_engine, event
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

if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        # SQLite requires this PRAGMA on every new DBAPI connection to enforce
        # declared foreign keys. PostgreSQL enforces them natively.
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()


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
