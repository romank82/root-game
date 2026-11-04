"""13.4-b — тесты app_errors_middleware (main.py): запись AppError на 5xx.

Охват:

  1. test_5xx_writes_app_error — необработанный 5xx пишет AppError с
     error_type/message/safe_context/correlation_id из audit_context
     (основной путь).
  2. test_4xx_not_written — HTTPException (как делают все endpoint'ы для
     4xx) пробрасывается БЕЗ записи.
  3. test_correlation_id_fallback_not_from_audit_context — при
     отсутствии audit_context / correlation_id в state используется
     fallback uuid4().hex (длина 32, hex).
  4. test_404_through_full_stack_not_written — один ASGI-кейс: 404 через
     полный стек (TestClient) не пишет AppError.

Стратегия — UNIT-SMOKE (прямой вызов middleware с fake Request и mock
call_next): детерминированнее и без ExceptionGroup (Python 3.14 +
Starlette: необработанное исключение из BaseHTTPMiddleware всплывает как
ExceptionGroup мимо ServerErrorMiddleware, поэтому реальный 500-ответ
возможен только с raise_server_exceptions=False — см. приёмку 13.4-b).
Развёрнутый 500 через полный стек потребовал бы временного маршрута в
общем app.main.app (мутация singleton-объекта) — по ТЗ основное покрытие
UNIT-SMOKE, плюс один ASGI-кейс (404) для проверки интеграции стека.
TestClient в проекте ранее не использовался (см. test_webhook_telegram) —
здесь единственное оправданное исключение.

Инфраструктура — по образцу test_country_policy_integration: реальная
SQLite + alembic upgrade head (изолированный временный файл), SessionLocal
патчится на app.main (именно его открывает middleware). В приложении
ничего не меняется.

Изоляция: каждый тест чистит app_errors в тестовой БД (для детерминизма
счётчика записей) — игровые данные не затрагиваются.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "backend"


class AppErrorsMiddlewareTests(unittest.TestCase):
    """13.4-b: app_errors_middleware пишет AppError на необработанные 5xx."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-app-errors-middleware-"
        )
        cls.database_path = (
            Path(cls._temporary_directory.name) / "app_errors.sqlite3"
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
        cls.SessionLocal = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

        import app.main as main_module
        from app.models import AppError

        cls.model = AppError
        cls._main_module = main_module
        # Храним как staticmethod: простая ссылка на функцию на классе — это
        # descriptor, и вызов через self подставил бы self первым аргументом
        # (bound method), ломая сигнатуру (request, call_next).
        cls.middleware = staticmethod(main_module.app_errors_middleware)
        # middleware обращается к app.main.SessionLocal (module-level имя).
        cls._session_local_patch = patch.object(
            main_module, "SessionLocal", cls.SessionLocal
        )
        cls._session_local_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._session_local_patch.stop()
        cls.engine.dispose()
        cls._temporary_directory.cleanup()

    def setUp(self) -> None:
        """Очистить app_errors в тестовой БД: детерминизм счётчика записей."""
        with self.SessionLocal.begin() as session:
            session.execute(delete(self.model))

    # ---- Хелперы ---------------------------------------------------------

    @staticmethod
    def _call_next_raising(exception: Exception):
        """Обёртка синхронного исключения в async call_next."""

        async def _call_next(_request):
            raise exception

        return _call_next

    @staticmethod
    def _request(
        method: str = "GET",
        path: str = "/x",
        audit_context: dict | None = None,
        state: SimpleNamespace | None = None,
    ) -> SimpleNamespace:
        """Fake Request: только то, что читает middleware (method/url/state)."""
        if state is None:
            state = SimpleNamespace(audit_context=audit_context or {})
        return SimpleNamespace(
            state=state,
            method=method,
            url=SimpleNamespace(path=path),
        )

    # ---- Тесты -------------------------------------------------------------

    def test_5xx_writes_app_error(self) -> None:
        """Необработанный 5xx -> AppError записан, исключение проброшено.

        Проверяем error_type/message/safe_context и correlation_id из
        audit_context (основной путь — именно ТЗ 13.4-b).
        """
        request = self._request(
            method="GET",
            path="/x",
            audit_context={"correlation_id": "corr-123", "player_id": "player-abc"},
        )

        with self.assertRaises(RuntimeError):
            asyncio.run(
                self.middleware(
                    request, self._call_next_raising(RuntimeError("boom"))
                )
            )

        with self.SessionLocal() as session:
            rows = session.scalars(select(self.model)).all()

        self.assertEqual(len(rows), 1, "ровно одна запись AppError")
        row = rows[0]
        self.assertEqual(row.correlation_id, "corr-123")
        self.assertEqual(row.severity, "error")
        self.assertEqual(row.error_type, "RuntimeError")
        self.assertEqual(row.message, "boom")
        self.assertEqual(
            row.safe_context,
            {"method": "GET", "path": "/x"},
        )
        # M-2b: структурированные поля (endpoint/status_code/stack).
        self.assertEqual(row.endpoint, "/x")
        self.assertEqual(row.status_code, 500)
        self.assertEqual(row.player_id, "player-abc")
        self.assertIsNotNone(row.stack)
        self.assertIn("RuntimeError", row.stack)
        self.assertLessEqual(len(row.stack), 4000)

    def test_correlation_middleware_player_id_from_cookie(self) -> None:
        """M-2c: correlation_id_middleware кладёт player_id из cookie в audit_context.

        Три случая одним тестом:
          1. валидная cookie -> player_id из подписанного токена;
          2. нет cookie -> player_id = None;
          3. невалидная cookie -> player_id = None (try/except, без raise).
        """
        from app.telegram_auth import create_session_token

        secret = "test-session-secret"
        token = create_session_token("player-test", secret, 3600)
        main_module = self._main_module
        cookie_name = main_module.SESSION_COOKIE_NAME

        def _correlation_request(cookies: dict) -> SimpleNamespace:
            return SimpleNamespace(
                state=SimpleNamespace(),
                cookies=cookies,
                client=None,
                headers={"user-agent": "test-agent"},
            )

        async def _call_next_ok(_request):
            return SimpleNamespace(headers={})

        with patch.object(
            main_module,
            "settings",
            SimpleNamespace(game_session_secret=secret),
        ):
            # 1) Валидная cookie -> player_id из токена.
            request = _correlation_request({cookie_name: token})
            response = asyncio.run(
                main_module.correlation_id_middleware(request, _call_next_ok)
            )
            self.assertEqual(
                request.state.audit_context["player_id"], "player-test"
            )
            self.assertIn("X-Correlation-ID", response.headers)

            # 2) Нет cookie -> player_id None.
            request_without = _correlation_request({})
            asyncio.run(
                main_module.correlation_id_middleware(
                    request_without, _call_next_ok
                )
            )
            self.assertIsNone(request_without.state.audit_context["player_id"])

            # 3) Невалидная cookie -> player_id None (try/except).
            request_invalid = _correlation_request({cookie_name: "garbage"})
            asyncio.run(
                main_module.correlation_id_middleware(
                    request_invalid, _call_next_ok
                )
            )
            self.assertIsNone(request_invalid.state.audit_context["player_id"])

    def test_4xx_not_written(self) -> None:
        """HTTPException (4xx) пробрасывается, AppError НЕ пишется."""
        request = self._request(
            method="POST",
            path="/y",
            audit_context={"correlation_id": "corr-123"},
        )

        with self.assertRaises(HTTPException) as context:
            asyncio.run(
                self.middleware(
                    request,
                    self._call_next_raising(HTTPException(422, "bad")),
                )
            )

        self.assertEqual(context.exception.status_code, 422)

        with self.SessionLocal() as session:
            rows = session.scalars(select(self.model)).all()
        self.assertEqual(rows, [], "4xx не должен писать в app_errors")

    def test_correlation_id_fallback_when_audit_context_missing(self) -> None:
        """Нет correlation_id в state -> fallback uuid4().hex (32 hex-символа)."""
        # Вариант 1: audit_context есть, но correlation_id в нём нет.
        with self.assertRaises(RuntimeError):
            asyncio.run(
                self.middleware(
                    self._request(audit_context={"ip_address": "8.8.8.8"}),
                    self._call_next_raising(RuntimeError("boom-1")),
                )
            )

        # Вариант 2: state есть, но атрибута audit_context нет вовсе.
        with self.assertRaises(RuntimeError):
            asyncio.run(
                self.middleware(
                    self._request(state=SimpleNamespace()),
                    self._call_next_raising(RuntimeError("boom-2")),
                )
            )

        with self.SessionLocal() as session:
            rows = session.scalars(select(self.model)).all()

        self.assertEqual(len(rows), 2, "обе ошибки записаны (fallback)")
        for row in rows:
            self.assertEqual(
                len(row.correlation_id), 32, "uuid4().hex даёт 32 hex-символа"
            )
            self.assertTrue(
                set(row.correlation_id) <= set("0123456789abcdef"),
                "correlation_id обязан быть uuid4().hex",
            )
            self.assertNotIn(
                row.correlation_id, (None, ""), "fallback не должен быть пустым"
            )

    def test_404_through_full_stack_not_written(self) -> None:
        """Полный ASGI-стек: 404 на несуществующий путь -> 0 записей.

        Единственный целостный кейс через TestClient (raise_server_exceptions
        не играет роли: 404 — штатный ответ, а не исключение). 500 через
        полный стек потребовал бы временного 5xx-маршрута в общем
        app.main.app (мутация singleton) — по ТЗ пропускаем; запись на 5xx
        покрыта UNIT-SMOKE (test_5xx_writes_app_error).
        """
        client = TestClient(self._main_module.app, raise_server_exceptions=False)

        response = client.get("/__app_errors_middleware_missing_404__")

        self.assertEqual(response.status_code, 404)

        with self.SessionLocal() as session:
            rows = session.scalars(select(self.model)).all()
        self.assertEqual(rows, [], "404 через полный стек не пишет в app_errors")
