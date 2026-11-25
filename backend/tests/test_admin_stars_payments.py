"""Тесты GET /api/v1/admin/economy/stars-payments (Sprint 12.2, журнал Stars).

Инфраструктура — паттерн test_admin_economy.py: на каждый тест свежая
disposable SQLite + alembic upgrade head (триггеры и CHECK-constraints из
миграций), SessionLocal модуля admin_economy патчится на неё. Эндпоинт
вызывается напрямую (list_stars_payments), поэтому право economy.read
проверяется отдельным тестом через сам dependency require_permission —
это ровно тот гейт, что стоит на роуте в проде (прямой вызов функции его
минует).

Покрывает:
  1. пустой журнал -> items=[], total=0;
  2. три платежа -> порядок created_at desc, сериализация (gasAmount строкой,
     telegramPaymentChargeId = null до successful_payment);
  3. фильтр status=completed;
  4. фильтр player_id (точное совпадение);
  5. search по reference_id / telegram_payment_charge_id / payload
     (ILIKE — регистронезависимо);
  6. диапазон from/to по created_at;
  7. пагинация limit/offset (total — общее число, не размер страницы);
  8. без гранта economy.read -> 403, с грантом -> доступ есть;
  9. неизвестный status -> 422;
 10. некорректная дата в from -> 422;
 11. read-only: число строк stars_payments после вызовов не меняется.
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

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import sessionmaker

from app.admin_access import DIRECT_EXECUTION_MODE, require_permission
from app.admin_economy import ECONOMY_READ_PERMISSION, list_stars_payments

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# База для created_at: фиксированные моменты, чтобы порядок и диапазоны
# не зависели от текущего времени.
BASE_CREATED_AT = datetime(2026, 11, 1, 10, 0, tzinfo=timezone.utc)


class AdminStarsPaymentsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модуль; SessionLocal патчится на свежую БД в setUp."""
        from app import admin_economy

        cls.admin_economy = admin_economy
        cls._session_local_patch = None
        cls._admin_access_session_local_patch = None

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-admin-stars-payments-tests-"
        )
        self.database_path = Path(self._temporary_directory.name) / "admin.sqlite3"
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
            self.admin_economy, "SessionLocal", self.SessionLocal
        )
        self._session_local_patch.start()

        # require_permission (app.admin_access) читает гранты через свой
        # импортированный SessionLocal — патчим его на ту же тестовую БД,
        # чтобы проверка права не зависела от локальной chimera.db.
        from app import admin_access

        self._admin_access_session_local_patch = patch.object(
            admin_access, "SessionLocal", self.SessionLocal
        )
        self._admin_access_session_local_patch.start()

    def tearDown(self) -> None:
        self._admin_access_session_local_patch.stop()
        self._session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

# ---- Fixtures и хелперы -------------------------------------------------

    def _make_admin(self, is_super_admin: bool = True):
        from app.models import AdminUser

        admin_id = f"admin-{uuid.uuid4().hex}"
        with self.SessionLocal.begin() as session:
            session.add(
                AdminUser(
                    id=admin_id,
                    username=f"admin-{admin_id[-6:]}",
                    password_hash="test-hash",
                    role="super_admin" if is_super_admin else "admin",
                    is_super_admin=is_super_admin,
                    is_active=True,
                    is_deleted=False,
                )
            )
        with self.SessionLocal() as session:
            return session.get(AdminUser, admin_id)

    def _grant(self, admin_id: str, permission_code: str) -> None:
        from app.models import AdminUserPermission

        with self.SessionLocal.begin() as session:
            session.add(
                AdminUserPermission(
                    id=f"grant-{uuid.uuid4().hex}",
                    admin_user_id=admin_id,
                    permission_code=permission_code,
                    execution_mode=DIRECT_EXECUTION_MODE,
                    is_active=True,
                )
            )

    def _make_player(
        self,
        player_id: str,
        *,
        display_name: str | None = None,
        telegram_username: str | None = None,
        telegram_first_name: str | None = None,
        nickname: str | None = None,
        nickname_lower: str | None = None,
    ) -> str:
        """Игрок с заданным id: player_id фиксирован — на нём фильтр и FK.

        display_name по умолчанию «Stars player <id>» (как до Sprint
        12.2-enhance) — чтобы _seed_three и старые тесты не меняли ожиданий.
        Остальные поля нужны для player_search (ник/имя/@username): по
        умолчанию NULL.
        """
        from app.models import GamePlayer

        resolved_display_name = (
            display_name if display_name is not None else f"Stars player {player_id}"
        )
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name=resolved_display_name,
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    telegram_username=telegram_username,
                    telegram_first_name=telegram_first_name,
                    nickname=nickname,
                    nickname_lower=nickname_lower,
                    status="active",
                )
            )
        return player_id

    def _make_payment(
        self,
        player_id: str,
        *,
        gas_amount: int = 100,
        amount_stars: int = 40,
        status: str = "pending",
        charge_id: str | None = None,
        reference_id: str | None = None,
        payload: str | None = None,
        created_at: datetime | None = None,
    ) -> str:
        """Одна запись stars_payments = один инвойс (10.4-g-1).

        unique(reference_id) — у каждой записи свой номер инвойса.
        payload по умолчанию равен reference_id (так делает stars_service).
        """
        from app.models import StarsPayment

        payment_id = f"stars-payment-{uuid.uuid4().hex}"
        reference = reference_id or f"stars-invoice-{uuid.uuid4().hex[:8]}"
        moment = created_at or BASE_CREATED_AT
        with self.SessionLocal.begin() as session:
            session.add(
                StarsPayment(
                    id=payment_id,
                    player_id=player_id,
                    gas_amount=gas_amount,
                    amount_stars=amount_stars,
                    telegram_payment_charge_id=charge_id,
                    status=status,
                    reference_id=reference,
                    payload=payload if payload is not None else reference,
                    created_at=moment,
                    updated_at=moment,
                )
            )
        return payment_id

    def _seed_three(self) -> tuple[str, str, str]:
        """3 платежа: player-a/pending (1 ноя), player-b/completed (5 ноя),
        player-a/refunded (9 ноя). Возвращает (payment_1, payment_2, payment_3).
        """
        self._make_player("player-a")
        self._make_player("player-b")

        payment_1 = self._make_payment(
            "player-a",
            gas_amount=10,
            amount_stars=5,
            status="pending",
            reference_id="stars-invoice-1",
            created_at=BASE_CREATED_AT,
        )
        payment_2 = self._make_payment(
            "player-b",
            gas_amount=100,
            amount_stars=40,
            status="completed",
            charge_id="charge-ABC",
            reference_id="stars-invoice-2",
            created_at=BASE_CREATED_AT + timedelta(days=4),
        )
        payment_3 = self._make_payment(
            "player-a",
            gas_amount=1000,
            amount_stars=300,
            status="refunded",
            charge_id="charge-XYZ",
            reference_id="stars-invoice-3",
            created_at=BASE_CREATED_AT + timedelta(days=8),
        )
        return payment_1, payment_2, payment_3

# ---- Тесты --------------------------------------------------------------

    def test_list_stars_payments_empty(self) -> None:
        """Пустой журнал: items=[], total=0 (ошибок на пустой таблице нет)."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)

        result = list_stars_payments(admin=admin)

        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["limit"], 50)
        self.assertEqual(result["offset"], 0)

    def test_list_stars_payments_all(self) -> None:
        """Три платежа: порядок created_at desc и контракт полей записи."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        payment_1, payment_2, payment_3 = self._seed_three()

        result = list_stars_payments(admin=admin)

        self.assertEqual(result["total"], 3)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(
            [item["id"] for item in result["items"]],
            [payment_3, payment_2, payment_1],
        )

        newest = result["items"][0]
        self.assertEqual(newest["playerId"], "player-a")
        self.assertEqual(newest["amountStars"], 300)
        # gas_amount — Numeric(18,4): отдаётся строкой, без потери точности.
        self.assertEqual(newest["gasAmount"], "1000.0000")
        self.assertEqual(newest["status"], "refunded")
        self.assertEqual(newest["telegramPaymentChargeId"], "charge-XYZ")
        self.assertEqual(newest["referenceId"], "stars-invoice-3")
        self.assertEqual(newest["payload"], "stars-invoice-3")
        self.assertTrue(newest["createdAt"].startswith("2026-11-09T10:00:00"))

        # charge_id заполняется только на successful_payment -> pending = null.
        oldest = result["items"][2]
        self.assertIsNone(oldest["telegramPaymentChargeId"])
        self.assertEqual(oldest["status"], "pending")

        # Sprint 12.2-enhance: playerDisplayName приходит из JOIN с GamePlayer
        # (в _seed_three display_name = «Stars player <player_id>»).
        self.assertTrue(
            all("playerDisplayName" in item for item in result["items"])
        )
        self.assertEqual(newest["playerDisplayName"], "Stars player player-a")

    def test_list_stars_payments_includes_player_nickname(self) -> None:
        """В журнале Stars есть читаемый ник игрока.

        playerId админу ничего не говорит — по нему игрока в интерфейсе не
        найти. Показывается ник вида «roman#491-773-811» со ссылкой на
        карточку.
        """
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._seed_three()

        from sqlalchemy import update

        from app.models import GamePlayer

        nickname = "roman#491-773-811"
        with self.SessionLocal.begin() as session:
            session.execute(
                update(GamePlayer)
                .where(GamePlayer.id == "player-a")
                .values(nickname=nickname, nickname_lower=nickname.lower())
            )

        result = list_stars_payments(admin=admin)

        by_player = [i for i in result["items"] if i["playerId"] == "player-a"]
        self.assertTrue(by_player)
        for item in by_player:
            self.assertEqual(item["playerNickname"], nickname)

        # player-b ник не задавали -> поле есть и равно null, не падает.
        other = [i for i in result["items"] if i["playerId"] == "player-b"]
        self.assertTrue(other)
        self.assertIsNone(other[0]["playerNickname"])

    def test_list_stars_payments_filter_status(self) -> None:
        """status=completed -> только completed, total=1."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        _, payment_2, _ = self._seed_three()

        result = list_stars_payments(admin=admin, status="completed")

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["id"] for item in result["items"]], [payment_2])
        self.assertEqual(result["items"][0]["status"], "completed")

    def test_list_stars_payments_filter_player_id(self) -> None:
        """player_id=player-a -> только платежи player-a, total=2."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        payment_1, _, payment_3 = self._seed_three()

        result = list_stars_payments(admin=admin, player_id="player-a")

        self.assertEqual(result["total"], 2)
        self.assertEqual(
            {item["id"] for item in result["items"]},
            {payment_1, payment_3},
        )
        self.assertTrue(
            all(item["playerId"] == "player-a" for item in result["items"])
        )

        # Контроль: второй игрок виден по своему фильтру.
        other = list_stars_payments(admin=admin, player_id="player-b")
        self.assertEqual(other["total"], 1)
        self.assertEqual(other["items"][0]["playerId"], "player-b")

    def test_player_search_by_display_name(self) -> None:
        """player_search по display_name: подстрока (кириллица) + ILIKE (латиница)."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._make_player("player-a", display_name="Роман Петров")
        self._make_payment("player-a", reference_id="stars-invoice-search-1")

        result = list_stars_payments(admin=admin, player_search="Роман")

        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["playerId"], "player-a")
        self.assertEqual(result["items"][0]["playerDisplayName"], "Роман Петров")

        # Подстрока в середине имени (не только с начала) — тоже находит.
        middle = list_stars_payments(admin=admin, player_search="оман")
        self.assertEqual(middle["total"], 1)
        self.assertEqual(middle["items"][0]["playerId"], "player-a")

        # Регистронезависимость ILIKE проверяется на ЛАТИНИЦЕ: SQLite lower()
        # нормализует только ASCII (lower('Роман') == 'Роман'), поэтому
        # «рома» на SQLite не совпадает, а на PostgreSQL ILIKE совпал бы.
        # Диалект-независимый кейс — как в test_admin_economy.
        self._make_player("player-b", display_name="Roman Petrov")
        self._make_payment("player-b", reference_id="stars-invoice-search-1b")

        lower_latin = list_stars_payments(admin=admin, player_search="roman")
        self.assertEqual(lower_latin["total"], 1)
        self.assertEqual(lower_latin["items"][0]["playerId"], "player-b")
        self.assertEqual(lower_latin["items"][0]["playerDisplayName"], "Roman Petrov")

    def test_player_search_by_exact_id(self) -> None:
        """player_search с полным id — точное совпадение, не ILIKE."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._make_player("player-a", display_name="Роман")
        self._make_payment("player-a", reference_id="stars-invoice-search-2")

        by_id = list_stars_payments(admin=admin, player_search="player-a")
        self.assertEqual(by_id["total"], 1)
        self.assertEqual(by_id["items"][0]["playerId"], "player-a")

        # Нет такого игрока -> пусто (а не «все платежи»).
        missing = list_stars_payments(admin=admin, player_search="player-b")
        self.assertEqual(missing["total"], 0)

    def test_player_search_by_telegram_username(self) -> None:
        """player_search по telegram_username: подстрока и полный логин."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._make_player(
            "player-a", display_name="Роман", telegram_username="roman_p"
        )
        self._make_payment("player-a", reference_id="stars-invoice-search-3")

        substring = list_stars_payments(admin=admin, player_search="roman")
        self.assertEqual(substring["total"], 1)
        self.assertEqual(substring["items"][0]["playerId"], "player-a")

        full = list_stars_payments(admin=admin, player_search="roman_p")
        self.assertEqual(full["total"], 1)
        self.assertEqual(full["items"][0]["playerId"], "player-a")

        # @ — стандартный префикс Telegram-username, бэкенд срезает его
        # (Sprint 12.2-enhance-fix: strip -> removeprefix("@")), поэтому
        # «@roman_p» находит игрока с telegram_username="roman_p".
        with_at = list_stars_payments(admin=admin, player_search="@roman_p")
        self.assertEqual(with_at["total"], 1)
        self.assertEqual(with_at["items"][0]["playerId"], "player-a")

    def test_player_search_strips_at_prefix(self) -> None:
        """Ведущий @ срезается: @roman, roman и « @roman » находят игрока."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._make_player(
            "player-a", display_name="Роман", telegram_username="roman"
        )
        self._make_payment("player-a", reference_id="stars-invoice-search-at")

        for query in ("@roman", "roman", " @roman "):
            with self.subTest(player_search=query):
                result = list_stars_payments(admin=admin, player_search=query)
                self.assertEqual(result["total"], 1, query)
                self.assertEqual(result["items"][0]["playerId"], "player-a")

        # @ не «съедает» неподходящий логин: чужой ник даёт пусто.
        unknown = list_stars_payments(admin=admin, player_search="@anna")
        self.assertEqual(unknown["total"], 0)

    def test_player_search_empty_result(self) -> None:
        """player_search без совпадений -> total=0 и пустой items."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._make_player("player-a", display_name="Роман")
        self._make_payment("player-a", reference_id="stars-invoice-search-4")

        result = list_stars_payments(admin=admin, player_search="нет-такого")

        self.assertEqual(result["total"], 0)
        self.assertEqual(result["items"], [])

    def test_player_search_combined_with_status(self) -> None:
        """player_search комбинируется со status по AND (не OR)."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._make_player("player-a", display_name="Роман")
        self._make_payment(
            "player-a", status="pending", reference_id="stars-invoice-search-5a"
        )
        self._make_payment(
            "player-a", status="completed", reference_id="stars-invoice-search-5b"
        )

        completed = list_stars_payments(
            admin=admin, player_search="Роман", status="completed"
        )
        self.assertEqual(completed["total"], 1)
        self.assertEqual(completed["items"][0]["status"], "completed")

        pending = list_stars_payments(
            admin=admin, player_search="Роман", status="pending"
        )
        self.assertEqual(pending["total"], 1)
        self.assertEqual(pending["items"][0]["status"], "pending")

        # Контроль: без фильтра по игроку видно оба платежа.
        self.assertEqual(list_stars_payments(admin=admin)["total"], 2)

    def test_list_stars_payments_search(self) -> None:
        """search="charge" -> 2 записи (по charge_id), регистр не важен."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        _, payment_2, payment_3 = self._seed_three()

        result = list_stars_payments(admin=admin, search="charge")
        self.assertEqual(result["total"], 2)
        self.assertEqual(
            {item["id"] for item in result["items"]},
            {payment_2, payment_3},
        )

        # ILIKE: верхний регистр находит то же самое (проверка на PG и SQLite).
        upper = list_stars_payments(admin=admin, search="CHARGE")
        self.assertEqual(upper["total"], 2)

        # Поиск по reference_id (payload по умолчанию = reference_id).
        by_reference = list_stars_payments(admin=admin, search="stars-invoice-1")
        self.assertEqual(by_reference["total"], 1)
        self.assertEqual(by_reference["items"][0]["referenceId"], "stars-invoice-1")

    def test_list_stars_payments_date_range(self) -> None:
        """from/to по created_at: только платёж внутри выбранных суток."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        payment_1, payment_2, _ = self._seed_three()

        result = list_stars_payments(
            admin=admin,
            from_="2026-11-05T00:00:00",
            to="2026-11-05T23:59:59",
        )

        self.assertEqual(result["total"], 1)
        self.assertEqual([item["id"] for item in result["items"]], [payment_2])

        # Только from: всё, что не раньше 5 ноября (2 записи).
        from_only = list_stars_payments(admin=admin, from_="2026-11-05T00:00:00")
        self.assertEqual(from_only["total"], 2)

        # Только to: всё, что не позже 1 ноября (1 запись — самый старый).
        to_only = list_stars_payments(admin=admin, to="2026-11-01T23:59:59")
        self.assertEqual(to_only["total"], 1)
        self.assertEqual(to_only["items"][0]["id"], payment_1)

    def test_list_stars_payments_pagination(self) -> None:
        """limit=1&offset=1 -> второй по порядку платёж; total — общий."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        _, payment_2, _ = self._seed_three()

        page = list_stars_payments(admin=admin, limit=1, offset=1)

        self.assertEqual(page["total"], 3)  # total не зависит от размера страницы
        self.assertEqual(len(page["items"]), 1)
        self.assertEqual(page["items"][0]["id"], payment_2)
        self.assertEqual(page["limit"], 1)
        self.assertEqual(page["offset"], 1)

        # Клампинг как в /transactions: limit>200 -> 200, offset<0 -> 0.
        clamped = list_stars_payments(admin=admin, limit=999, offset=-5)
        self.assertEqual(clamped["limit"], 200)
        self.assertEqual(clamped["offset"], 0)
        self.assertEqual(clamped["total"], 3)

    def test_403_without_permission(self) -> None:
        """Без гранта economy.read -> 403; с грантом гейт открыт."""
        admin = self._make_admin(is_super_admin=False)

        # Ровно тот dependency, что стоит на роуте в проде: прямой вызов
        # функции list_stars_payments его минует (как в test_admin_economy).
        dependency = require_permission(ECONOMY_READ_PERMISSION)
        with self.assertRaises(HTTPException) as context:
            dependency(admin=admin)
        self.assertEqual(context.exception.status_code, 403)

        # Положительный контроль: с грантом тот же гейт отдаёт админа.
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        granted = dependency(admin=admin)
        self.assertEqual(granted.id, admin.id)

    def test_422_invalid_status(self) -> None:
        """Неизвестный status -> 422 (допустимые заданы CHECK-constraint)."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._seed_three()

        with self.assertRaises(HTTPException) as context:
            list_stars_payments(admin=admin, status="bogus")
        self.assertEqual(context.exception.status_code, 422)

        # Пустая строка — тоже 422: эндпоинт принимает только три значения из
        # CHECK-constraint. UI при «Все статусы» параметр не отправляет
        # (undefined), поэтому такой запрос возможен лишь вручную.
        with self.assertRaises(HTTPException) as empty_context:
            list_stars_payments(admin=admin, status="")
        self.assertEqual(empty_context.exception.status_code, 422)

    def test_422_invalid_date(self) -> None:
        """Некорректная ISO-дата в from/to -> 422."""
        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._seed_three()

        with self.assertRaises(HTTPException) as context:
            list_stars_payments(admin=admin, from_="not-a-date")
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("from", context.exception.detail)

        with self.assertRaises(HTTPException) as context:
            list_stars_payments(admin=admin, to="2026-11-32")
        self.assertEqual(context.exception.status_code, 422)
        self.assertIn("to", context.exception.detail)

    def test_list_stars_payments_no_mutations(self) -> None:
        """Read-only: число строк stars_payments после вызовов не меняется."""
        from app.models import StarsPayment

        admin = self._make_admin()
        self._grant(admin.id, ECONOMY_READ_PERMISSION)
        self._seed_three()

        def count_rows() -> int:
            with self.SessionLocal() as session:
                return (
                    session.scalar(select(func.count()).select_from(StarsPayment)) or 0
                )

        before = count_rows()
        list_stars_payments(admin=admin)
        list_stars_payments(admin=admin, status="completed")
        list_stars_payments(admin=admin, search="stars-invoice")
        list_stars_payments(admin=admin, limit=1, offset=2)

        self.assertEqual(before, 3)
        self.assertEqual(count_rows(), before)
