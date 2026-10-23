"""Этап 9.3.1 — ИНФРАСТРУКТУРА параллельных финансовых тестов на PostgreSQL.

Текущий шаг — только каркас (Sprint 9.3.1, шаг 1):
  - схема поднимается alembic upgrade head на отдельной тестовой БД
    chimera_test (docker-compose: сервис db-test, порт 5433);
  - SessionLocal патчится на PG по образцу test_economy_9_3.py
    (четыре канала: app.db, mission_engine, shop_service, fallback_shop);
  - тест мягкий к отсутствию PG: если localhost:5433 недоступен — skip
    (unittest.skipTest в setUp), локальный SQLite-прогон не ломается.

Сам параллельный тест покупок (purchase_catalog_item, FOR UPDATE) —
СЛЕДУЮЩИМ шагом; здесь test_pg_infrastructure_ready только доказывает,
что на PostgreSQL миграции применяются и схема готова к конкурентным
проверкам.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Отдельный тестовый PG на порту 5433 (docker-compose: db-test), чтобы не
# конфликтовать с dev-БД на 5432. Переопределяется через PG_TEST_DATABASE_URL.
PG_URL = os.environ.get(
    "PG_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/chimera_test",
)


def _pg_available() -> bool:
    """True, если PG на PG_URL доступен (короткий timeout, исключений нет)."""
    try:
        engine = create_engine(
            PG_URL,
            pool_pre_ping=True,
            connect_args={"connect_timeout": 3},
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


class EconomyPg931InfrastructureTests(unittest.TestCase):
    """9.3.1: PG-инфраструктура — схема поднимается на PostgreSQL."""

    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модули; SessionLocal патчится на PG в setUp."""
        from app import db, fallback_shop, mission_engine, shop_service

        cls.db_module = db
        cls.mission_engine = mission_engine
        cls.shop_service = shop_service
        cls.fallback_shop = fallback_shop
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Чистая PG-схема + alembic upgrade head (обновляется каждый тест).

        Патчатся ЧЕТЫРЕ канала SessionLocal (по образцу test_economy_9_3.py):
          - app.db.SessionLocal — ленивые импорты и транзакции через
            from app.db import SessionLocal на момент вызова;
          - mission_engine / fallback_shop — module-level импорт на старте
            модуля, атрибут зафиксирован и требует отдельной подмены;
          - shop_service — не имеет module-level SessionLocal (session
            передаётся извне в purchase_catalog_item), поэтому патч с
            create=True: безвреден, но не падает из-за отсутствия атрибута.
        """
        if not _pg_available():
            self.skipTest(
                f"PostgreSQL не доступен ({PG_URL}); PG-тесты пропущены."
            )

        # Чистая база: пересоздаём schema public (alembic_version в том же
        # public — DROP SCHEMA каскадно сносит и его, и все миграции).
        admin_engine = create_engine(
            PG_URL,
            connect_args={"connect_timeout": 5},
        )
        with admin_engine.connect() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
            connection.commit()
        admin_engine.dispose()

        environment = os.environ.copy()
        environment["DATABASE_URL"] = PG_URL
        subprocess.run(
            [
                sys.executable,
                "-m",
                "alembic",
                "-c",
                str(BACKEND_ROOT / "alembic.ini"),
                "upgrade",
                "head",
            ],
            cwd=BACKEND_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )

        self.engine = create_engine(PG_URL, pool_pre_ping=True)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        self._session_local_patches = [
            patch("app.db.SessionLocal", self.SessionLocal),
            patch.object(self.mission_engine, "SessionLocal", self.SessionLocal),
            patch.object(
                self.shop_service, "SessionLocal", self.SessionLocal, create=True
            ),
            patch.object(self.fallback_shop, "SessionLocal", self.SessionLocal),
        ]
        for session_local_patch in self._session_local_patches:
            session_local_patch.start()

    def tearDown(self) -> None:
        for session_local_patch in self._session_local_patches:
            session_local_patch.stop()
        self.engine.dispose()

    def test_pg_infrastructure_ready(self) -> None:
        """Схема поднялась на PG: alembic_version + ключевые таблицы."""
        with self.SessionLocal() as session:
            # 1. Миграции применились: alembic_version непустая.
            alembic_rows = session.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchall()
            self.assertTrue(
                alembic_rows, "alembic_version пуста — миграции не применились"
            )

            # 2. Ключевая игровая таблица существует (seed из миграций).
            player_rows = session.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'game_players'"
                )
            ).fetchall()
            self.assertTrue(player_rows, "таблица game_players отсутствует")

            # 3. SELECT 1 работает через test SessionLocal (PG-канал живой).
            self.assertEqual(
                session.execute(text("SELECT 1")).scalar(),
                1,
            )

