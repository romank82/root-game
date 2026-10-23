"""Этап 10.5-a — PG-тесты перевода ROOT (transfer_service.transfer_root).

Сервис перевода (10.5-a): атомарный debit/credit, лимиты из CMS, порог
earned (только mission_reward-кредиты), daily-лимит (UTC-сутки),
идемпотентность по (from_player_id, request_id), детерминированная
блокировка двух кошельков (sorted по player_id), transfer_restricted/
blocked/suspended. Инфраструктура — по образцу test_economy_pg_9_3_1:
чистая PG-схема через alembic upgrade head на chimera_test (порт 5433),
SessionLocal патчится на PG; без PG — unittest.skipTest (локальный
SQLite-прогон не ломается).

Покрывает:
  1. test_transfer_success — успешный перевод: балансы, ledger, PlayerTransfer;
  2. test_transfer_idempotent — повторный request_id без двойного списания;
  3. test_transfer_errors — 422/404/403/409 + ROLLBACK (баланс не меняется);
  4. test_transfer_daily_limit — 5x1000 при daily=5000, 6-й -> 429;
  5. test_transfer_parallel_no_overspend — 2 потока с одного кошелька,
     FOR UPDATE сериализует, без ухода в минус, ledger сходится.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

from app.mission_engine import MissionEngineError
from app.transfer_service import transfer_root

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Отдельный тестовый PG на порту 5433 (docker-compose: db-test), чтобы не
# конфликтовать с dev-БД на 5432. Переопределяется через PG_TEST_DATABASE_URL.
PG_URL = os.environ.get(
    "PG_TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5433/chimera_test",
)

TRANSFER_MIN_KEY = "economy.transfer_min_amount"
TRANSFER_MAX_KEY = "economy.transfer_max_amount"
DAILY_TRANSFER_LIMIT_KEY = "economy.daily_transfer_limit"
TRANSFER_MINIMUM_EARNED_ROOT_KEY = "economy.transfer_minimum_earned_root"


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


class TransferPg105Tests(unittest.TestCase):
    """10.5-a: перевод ROOT между игроками на PostgreSQL."""

    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модули; SessionLocal патчится на PG в setUp."""
        from app import db, transfer_service

        cls.db_module = db
        cls.transfer_service = transfer_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Чистая PG-схема + alembic upgrade head + патч SessionLocal.

        Патчатся ДВА канала SessionLocal:
          - app.db.SessionLocal — ленивые импорты на момент вызова;
          - app.transfer_service.SessionLocal — module-level импорт на старте
            модуля (используется entrypoint-ом).
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
            patch.object(self.transfer_service, "SessionLocal", self.SessionLocal),
        ]
        for session_local_patch in self._session_local_patches:
            session_local_patch.start()

    def tearDown(self) -> None:
        for session_local_patch in self._session_local_patches:
            session_local_patch.stop()
        self.engine.dispose()

    # ---- Хелперы: игрок / кошелёк / CMS / баланс --------------------------

    def _make_player(self, session, suffix: str, status: str = "active") -> str:
        """Игрок GamePlayer (status по умолчанию active)."""
        from app.models import GamePlayer

        player_id = f"pg-player-{uuid.uuid4().hex[:10]}"
        session.add(
            GamePlayer(
                id=player_id,
                display_name=f"PG 10.5 {suffix}",
                auth_provider="test",
                external_id=f"test-{uuid.uuid4().hex}",
                status=status,
            )
        )
        session.flush()  # FK: wallets.player_id -> game_players
        return player_id

    def _seed_wallet(
        self,
        session,
        player_id: str,
        balance: int,
        reference_type: str = "mission_reward",
    ) -> str:
        """Кошелёк ROOT с credit-проводкой = balance (ledger — source of truth).

        По умолчанию reference_type="mission_reward" — даёт earned (порог 50).
        Для кейса earned<50 передать другой reference_type (например test_seed).
        """
        from app.models import Wallet, WalletTransaction

        wallet_id = f"wallet-{uuid.uuid4().hex}"
        session.add(
            Wallet(
                id=wallet_id,
                player_id=player_id,
                currency="ROOT",
                available_balance=balance,
                locked_balance=0,
            )
        )
        session.flush()  # FK: wallet_transactions.wallet_id -> wallets
        session.add(
            WalletTransaction(
                id=f"wallet-transaction-{uuid.uuid4().hex}",
                wallet_id=wallet_id,
                amount=balance,
                balance_after=balance,
                transaction_type="credit",
                reason="PG 10.5 transfer seed",
                reference_type=reference_type,
                reference_id=f"seed-{uuid.uuid4().hex}",
                metadata_json={},
            )
        )
        return wallet_id

    def _ensure_cms_settings(self, session, overrides: dict | None = None) -> None:
        """4 настройки перевода в статусе active (CMS-first); overrides меняют
        значения каталога по ключу."""
        from app.models import SystemSetting

        defaults = {
            TRANSFER_MIN_KEY: 1,
            TRANSFER_MAX_KEY: 10000,
            DAILY_TRANSFER_LIMIT_KEY: 50000,
            TRANSFER_MINIMUM_EARNED_ROOT_KEY: 50,
        }
        if overrides:
            defaults.update(overrides)
        for key, value in defaults.items():
            existing = session.get(SystemSetting, key)
            if existing is None:
                session.add(
                    SystemSetting(
                        key=key,
                        value_json=value,
                        value_type="integer",
                        category="economy",
                        title=key,
                        description="Seeded by PG 10.5 transfer test",
                        is_sensitive=True,
                        status="active",
                    )
                )
            else:
                existing.value_json = value
                existing.status = "active"

    def _root_balance(self, player_id: str) -> int:
        """available_balance кошелька ROOT игрока (0, если кошелька нет)."""
        from app.models import Wallet

        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            return wallet.available_balance if wallet is not None else 0


    # ---- Тесты ------------------------------------------------------------

    def test_transfer_success(self) -> None:
        """Успешный перевод: балансы, ledger (debit/credit), PlayerTransfer."""
        from app.models import PlayerTransfer, WalletTransaction

        with self.SessionLocal.begin() as session:
            self._ensure_cms_settings(session)
            p1 = self._make_player(session, "sender")
            p2 = self._make_player(session, "recipient")
            w1 = self._seed_wallet(session, p1, 1000)  # earned=1000
            w2 = self._seed_wallet(session, p2, 500)

            result = transfer_root(session, p1, p2, 100, "req-1")

            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["transferId"].startswith("player-transfer-"))
            self.assertEqual(result["fromPlayerId"], p1)
            self.assertEqual(result["toPlayerId"], p2)
            self.assertEqual(result["amount"], 100)
            self.assertEqual(result["fromBalance"], 900)
            self.assertEqual(result["toBalance"], 600)

            pt = session.scalar(
                select(PlayerTransfer).where(
                    PlayerTransfer.from_player_id == p1,
                    PlayerTransfer.reference_id == "req-1",
                )
            )
            self.assertIsNotNone(pt, "PlayerTransfer не создан")
            self.assertEqual(pt.status, "completed")
            self.assertEqual(pt.amount, 100)
            self.assertEqual(pt.to_player_id, p2)

            debit = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == w1,
                    WalletTransaction.transaction_type == "debit",
                    WalletTransaction.reference_type == "player_transfer_debit",
                    WalletTransaction.reference_id == "req-1",
                )
            )
            credit = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == w2,
                    WalletTransaction.transaction_type == "credit",
                    WalletTransaction.reference_type == "player_transfer_credit",
                    WalletTransaction.reference_id == "req-1",
                )
            )
            self.assertEqual(debit, 1)
            self.assertEqual(credit, 1)

        # Коммит произошёл (SessionLocal.begin) — проверяем пост-фактум.
        self.assertEqual(self._root_balance(p1), 900)
        self.assertEqual(self._root_balance(p2), 600)

    def test_transfer_idempotent(self) -> None:
        """Повторный request_id — тот же transferId, без двойного списания."""
        from app.models import PlayerTransfer, WalletTransaction

        with self.SessionLocal.begin() as session:
            self._ensure_cms_settings(session)
            p1 = self._make_player(session, "sender")
            p2 = self._make_player(session, "recipient")
            w1 = self._seed_wallet(session, p1, 1000)
            w2 = self._seed_wallet(session, p2, 500)
            first = transfer_root(session, p1, p2, 100, "req-1")

        # Новый вызов (другая транзакция) с тем же request_id.
        with self.SessionLocal.begin() as session:
            second = transfer_root(session, p1, p2, 100, "req-1")

        self.assertEqual(second["transferId"], first["transferId"])
        self.assertEqual(second["status"], "completed")
        self.assertEqual(second["fromBalance"], 900)
        self.assertEqual(second["toBalance"], 600)
        self.assertEqual(self._root_balance(p1), 900)
        self.assertEqual(self._root_balance(p2), 600)

        with self.SessionLocal() as session:
            pt_count = session.scalar(
                select(func.count(PlayerTransfer.id)).where(
                    PlayerTransfer.from_player_id == p1,
                    PlayerTransfer.reference_id == "req-1",
                )
            )
            debit = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == w1,
                    WalletTransaction.transaction_type == "debit",
                    WalletTransaction.reference_type == "player_transfer_debit",
                    WalletTransaction.reference_id == "req-1",
                )
            )
            credit = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == w2,
                    WalletTransaction.transaction_type == "credit",
                    WalletTransaction.reference_type == "player_transfer_credit",
                    WalletTransaction.reference_id == "req-1",
                )
            )
        self.assertEqual(pt_count, 1)
        self.assertEqual(debit, 1)
        self.assertEqual(credit, 1)


    def test_transfer_errors(self) -> None:
        """Ошибки: себе 422, нет получателя 404, blocked 403, transfer_restricted
        403, min/max 422, earned<50 403, баланс<amount 409. После каждой
        ошибки баланс не изменился (транзакция откатилась — ROLLBACK)."""
        from app.models import AdminUser, PlayerRestriction

        # 1. перевод самому себе -> 422
        with self.SessionLocal.begin() as session:
            p_self = self._make_player(session, "self")
            self._seed_wallet(session, p_self, 1000)
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_self, p_self, 100, "req-self")
            self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self._root_balance(p_self), 1000)

        # 2. получатель не существует -> 404
        with self.SessionLocal.begin() as session:
            p_nf = self._make_player(session, "nf-sender")
            self._seed_wallet(session, p_nf, 1000)
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_nf, "no-such-player", 100, "req-nf")
            self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self._root_balance(p_nf), 1000)

        # 3. получатель status='blocked' -> 403
        with self.SessionLocal.begin() as session:
            p_blk = self._make_player(session, "blk-sender")
            self._seed_wallet(session, p_blk, 1000)
            p_blocked = self._make_player(session, "blk-recipient", status="blocked")
            self._seed_wallet(session, p_blocked, 0)
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_blk, p_blocked, 100, "req-blk")
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self._root_balance(p_blk), 1000)

        # 4. отправитель transfer_restricted -> 403 (нужен admin для FK)
        admin_id = f"admin-{uuid.uuid4().hex[:8]}"
        with self.SessionLocal.begin() as session:
            if session.get(AdminUser, admin_id) is None:
                session.add(
                    AdminUser(
                        id=admin_id,
                        username=f"admin-{uuid.uuid4().hex[:8]}",
                        password_hash="test-not-a-real-hash",
                        role="admin",
                        is_super_admin=True,
                        is_active=True,
                        is_deleted=False,
                    )
                )
            p_tr = self._make_player(session, "restricted-sender")
            self._seed_wallet(session, p_tr, 1000)
            p_tr_r = self._make_player(session, "restricted-recipient")
            self._seed_wallet(session, p_tr_r, 0)
            session.add(
                PlayerRestriction(
                    id=f"pr-{uuid.uuid4().hex}",
                    player_id=p_tr,
                    restriction_type="transfer_restricted",
                    status="active",
                    reason="PG 10.5 transfer test",
                    admin_id=admin_id,
                )
            )
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_tr, p_tr_r, 100, "req-tr")
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self._root_balance(p_tr), 1000)

        # 5. сумма < min (0) -> 422; сумма > max (10001) -> 422
        with self.SessionLocal.begin() as session:
            self._ensure_cms_settings(session)
            p_mm = self._make_player(session, "minmax-sender")
            self._seed_wallet(session, p_mm, 1000)
            p_mm_r = self._make_player(session, "minmax-recipient")
            self._seed_wallet(session, p_mm_r, 0)
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_mm, p_mm_r, 0, "req-min")
            self.assertEqual(ctx.exception.status_code, 422)
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_mm, p_mm_r, 10001, "req-max")
            self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(self._root_balance(p_mm), 1000)

        # 6. earned < 50 -> 403 (seed не mission_reward => earned=0)
        with self.SessionLocal.begin() as session:
            self._ensure_cms_settings(session)
            p_er = self._make_player(session, "earned-sender")
            self._seed_wallet(session, p_er, 10, reference_type="test_seed")
            p_er_r = self._make_player(session, "earned-recipient")
            self._seed_wallet(session, p_er_r, 0)
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_er, p_er_r, 10, "req-earned")
            self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(self._root_balance(p_er), 10)

        # 7. баланс < amount -> 409
        with self.SessionLocal.begin() as session:
            self._ensure_cms_settings(session)
            p_bs = self._make_player(session, "balshort-sender")
            self._seed_wallet(session, p_bs, 100)
            p_bs_r = self._make_player(session, "balshort-recipient")
            self._seed_wallet(session, p_bs_r, 0)
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p_bs, p_bs_r, 200, "req-balshort")
            self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(self._root_balance(p_bs), 100)


    def test_transfer_daily_limit(self) -> None:
        """Daily=5000: 5x1000 успешно, 6-й -> 429 (системная ошибка, откат)."""
        from app.models import PlayerTransfer

        with self.SessionLocal.begin() as session:
            self._ensure_cms_settings(
                session, overrides={DAILY_TRANSFER_LIMIT_KEY: 5000}
            )
            p1 = self._make_player(session, "daily-sender")
            self._seed_wallet(session, p1, 10000)  # earned=10000
            p2 = self._make_player(session, "daily-recipient")
            self._seed_wallet(session, p2, 0)

        for index in range(1, 6):
            with self.SessionLocal.begin() as session:
                result = transfer_root(session, p1, p2, 1000, f"req-d-{index}")
            self.assertEqual(result["status"], "completed")

        self.assertEqual(self._root_balance(p1), 5000)
        self.assertEqual(self._root_balance(p2), 5000)

        # 6-й перевод за сутки: 5000+1000 = 6000 > 5000 -> 429
        with self.SessionLocal.begin() as session:
            with self.assertRaises(MissionEngineError) as ctx:
                transfer_root(session, p1, p2, 1000, "req-d-6")
            self.assertEqual(ctx.exception.status_code, 429)

        # Откат: баланс не изменился, закоммичено ровно 5 переводов.
        self.assertEqual(self._root_balance(p1), 5000)
        with self.SessionLocal() as session:
            count = session.scalar(
                select(func.count(PlayerTransfer.id)).where(
                    PlayerTransfer.from_player_id == p1,
                    PlayerTransfer.status == "completed",
                )
            )
        self.assertEqual(count, 5)

    def test_transfer_parallel_no_overspend(self) -> None:
        """2 потока с одного кошелька (400+400 при балансе 1000): FOR UPDATE
        сериализует, оба успешны, P1=200 без минуса, ledger сходится.

        Синхронизация старта — threading.Barrier(2) (максимальная гонка),
        без sleep-костылей. Оба потока — отдельные транзакции
        (with self.SessionLocal.begin()).
        """
        from app.models import PlayerTransfer, WalletTransaction

        with self.SessionLocal.begin() as session:
            self._ensure_cms_settings(session)
            p1 = self._make_player(session, "parallel-sender")
            w1 = self._seed_wallet(session, p1, 1000)  # earned=1000
            p2 = self._make_player(session, "parallel-r1")
            w2 = self._seed_wallet(session, p2, 0)
            p3 = self._make_player(session, "parallel-r2")
            w3 = self._seed_wallet(session, p3, 0)

        barrier = threading.Barrier(2)
        outcomes: list[tuple[str, str | None]] = []
        outcomes_lock = threading.Lock()

        def sender(recipient: str, request_id: str) -> None:
            barrier.wait()
            try:
                with self.SessionLocal.begin() as session:
                    transfer_root(session, p1, recipient, 400, request_id)
                outcome = ("success", None)
            except Exception as exc:  # noqa: BLE001 — классы собираем в отчёт
                outcome = (type(exc).__name__, str(exc))
            with outcomes_lock:
                outcomes.append(outcome)

        threads = [
            threading.Thread(target=sender, args=(p2, "req-a"), name="transfer-a"),
            threading.Thread(target=sender, args=(p3, "req-b"), name="transfer-b"),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        successes = sum(1 for name, _ in outcomes if name == "success")
        errors = [
            f"{name}: {detail}" for name, detail in outcomes if name != "success"
        ]
        self.assertEqual(
            successes,
            2,
            f"Ожидали 2 успеха, получили {successes}; errors={errors}",
        )

        self.assertEqual(self._root_balance(p1), 200)
        self.assertEqual(self._root_balance(p2), 400)
        self.assertEqual(self._root_balance(p3), 400)

        with self.SessionLocal() as session:
            transfer_count = session.scalar(
                select(func.count(PlayerTransfer.id)).where(
                    PlayerTransfer.from_player_id == p1,
                    PlayerTransfer.status == "completed",
                )
            )
            debit_count = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == w1,
                    WalletTransaction.transaction_type == "debit",
                    WalletTransaction.reference_type == "player_transfer_debit",
                )
            )
            credit_p2 = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == w2,
                    WalletTransaction.transaction_type == "credit",
                    WalletTransaction.reference_type == "player_transfer_credit",
                )
            )
            credit_p3 = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == w3,
                    WalletTransaction.transaction_type == "credit",
                    WalletTransaction.reference_type == "player_transfer_credit",
                )
            )
        self.assertEqual(transfer_count, 2)
        self.assertEqual(debit_count, 2)
        self.assertEqual(credit_p2, 1)
        self.assertEqual(credit_p3, 1)

