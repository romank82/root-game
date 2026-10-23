"""Ник игрока (10.0, часть 2) — генерация в _upsert_telegram_player.

Live SQLite + alembic upgrade head (паттерн test_admin_economy.py): для
каждого теста — свежая disposable БД со схемой из миграций (включая
884a02f1a72d add nickname to game_players). SessionLocal модуля app.main
патчится на тестовую БД (паттерн test_admin_player_restrictions.py);
_upsert_telegram_player вызывается напрямую с теми же примитивными
аргументами, которые наполняет VerifiedTelegramUser из verify_init_data
(telegram_id / first_name / last_name / username / photo_url).

Покрывает:
  - новый игрок: ник сгенерирован в формате основа#123-456-789
    (транслит first_name), nickname_lower == nickname.lower();
  - существующий игрок с ником: ник immutable при повторном входе,
    display_name продолжает перезаписываться;
  - существующий игрок без ника (nickname=None): ник генерируется
    при входе (страховка поверх backfill миграции 884a02f1a72d).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import GamePlayer

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

NICKNAME_PATTERN = re.compile(r"^[a-z0-9-]+#\d{3}-\d{3}-\d{3}$")


class TelegramNicknameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модуль; SessionLocal патчится на свежую БД в setUp."""
        from app import main

        cls.main = main
        cls._session_local_patch = None

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-nickname-tests-"
        )
        self.database_path = Path(self._temporary_directory.name) / "nickname.sqlite3"
        database_url = f"sqlite:///{self.database_path}"

        environment = os.environ.copy()
        environment["DATABASE_URL"] = database_url

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

        self.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(self.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self._session_local_patch = patch.object(
            self.main, "SessionLocal", self.SessionLocal
        )
        self._session_local_patch.start()

    def tearDown(self) -> None:
        self._session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------------

    def _upsert(self, telegram_id: str, first_name: str, username: str | None):
        """Вызов _upsert_telegram_player с профилем из VerifiedTelegramUser.

        last_name/photo_url = None — на генерацию ника не влияют.
        """
        return self.main._upsert_telegram_player(
            telegram_id=telegram_id,
            first_name=first_name,
            last_name=None,
            username=username,
            photo_url=None,
        )

    def _add_telegram_player(self, external_id: str, **fields: object) -> str:
        """Прямое создание Telegram-игрока (мимо _upsert_telegram_player)."""
        player_id = f"player-{uuid.uuid4().hex}"
        values: dict[str, object] = {
            "id": player_id,
            "display_name": "Old name",
            "auth_provider": "telegram",
            "external_id": external_id,
            "status": "active",
        }
        values.update(fields)
        with self.SessionLocal.begin() as session:
            session.add(GamePlayer(**values))
        return player_id

    def _stored_nicknames(self, player_id: str) -> tuple[str | None, str | None]:
        """Ники из БД (не из объекта в памяти) — что реально сохранено."""
        with self.SessionLocal() as session:
            player = session.get(GamePlayer, player_id)
        return player.nickname, player.nickname_lower

    # ---- Тесты --------------------------------------------------------------

    def test_upsert_generates_nickname_for_new_player(self) -> None:
        """Новый игрок получает ник основа#123-456-789 + nickname_lower."""
        player = self._upsert(
            telegram_id="100000001",
            first_name="Роман",
            username="romank82",
        )

        self.assertRegex(player.nickname, NICKNAME_PATTERN)
        self.assertTrue(player.nickname.startswith("roman#"))
        self.assertEqual(player.nickname_lower, player.nickname.lower())
        self.assertEqual(player.display_name, "Роман")

        stored_nickname, stored_lower = self._stored_nicknames(player.id)
        self.assertEqual(stored_nickname, player.nickname)
        self.assertEqual(stored_lower, player.nickname.lower())

    def test_upsert_keeps_existing_nickname(self) -> None:
        """Существующий ник immutable при повторном входе; display_name меняется."""
        player_id = self._add_telegram_player(
            external_id="100000002",
            display_name="Роман",
            telegram_username="olduser",
            telegram_username_normalized="olduser",
            nickname="roman#111-222-333",
            nickname_lower="roman#111-222-333",
        )

        player = self._upsert(
            telegram_id="100000002",
            first_name="НовоеИмя",
            username="newuser",
        )

        self.assertEqual(player.id, player_id)
        self.assertEqual(player.nickname, "roman#111-222-333")
        self.assertEqual(player.nickname_lower, "roman#111-222-333")
        # display_name по-прежнему перезаписывается (существующее поведение).
        self.assertEqual(player.display_name, "НовоеИмя")

        stored_nickname, stored_lower = self._stored_nicknames(player_id)
        self.assertEqual(stored_nickname, "roman#111-222-333")
        self.assertEqual(stored_lower, "roman#111-222-333")

    def test_upsert_generates_for_existing_without_nickname(self) -> None:
        """Игрок без ника (nickname=None) получает его при входе."""
        player_id = self._add_telegram_player(
            external_id="100000003",
            display_name="Ольга",
            telegram_username="olga",
            telegram_username_normalized="olga",
        )

        player = self._upsert(
            telegram_id="100000003",
            first_name="Ольга",
            username="olga",
        )

        self.assertIsNotNone(player.nickname)
        self.assertRegex(player.nickname, NICKNAME_PATTERN)
        self.assertTrue(player.nickname.startswith("olga#"))
        self.assertEqual(player.nickname_lower, player.nickname.lower())
        self.assertEqual(player.display_name, "Ольга")

        stored_nickname, stored_lower = self._stored_nicknames(player_id)
        self.assertEqual(stored_nickname, player.nickname)
        self.assertEqual(stored_lower, player.nickname.lower())


if __name__ == "__main__":
    unittest.main()
