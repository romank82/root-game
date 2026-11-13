"""Chat командной сессии (этап 6.6-a): доступ, закрытие после финала, выдача.

Инфраструктура — паттерн test_team_wave_flow.py: изолированная disposable
SQLite + alembic upgrade head, SessionLocal патчится на уровне app.db
(сервисы импортируют его лениво), вызовы *_entrypoint напрямую.

Покрывает:
  1. не участник сессии -> 404 (и list, и send);
  2. несуществующая сессия -> 404;
  3. завершённая сессия (succeeded/failed/expired/cancelled_before_start)
     -> 409 «Сессия завершена. Чат недоступен.»;
  4. активные статусы (collecting/ready_to_start/active) -> отправка работает;
  5. пустой/пробельный текст -> 422;
  6. текст > 1000 символов -> 422;
  7. порядок выдачи — новые сверху, поля id/playerId/text/createdAt;
  8. limit + hasMore (limit=2 из 3 -> 2 + hasMore=True);
  9. курсор before=<createdAt> отдаёт следующую (более старую) страницу;
 10. status='hidden' не попадает в список (задел под 6.7.b);
 11. участник со status='left' -> 404.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError
from app.team_session_chat_service import (
    list_messages_entrypoint,
    send_message_entrypoint,
)
from tests.test_geo_team_contract import valid_team_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"


class TeamSessionChatTests(unittest.TestCase):
    """6.6-a: чат внутри TeamSession (не Team)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-team-chat-tests-"
        )
        cls.database_path = Path(cls._temporary_directory.name) / "team_chat.sqlite3"
        database_url = f"sqlite:///{cls.database_path}"

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

        cls.engine = create_engine(
            database_url,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(cls.engine, "connect")
        def enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        from app import db

        cls._session_local_patch = patch.object(db, "SessionLocal", cls.SessionLocal)
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    # ---- Фабрики ------------------------------------------------------------

    def _make_player(self) -> str:
        from app.models import GamePlayer

        player_id = f"player-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=f"Player-{player_id[-6:]}",
                    auth_provider="telegram",
                    external_id=f"tg-{uuid.uuid4().hex}",
                    status="active",
                )
            )
        return player_id

    def _make_mission(self) -> str:
        from app.models import Mission, Season

        suffix = uuid.uuid4().hex
        with self.SessionLocal.begin() as session:
            season = Season(
                id=f"season-{suffix}",
                slug=f"season-{suffix}",
                title="Season",
            )
            session.add(season)
            session.flush()
            session.add(
                Mission(
                    id=f"mission-{suffix}",
                    season_id=season.id,
                    slug=f"mission-{suffix}",
                    mission_type="team",
                    mission_category="team",
                    title="Chat mission",
                    status="published",
                    content={},
                    validation_config=valid_team_config(),
                )
            )
        return f"mission-{suffix}"

    def _make_session(
        self,
        players: list[str],
        *,
        status: str = "collecting",
        member_status: str = "joined",
    ) -> str:
        """TeamSession + MissionRun/TeamSessionMember на каждого игрока."""
        from app.geo_team_runtime_models import (
            MissionRun,
            TeamSession,
            TeamSessionMember,
        )

        mission_id = self._make_mission()
        session_id = f"team-session-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                TeamSession(
                    id=session_id,
                    mission_id=mission_id,
                    status=status,
                    effective_config_snapshot=valid_team_config(),
                )
            )
            session.flush()
            for player_id in players:
                mission_run = MissionRun(
                    id=f"mission-run-{uuid.uuid4().hex}",
                    player_id=player_id,
                    mission_id=mission_id,
                    team_session_id=session_id,
                    status="active",
                    effective_config_snapshot=valid_team_config(),
                )
                session.add(mission_run)
                session.flush()
                session.add(
                    TeamSessionMember(
                        id=f"tsm-{uuid.uuid4().hex}",
                        team_session_id=session_id,
                        player_id=player_id,
                        mission_run_id=mission_run.id,
                        status=member_status,
                    )
                )
        return session_id

    def _add_message(
        self,
        session_id: str,
        player_id: str,
        text: str,
        *,
        status: str = "visible",
        created_at: datetime | None = None,
    ) -> str:
        """Прямая вставка (для hidden и детерминированной пагинации)."""
        from app.geo_team_runtime_models import TeamSessionMessage

        message_id = f"team-msg-{uuid.uuid4().hex}"
        moment = created_at or datetime.now(timezone.utc)
        with self.SessionLocal.begin() as session:
            session.add(
                TeamSessionMessage(
                    id=message_id,
                    team_session_id=session_id,
                    player_id=player_id,
                    text=text,
                    status=status,
                    created_at=moment,
                    updated_at=moment,
                )
            )
        return message_id

    # ---- 1-2. Доступ --------------------------------------------------------

    def test_non_member_gets_404_on_list_and_send(self) -> None:
        member = self._make_player()
        outsider = self._make_player()
        session_id = self._make_session([member])

        with self.assertRaises(MissionEngineError) as listed:
            list_messages_entrypoint(outsider, session_id)
        self.assertEqual(listed.exception.status_code, 404)
        self.assertEqual(listed.exception.detail, "Вы не участник этой сессии.")

        with self.assertRaises(MissionEngineError) as sent:
            send_message_entrypoint(outsider, session_id, "привет")
        self.assertEqual(sent.exception.status_code, 404)
        self.assertEqual(sent.exception.detail, "Вы не участник этой сессии.")

    def test_unknown_session_returns_404(self) -> None:
        player_id = self._make_player()

        with self.assertRaises(MissionEngineError) as caught:
            list_messages_entrypoint(player_id, f"team-session-{uuid.uuid4().hex}")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, "Командная сессия не найдена.")

    # ---- 3-4. Статусы сессии ------------------------------------------------

    def test_finished_session_closes_chat(self) -> None:
        for status in (
            "succeeded",
            "failed",
            "expired",
            "cancelled_before_start",
        ):
            player_id = self._make_player()
            session_id = self._make_session([player_id], status=status)

            with self.assertRaises(MissionEngineError) as caught:
                send_message_entrypoint(player_id, session_id, "ещё одно")
            self.assertEqual(caught.exception.status_code, 409, status)
            self.assertEqual(
                caught.exception.detail, "Сессия завершена. Чат недоступен."
            )

            with self.assertRaises(MissionEngineError) as listed:
                list_messages_entrypoint(player_id, session_id)
            self.assertEqual(listed.exception.status_code, 409, status)

    def test_all_active_statuses_allow_send(self) -> None:
        for status in ("collecting", "ready_to_start", "active"):
            player_id = self._make_player()
            session_id = self._make_session([player_id], status=status)

            sent = send_message_entrypoint(player_id, session_id, f"статус {status}")
            self.assertEqual(sent["text"], f"статус {status}")

            listed = list_messages_entrypoint(player_id, session_id)
            self.assertEqual(len(listed["messages"]), 1, status)

    # ---- 5-6. Валидация текста ----------------------------------------------

    def test_empty_text_rejected(self) -> None:
        player_id = self._make_player()
        session_id = self._make_session([player_id])

        with self.assertRaises(MissionEngineError) as caught:
            send_message_entrypoint(player_id, session_id, "   ")
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(caught.exception.detail, "Сообщение не может быть пустым.")

    def test_too_long_text_rejected(self) -> None:
        player_id = self._make_player()
        session_id = self._make_session([player_id])

        with self.assertRaises(MissionEngineError) as caught:
            send_message_entrypoint(player_id, session_id, "x" * 1001)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("слишком длинное", caught.exception.detail)

    # ---- 7-9. Выдача и пагинация -------------------------------------------

    def test_send_then_list_newest_first(self) -> None:
        player_a = self._make_player()
        player_b = self._make_player()
        session_id = self._make_session([player_a, player_b])

        first = send_message_entrypoint(player_a, session_id, "первое")
        second = send_message_entrypoint(player_b, session_id, "  второе  ")

        # trim: пробелы по краям срезаются
        self.assertEqual(second["text"], "второе")

        listed = list_messages_entrypoint(player_a, session_id)
        texts = [row["text"] for row in listed["messages"]]
        self.assertEqual(texts, ["второе", "первое"])
        self.assertFalse(listed["hasMore"])
        self.assertEqual(listed["limit"], 50)

        newest = listed["messages"][0]
        self.assertEqual(newest["id"], second["id"])
        self.assertEqual(newest["playerId"], player_b)
        self.assertIsNotNone(newest["createdAt"])
        # createdAt — aware ISO-8601 (SQLite-наив нормализован в UTC)
        self.assertIn("+00:00", newest["createdAt"])
        self.assertNotEqual(first["id"], second["id"])

    def test_limit_and_has_more(self) -> None:
        player_id = self._make_player()
        session_id = self._make_session([player_id])

        base = datetime.now(timezone.utc) - timedelta(minutes=5)
        for index in range(3):
            self._add_message(
                session_id,
                player_id,
                f"msg-{index}",
                created_at=base + timedelta(seconds=index),
            )

        page = list_messages_entrypoint(player_id, session_id, limit=2)
        self.assertEqual(len(page["messages"]), 2)
        self.assertTrue(page["hasMore"])
        self.assertEqual(page["limit"], 2)
        self.assertEqual(
            [row["text"] for row in page["messages"]], ["msg-2", "msg-1"]
        )

        everything = list_messages_entrypoint(player_id, session_id, limit=50)
        self.assertEqual(len(everything["messages"]), 3)
        self.assertFalse(everything["hasMore"])

    def test_before_cursor_returns_older_page(self) -> None:
        player_id = self._make_player()
        session_id = self._make_session([player_id])

        base = datetime.now(timezone.utc) - timedelta(minutes=5)
        for index in range(3):
            self._add_message(
                session_id,
                player_id,
                f"msg-{index}",
                created_at=base + timedelta(seconds=index),
            )

        first_page = list_messages_entrypoint(player_id, session_id, limit=2)
        oldest_in_page = first_page["messages"][-1]["createdAt"]

        second_page = list_messages_entrypoint(
            player_id, session_id, limit=2, before=oldest_in_page
        )
        self.assertEqual(
            [row["text"] for row in second_page["messages"]], ["msg-0"]
        )
        self.assertFalse(second_page["hasMore"])

    def test_hidden_message_not_listed(self) -> None:
        player_id = self._make_player()
        session_id = self._make_session([player_id])

        visible_id = self._add_message(session_id, player_id, "видно")
        hidden_id = self._add_message(
            session_id, player_id, "скрыто", status="hidden"
        )

        listed = list_messages_entrypoint(player_id, session_id)
        ids = [row["id"] for row in listed["messages"]]
        self.assertIn(visible_id, ids)
        self.assertNotIn(hidden_id, ids)

    # ---- 10. Выбывший участник ---------------------------------------------

    def test_left_member_gets_404(self) -> None:
        player_id = self._make_player()
        session_id = self._make_session([player_id], member_status="left")

        with self.assertRaises(MissionEngineError) as caught:
            send_message_entrypoint(player_id, session_id, "я вышел")
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(caught.exception.detail, "Вы не участник этой сессии.")


if __name__ == "__main__":
    unittest.main()
