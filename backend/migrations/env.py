from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.db import Base, DATABASE_URL
import app.models  # noqa: F401 — импорт регистрирует модели в Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# DATABASE_URL единый для FastAPI, SQLAlchemy и Alembic.
config.set_main_option("sqlalchemy.url", DATABASE_URL)

target_metadata = Base.metadata

# Временные таблицы прототипа. Они используются работающим старым API и будут
# перенесены в отдельной контролируемой миграции, а не удалены autogenerate.
LEGACY_TABLES = {"players", "completed_rewards"}


def include_object(object_, name, type_, reflected, compare_to):
    """Не включать legacy-таблицы прототипа в Alembic autogenerate."""
    return not (type_ == "table" and name in LEGACY_TABLES)


def run_migrations_offline() -> None:
    """Запуск миграций без подключения к БД."""
    url = config.get_main_option("sqlalchemy.url")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Запуск миграций с подключением к БД."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
