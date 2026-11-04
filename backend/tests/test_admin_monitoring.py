"""Тесты read-only админ-эндпоинтов «Мониторинг» (13.5-a).

Покрывает логику выборки AppError/PlayerEvent на реальной SQLite
(alembic upgrade head): фильтры (severity / event_type / player_id),
period (day/week/month/all), пагинацию (limit/offset, clamp limit).

Инфраструктура — по образцу test_country_policy_integration.py:
реальная SQLite + alembic upgrade head; SessionLocal патчится и в
app.db, и в app.admin_monitoring (модуль держит прямую ссылку
`from app.db import SessionLocal`).

Эндпоинты вызываются напрямую (функция + фейковый _admin): дефолт
Depends(require_permission(...)) при прямом вызове не исполняется,
поэтому permission-логика здесь не проверяется — она покрыта
admin-тестами (require_permission + авторизация).

В приложении ничего не меняется: записи создаются только в изолированной
тестовой базе.
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
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import AppError, GamePlayer, PlayerEvent, SystemSetting

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


def _now_naive_utc() -> datetime:
    """Naive UTC now — как SQLite хранит DateTime(timezone=True)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class AdminMonitoringTests(unittest.TestCase):
    """Read-only эндпоинты мониторинга на реальной SQLite (alembic head)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-monitoring-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "monitoring.sqlite3"
        )
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

        from app import admin_monitoring

        cls._session_local_patches = [
            patch("app.db.SessionLocal", cls.SessionLocal),
            patch.object(admin_monitoring, "SessionLocal", cls.SessionLocal),
        ]
        for session_local_patch in cls._session_local_patches:
            session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        for session_local_patch in cls._session_local_patches:
            session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def setUp(self) -> None:
        """Каждый тест стартует с пустых таблиц (изолированная БД)."""
        with self.SessionLocal.begin() as session:
            session.query(PlayerEvent).delete()
            session.query(AppError).delete()
            session.query(GamePlayer).delete()

    # ---- Fixtures и хелперы -------------------------------------------

    def _make_player(self, session, prefix: str = "player-mon") -> str:
        """GamePlayer с корректным id для FK PlayerEvent.player_id."""
        player_id = f"{prefix}-{uuid.uuid4().hex[:10]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name=f"Monitoring Player-{player_id[-6:]}",
                auth_provider="telegram",
                external_id=f"tg-{uuid.uuid4().hex}",
                status="active",
            )
        )
        session.flush()
        return player_id

    def _add_error(
        self,
        session,
        severity: str = "error",
        error_type: str = "mission.accept_failed",
        message: str = "boom",
        created_at: datetime | None = None,
        correlation_id: str | None = None,
        endpoint: str | None = None,
        status_code: int | None = None,
        player_id: str | None = None,
    ) -> None:
        error = AppError(
            id=f"app-error-{uuid.uuid4().hex[:16]}",
            correlation_id=correlation_id or uuid.uuid4().hex,
            severity=severity,
            error_type=error_type,
            message=message,
            safe_context={"grid": "hex-1"},
            endpoint=endpoint,
            status_code=status_code,
            player_id=player_id,
        )
        if created_at is not None:
            error.created_at = created_at
        session.add(error)
        session.flush()

    def _add_event(
        self,
        session,
        player_id: str,
        event_type: str = "auth.login",
        created_at: datetime | None = None,
    ) -> None:
        event = PlayerEvent(
            id=f"player-event-{uuid.uuid4().hex[:16]}",
            player_id=player_id,
            event_type=event_type,
            payload_json={"marker": "m1"},
            correlation_id=uuid.uuid4().hex,
        )
        if created_at is not None:
            event.created_at = created_at
        session.add(event)
        session.flush()

    @staticmethod
    def _call_errors(**kwargs) -> dict:
        from app.admin_monitoring import list_admin_monitoring_errors

        return list_admin_monitoring_errors(
            _admin=SimpleNamespace(id="admin-monitoring-1"), **kwargs
        )

    @staticmethod
    def _call_events(**kwargs) -> dict:
        from app.admin_monitoring import list_admin_monitoring_events

        return list_admin_monitoring_events(
            _admin=SimpleNamespace(id="admin-monitoring-1"), **kwargs
        )

    @staticmethod
    def _call_error_groups(**kwargs) -> dict:
        from app.admin_monitoring import list_admin_monitoring_error_groups

        return list_admin_monitoring_error_groups(
            _admin=SimpleNamespace(id="admin-monitoring-1"), **kwargs
        )
# ---- Tests ----------------------------------------------------------

    def test_errors_list_and_severity_filter(self) -> None:
        """3 AppError: list -> 3, total=3; severity=error -> только 1."""
        with self.SessionLocal.begin() as session:
            self._add_error(session, severity="critical")
            self._add_error(session, severity="critical")
            self._add_error(session, severity="error")

        all_result = self._call_errors()
        self.assertEqual(all_result["total"], 3)
        self.assertEqual(len(all_result["errors"]), 3)
        self.assertEqual(
            {err["severity"] for err in all_result["errors"]},
            {"error", "critical"},
        )

        error_only = self._call_errors(severity="error")
        self.assertEqual(error_only["total"], 1)
        self.assertEqual(len(error_only["errors"]), 1)
        self.assertEqual(error_only["errors"][0]["severity"], "error")

    def test_errors_correlation_id_filter(self) -> None:
        """Поиск по correlation_id: точное совпадение -> 1; несуществующий -> 0."""
        target = "deadbeef" * 4  # 32 hex-символа, как uuid4().hex
        with self.SessionLocal.begin() as session:
            self._add_error(session, correlation_id=target)
            self._add_error(session)  # случайный correlation_id

        found = self._call_errors(correlation_id=target)
        self.assertEqual(found["total"], 1)
        self.assertEqual(len(found["errors"]), 1)
        self.assertEqual(found["errors"][0]["correlationId"], target)

        missing = self._call_errors(correlation_id="f" * 32)
        self.assertEqual(missing["total"], 0)
        self.assertEqual(len(missing["errors"]), 0)

    def test_events_list_and_filters(self) -> None:
        """3 PlayerEvent: list -> 3; event_type -> 1; player_id -> 3."""
        with self.SessionLocal.begin() as session:
            player_id = self._make_player(session)
            self._add_event(session, player_id, "auth.login")
            self._add_event(session, player_id, "mission.accepted")
            self._add_event(session, player_id, "mission.completed")

        all_result = self._call_events()
        self.assertEqual(all_result["total"], 3)
        self.assertEqual(len(all_result["events"]), 3)

        by_type = self._call_events(event_type="auth.login")
        self.assertEqual(by_type["total"], 1)
        self.assertEqual(by_type["events"][0]["eventType"], "auth.login")

        by_player = self._call_events(player_id=player_id)
        self.assertEqual(by_player["total"], 3)

        by_player_and_type = self._call_events(
            player_id=player_id, event_type="mission.accepted"
        )
        self.assertEqual(by_player_and_type["total"], 1)

    def test_pagination(self) -> None:
        """5 ошибок, limit=2: offset 0 -> 2, offset 2 -> 2, offset 4 -> 1."""
        now = _now_naive_utc()
        with self.SessionLocal.begin() as session:
            for index in range(5):
                self._add_error(
                    session,
                    severity="error",
                    created_at=now - timedelta(hours=index + 1),
                )

        page_1 = self._call_errors(limit=2, offset=0)
        self.assertEqual(page_1["total"], 5)
        self.assertEqual(len(page_1["errors"]), 2)
        self.assertEqual(page_1["limit"], 2)

        page_2 = self._call_errors(limit=2, offset=2)
        self.assertEqual(len(page_2["errors"]), 2)

        page_3 = self._call_errors(limit=2, offset=4)
        self.assertEqual(len(page_3["errors"]), 1)

        # Сортировка created_at desc: самая свежая ошибка первой.
        newest = max(
            page_1["errors"] + page_2["errors"] + page_3["errors"],
            key=lambda err: err["createdAt"],
        )
        self.assertEqual(page_1["errors"][0]["createdAt"], newest["createdAt"])

    def test_limit_clamp(self) -> None:
        """limit=1000 -> 200; limit=0 -> 1 (max(1, min(limit, MAX)))."""
        now = _now_naive_utc()
        with self.SessionLocal.begin() as session:
            for index in range(3):
                self._add_error(
                    session,
                    severity="error",
                    created_at=now - timedelta(hours=index + 1),
                )

        clamped_high = self._call_errors(limit=1000)
        self.assertEqual(clamped_high["limit"], 200)
        self.assertEqual(len(clamped_high["errors"]), 3)
        self.assertEqual(clamped_high["total"], 3)

        clamped_low = self._call_errors(limit=0)
        self.assertEqual(clamped_low["limit"], 1)
        self.assertEqual(len(clamped_low["errors"]), 1)
        self.assertEqual(clamped_low["total"], 3)

    def test_period_filter(self) -> None:
        """period=day -> только свежие (24ч); week/month -> 7/30 дн; all."""
        now = _now_naive_utc()
        recent = now - timedelta(hours=1)  # входит в day/week/month
        mid = now - timedelta(days=2)  # входит в week/month, НЕ в day
        old = now - timedelta(days=40)  # входит только в all

        with self.SessionLocal.begin() as session:
            self._add_error(session, severity="error", created_at=recent)
            self._add_error(session, severity="error", created_at=mid)
            self._add_error(session, severity="error", created_at=old)

        self.assertEqual(self._call_errors(period="all")["total"], 3)
        self.assertEqual(self._call_errors(period="day")["total"], 1)
        self.assertEqual(self._call_errors(period="week")["total"], 2)
        self.assertEqual(self._call_errors(period="month")["total"], 2)

    def test_error_groups(self) -> None:
        """M-3: группировка по error_type/endpoint/status_code.

        5 ошибок: A (/x, 500) x3 (player p1,p1,p2), B (/y, 500) x2 (p3, None).
        - min_count=1 -> 2 группы; A: count=3, affectedPlayers=2 (NULL не
          считается); B: count=2, affectedPlayers=1.
        - min_count=3 -> 1 группа (A).
        - period=day (свежие) -> 2 группы.
        - total = число групп (2).
        """
        now = _now_naive_utc()
        with self.SessionLocal.begin() as session:
            self._add_error(
                session,
                error_type="A",
                endpoint="/x",
                status_code=500,
                player_id="p1",
                created_at=now - timedelta(hours=3),
            )
            self._add_error(
                session,
                error_type="A",
                endpoint="/x",
                status_code=500,
                player_id="p2",
                created_at=now - timedelta(hours=2),
            )
            self._add_error(
                session,
                error_type="A",
                endpoint="/x",
                status_code=500,
                player_id="p1",
                created_at=now - timedelta(hours=1),
            )
            self._add_error(
                session,
                error_type="B",
                endpoint="/y",
                status_code=500,
                player_id="p3",
                created_at=now - timedelta(hours=2),
            )
            self._add_error(
                session,
                error_type="B",
                endpoint="/y",
                status_code=500,
                player_id=None,
                created_at=now - timedelta(hours=1),
            )

        result = self._call_error_groups(period="all", min_count=1)
        self.assertEqual(result["total"], 2)
        self.assertEqual(len(result["groups"]), 2)

        # Сортировка count desc: группа A (3) первой, затем B (2).
        group_a, group_b = result["groups"]
        self.assertEqual(group_a["errorType"], "A")
        self.assertEqual(group_a["endpoint"], "/x")
        self.assertEqual(group_a["statusCode"], 500)
        self.assertEqual(group_a["count"], 3)
        self.assertEqual(group_a["affectedPlayers"], 2)  # p1, p2
        self.assertIsNotNone(group_a["firstSeen"])
        self.assertIsNotNone(group_a["lastSeen"])
        self.assertLess(group_a["firstSeen"], group_a["lastSeen"])

        self.assertEqual(group_b["errorType"], "B")
        self.assertEqual(group_b["endpoint"], "/y")
        self.assertEqual(group_b["count"], 2)
        self.assertEqual(group_b["affectedPlayers"], 1)  # p3; NULL не считается

        # min_count=3 -> только группа A.
        only_big = self._call_error_groups(period="all", min_count=3)
        self.assertEqual(only_big["total"], 1)
        self.assertEqual(len(only_big["groups"]), 1)
        self.assertEqual(only_big["groups"][0]["errorType"], "A")

        # period=day (созданы «сейчас») -> обе группы.
        day_result = self._call_error_groups(period="day")
        self.assertEqual(day_result["total"], 2)
        self.assertEqual(len(day_result["groups"]), 2)

    def test_errors_filter_by_group_fields(self) -> None:
        """M-4: /errors фильтрует по error_type/endpoint/status_code.

        3 ошибки: A (/x, 500) x2, B (/y, 500) x1.
        Фильтры (как клик по группе в M-6) сужают выборку согласованно.
        """
        with self.SessionLocal.begin() as session:
            self._add_error(
                session, error_type="A", endpoint="/x", status_code=500
            )
            self._add_error(
                session, error_type="A", endpoint="/x", status_code=500
            )
            self._add_error(
                session, error_type="B", endpoint="/y", status_code=500
            )

        self.assertEqual(self._call_errors(error_type="A")["total"], 2)
        self.assertEqual(self._call_errors(endpoint="/x")["total"], 2)
        self.assertEqual(self._call_errors(status_code=500)["total"], 3)
        self.assertEqual(
            self._call_errors(error_type="A", endpoint="/x")["total"], 2
        )
        self.assertEqual(self._call_errors(error_type="B")["total"], 1)
        self.assertEqual(self._call_errors(error_type="C")["total"], 0)

    def test_error_groups_is_global(self) -> None:
        """M-5: isGlobal = count >= monitoring.global_threshold (CMS-first).

        2 группы: A count=3, B count=2.
        - threshold=3 -> A True, B False;
        - threshold=2 -> оба True;
        - threshold=10 -> оба False;
        - удалить строку -> default 100 -> оба False.
        """
        with self.SessionLocal.begin() as session:
            for _ in range(3):
                self._add_error(
                    session, error_type="A", endpoint="/x", status_code=500
                )
            for _ in range(2):
                self._add_error(
                    session, error_type="B", endpoint="/y", status_code=500
                )

        def _set_threshold(value: int | None) -> None:
            with self.SessionLocal.begin() as session:
                setting = session.get(SystemSetting, "monitoring.global_threshold")
                if value is None:
                    if setting is not None:
                        session.delete(setting)
                    return
                if setting is None:
                    session.add(
                        SystemSetting(
                            key="monitoring.global_threshold",
                            value_json=value,
                            value_type="integer",
                            category="monitoring",
                            title="Глобальный порог ошибок группы",
                            is_sensitive=False,
                            status="active",
                        )
                    )
                else:
                    setting.value_json = value

        def _groups_by_type() -> dict:
            result = self._call_error_groups(period="all")
            return {group["errorType"]: group for group in result["groups"]}

        try:
            _set_threshold(3)
            groups = _groups_by_type()
            self.assertTrue(groups["A"]["isGlobal"])  # 3 >= 3
            self.assertFalse(groups["B"]["isGlobal"])  # 2 < 3

            _set_threshold(2)
            groups = _groups_by_type()
            self.assertTrue(groups["A"]["isGlobal"])  # 3 >= 2
            self.assertTrue(groups["B"]["isGlobal"])  # 2 >= 2

            _set_threshold(10)
            groups = _groups_by_type()
            self.assertFalse(groups["A"]["isGlobal"])  # 3 < 10
            self.assertFalse(groups["B"]["isGlobal"])  # 2 < 10

            _set_threshold(None)
            groups = _groups_by_type()
            self.assertFalse(groups["A"]["isGlobal"])  # default 100
            self.assertFalse(groups["B"]["isGlobal"])
        finally:
            # Восстановить default в общей temp-БД (setUp system_settings не чистит).
            _set_threshold(100)
