"""Этап 9.3.1 — ИНФРАСТРУКТУРА параллельных финансовых тестов на PostgreSQL.

Текущий шаг — только каркас (Sprint 9.3.1, шаг 1):
  - схема поднимается alembic upgrade head на отдельной тестовой БД
    chimera_test (docker-compose: сервис db-test, порт 5433);
  - SessionLocal патчится на PG по образцу test_economy_9_3.py
    (четыре канала: app.db, mission_engine, shop_service, fallback_shop);
  - тест мягкий к отсутствию PG: если localhost:5433 недоступен — skip
    (unittest.skipTest в setUp), локальный SQLite-прогон не ломается.

Покрывает два теста:
  1. test_pg_infrastructure_ready — схема на PostgreSQL мигрирует
     (alembic_version + ключевые таблицы);
  2. test_concurrent_shop_purchase_no_overspend — параллельная покупка
     ключа одной позиции: N потоков на общий кошелёк, FOR UPDATE
     сериализует, без ухода в минус, ledger сходится.
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

    def test_concurrent_shop_purchase_no_overspend(self) -> None:
        """N=5 потоков покупают одну позицию на кошельке с 100 ROOT, цена 40.

        Цель: FOR UPDATE на кошельке (shop_service._get_root_wallet_for_update,
        берется до расчёта reference_id) сериализует конкурентные покупки
        одного игрока. Ожидаемо ровно floor(100/40)=2 успеха, остальные —
        отказ; без ухода в минус, ledger сходится, reference_id не дублируются.

        Синхронизация старта — threading.Barrier(N) (максимальная гонка),
        без sleep-костылей. Ожидаемые классы ошибок проигравших потоков:
        MissionEngineError (409 «Недостаточно ROOT») или IntegrityError —
        любой из них допустим и фиксируется в отчёте; любой ДРУГОЙ класс
        роняет тест с понятным сообщением.
        """
        from app.models import (
            GamePlayer,
            Item,
            SystemSetting,
            Wallet,
            WalletTransaction,
        )
        from app.shop_service import SHOP_ENABLED_KEY, SHOP_PRICE_ROOT_KEY

        player_id = "pg-test-player"
        wallet_id = f"wallet-{uuid.uuid4().hex}"
        item_id = f"item-{uuid.uuid4().hex}"
        initial_balance = 100
        price = 40
        purchases = 5

        # ---- Подготовка (за одну транзакцию): игрок + кошелёк с seed-кредитом
        # (ledger — source of truth, чтобы SUM(credit)-SUM(debit) сходился) +
        # published KEY-item + системные настройки магазина (CMS-first).
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="PG 9.3.1 concurrency player",
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    status="active",
                )
            )
            session.add(
                Wallet(
                    id=wallet_id,
                    player_id=player_id,
                    currency="ROOT",
                    available_balance=initial_balance,
                    locked_balance=0,
                )
            )
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet_id,
                    amount=initial_balance,
                    balance_after=initial_balance,
                    transaction_type="credit",
                    reason="PG 9.3.1 test seed",
                    reference_type="test_seed",
                    reference_id=f"seed-{uuid.uuid4().hex}",
                    metadata_json={},
                )
            )
            session.add(
                Item(
                    id=item_id,
                    slug=f"slug-{item_id}",
                    code=f"CODE-{uuid.uuid4().hex[:12]}",
                    title="PG 9.3.1 key",
                    description="Purchasable catalog key",
                    symbol="KEY",
                    category="KEY",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            )
            for key, value in (
                (SHOP_ENABLED_KEY, True),
                (SHOP_PRICE_ROOT_KEY, price),
            ):
                existing = session.get(SystemSetting, key)
                value_type = "boolean" if isinstance(value, bool) else "integer"
                if existing is None:
                    session.add(
                        SystemSetting(
                            key=key,
                            value_json=value,
                            value_type=value_type,
                            category="shop",
                            title=key,
                            description="Seeded by PG 9.3.1 test",
                            is_sensitive=False,
                            status="active",
                        )
                    )
                else:
                    existing.value_json = value
                    existing.status = "active"

        # ---- Параллельный запуск покупок с общего барьера.
        barrier = threading.Barrier(purchases)
        outcomes: list[tuple[int, tuple[str, str | None]]] = []
        outcomes_lock = threading.Lock()

        def buyer(thread_index: int) -> None:
            barrier.wait()
            try:
                with self.SessionLocal.begin() as session:
                    self.shop_service.purchase_catalog_item(
                        session, player_id, item_id
                    )
                outcome = ("success", None)
            except Exception as exc:  # noqa: BLE001 — классы собираем в отчёт
                outcome = (type(exc).__name__, str(exc))
            with outcomes_lock:
                outcomes.append((thread_index, outcome))

        threads = [
            threading.Thread(target=buyer, args=(index,), name=f"buyer-{index}")
            for index in range(purchases)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        successes = sum(
            1 for _, outcome in outcomes if outcome[0] == "success"
        )
        errors = [
            f"{name}: {detail}" for _, (name, detail) in outcomes if name != "success"
        ]

        # ---- Проверка инвариантов по факту (все данные — в одном сообщении,
        # чтобы видно было реальные классы ошибок и итоговый баланс).
        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            self.assertIsNotNone(wallet, "Кошелёк ROOT не найден")
            final_balance = wallet.available_balance
            debit_count = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.transaction_type == "debit",
                )
            )
            distinct_ref_ids = session.scalars(
                select(WalletTransaction.reference_id)
                .where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.transaction_type == "debit",
                )
                .distinct()
            ).all()
            credit_sum = session.scalar(
                select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.transaction_type == "credit",
                )
            )
            debit_sum = session.scalar(
                select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.transaction_type == "debit",
                )
            )

        ledger_balance = credit_sum - debit_sum
        expected_balance = initial_balance - price * (initial_balance // price)
        expected_successes = initial_balance // price

        problems: list[str] = []
        if successes != expected_successes:
            problems.append(
                f"successes={successes}, ожидалось {expected_successes}"
            )
        if final_balance < 0:
            problems.append(f"баланс ушёл в минус: {final_balance}")
        if final_balance != expected_balance:
            problems.append(
                f"final_balance={final_balance}, ожидалось {expected_balance}"
            )
        if debit_count != expected_successes:
            problems.append(
                f"debit_count={debit_count}, ожидалось {expected_successes}"
            )
        if len(distinct_ref_ids) != expected_successes:
            problems.append(
                f"distinct_reference_ids={distinct_ref_ids}, "
                f"ожидалось {expected_successes}"
            )
        if ledger_balance != final_balance:
            problems.append(
                f"ledger={credit_sum}-{debit_sum}={ledger_balance} "
                f"!= balance={final_balance}"
            )
        unexpected = [
            f"{name}: {detail}"
            for _, (name, detail) in outcomes
            if name not in ("success", "MissionEngineError", "IntegrityError")
        ]
        if unexpected:
            problems.append(f"неожиданные классы исключений: {unexpected}")

        if problems:
            self.fail(
                "Гонка покупок нарушила инвариант 9.3.1: "
                + "; ".join(problems)
                + f" | errors={errors}"
            )




    def test_concurrent_fallback_purchase_idempotent(self) -> None:
        """9.3.1-c: purchase_fallback_offer под гонкой — идемпотентный успех.

        Два потока покупают ОДИН entitlement (quota_limit=1) с кошельком,
        баланс = цена. FOR UPDATE на строку PlayerFallbackEntitlement берётся
        первой строкой purchase_fallback_offer (fallback_shop.py) и
        сериализует: поток A коммитит ровно один debit + credit +
        consumed_count=1/status="exhausted", поток B блокируется на
        entitlement-локе до коммита A, затем попадает в committed-guard
        (consumed_count >= quota_limit И проводка {id}:{run}:{count} уже
        закоммичена) и возвращает идемпотентный успех БЕЗ повторного
        списания.

        Ожидание: ОБА потока success (второй — идемпотентный), ровно одна
        debit-проводка, ровно один InventoryEvent("credited"), consumed_count=1,
        status="exhausted", PlayerItem.quantity=1, баланс = price - price = 0,
        distinct_reference_ids == 1. Если второй поток вернёт
        MissionEngineError/IntegrityError — это FAIL: лок/guard не
        отработали (код сервиса в этой задаче не «подгоняем», только фиксируем).
        """
        from app.fallback_shop import (
            FALLBACK_ENABLED_KEY,
            FALLBACK_PRICE_ROOT_KEY,
        )
        from app.geo_team_runtime_models import (
            InventoryEvent,
            PlayerFallbackEntitlement,
        )
        from app.models import (
            Chapter,
            GamePlayer,
            Item,
            KeyRules,
            Mission,
            PlayerItem,
            Season,
            SystemSetting,
            Wallet,
            WalletTransaction,
        )

        # ---- Подготовка (одна транзакция): игрок + кошелёк с seed-кредитом
        # (ledger — source of truth) + published KEY-item + KeyRules +
        # fallback-настройки (CMS-first) + минимальная цепочка
        # Season -> Chapter -> Mission (FK entitlement.mission_id RESTRICT) +
        # сам entitlement с quota_limit=1.
        player_id = f"pg-fallback-player-{uuid.uuid4().hex[:12]}"
        wallet_id = f"wallet-{uuid.uuid4().hex}"
        item_id = f"item-{uuid.uuid4().hex}"
        mission_id = f"mission-{uuid.uuid4().hex}"
        entitlement_id = f"entitlement-{uuid.uuid4().hex}"
        price = 40

        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=player_id,
                    display_name="PG 9.3.1-c fallback player",
                    auth_provider="test",
                    external_id=f"test-{uuid.uuid4().hex}",
                    status="active",
                )
            )
            session.flush()  # FK: wallets.player_id -> game_players
            session.add(
                Wallet(
                    id=wallet_id,
                    player_id=player_id,
                    currency="ROOT",
                    available_balance=price,
                    locked_balance=0,
                )
            )
            session.flush()  # FK: wallet_transactions.wallet_id -> wallets
            session.add(
                WalletTransaction(
                    id=f"wallet-transaction-{uuid.uuid4().hex}",
                    wallet_id=wallet_id,
                    amount=price,
                    balance_after=price,
                    transaction_type="credit",
                    reason="PG 9.3.1-c test seed",
                    reference_type="test_seed",
                    reference_id=f"seed-{uuid.uuid4().hex}",
                    metadata_json={},
                )
            )
            session.add(
                Item(
                    id=item_id,
                    slug=f"slug-{item_id}",
                    code=f"CODE-{uuid.uuid4().hex[:12]}",
                    title="PG 9.3.1-c fallback key",
                    description="Fallback purchasable key",
                    symbol="KEY",
                    category="KEY",
                    rarity="common",
                    is_unique=False,
                    content={"schemaVersion": 1},
                    status="published",
                )
            )
            session.flush()  # FK: key_rules.item_id -> items

            # KeyRules обязательны: _resolve_fallback_key_item вернёт None
            # (409 «Ключ недоступно.») без is_consumable-правил.
            session.add(
                KeyRules(
                    id=f"key-rules-{uuid.uuid4().hex}",
                    item_id=item_id,
                    is_consumable=True,
                )
            )
            for key, value in (
                (FALLBACK_ENABLED_KEY, True),
                (FALLBACK_PRICE_ROOT_KEY, price),
            ):
                existing = session.get(SystemSetting, key)
                value_type = "boolean" if isinstance(value, bool) else "integer"
                if existing is None:
                    session.add(
                        SystemSetting(
                            key=key,
                            value_json=value,
                            value_type=value_type,
                            category="shop.fallback",
                            title=key,
                            description="Seeded by PG 9.3.1-c test",
                            is_sensitive=False,
                            status="active",
                        )
                    )
                else:
                    existing.value_json = value
                    existing.status = "active"

            season_id = f"season-{uuid.uuid4().hex}"
            chapter_id = f"chapter-{uuid.uuid4().hex}"
            session.add(
                Season(
                    id=season_id,
                    slug=f"slug-{season_id}",
                    title="PG 9.3.1-c season",
                )
            )
            session.flush()  # FK: chapters.season_id -> seasons
            session.add(
                Chapter(
                    id=chapter_id,
                    season_id=season_id,
                    slug=f"slug-{chapter_id}",
                    title="PG 9.3.1-c chapter",
                )
            )
            session.flush()  # FK: missions.chapter_id -> chapters
            session.add(
                Mission(
                    id=mission_id,
                    chapter_id=chapter_id,
                    slug=f"slug-{mission_id}",
                    mission_type="text_answer",
                    title="PG 9.3.1-c mission",
                    content={},
                    validation_config={},
                    status="published",
                )
            )

        # Entitlement — отдельной транзакцией: в проде он создаётся ПОСЛЕ
        # коммита игрока/миссии (mission failure), а в одном flush с
        # родителями порядок INSERT не гарантирован (relationship() у
        # PlayerFallbackEntitlement нет) — падало в FK violation на PG.
        with self.SessionLocal.begin() as session:
            session.add(
                PlayerFallbackEntitlement(
                    id=entitlement_id,
                    player_id=player_id,
                    mission_id=mission_id,
                    item_id=item_id,
                    offer_id=item_id,
                    quota_limit=1,
                    consumed_count=0,
                    run_entry_count=0,
                    status="available",
                )
            )

        # ---- Параллельный запуск покупок с общего барьера. Каждый поток —
        # своя транзакция (self.SessionLocal.begin()), как в shop-тесте.
        barrier = threading.Barrier(2)
        outcomes: list[tuple[int, tuple[str, str | None]]] = []
        outcomes_lock = threading.Lock()

        def buyer(thread_index: int) -> None:
            barrier.wait()
            try:
                with self.SessionLocal.begin() as session:
                    self.fallback_shop.purchase_fallback_offer(
                        session, player_id, entitlement_id
                    )
                outcome = ("success", None)
            except Exception as exc:  # noqa: BLE001 — классы собираем в отчёт
                outcome = (type(exc).__name__, str(exc))
            with outcomes_lock:
                outcomes.append((thread_index, outcome))

        threads = [
            threading.Thread(target=buyer, args=(index,), name=f"buyer-{index}")
            for index in range(2)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        successes = sum(1 for _, outcome in outcomes if outcome[0] == "success")
        errors = [
            f"{name}: {detail}" for _, (name, detail) in outcomes if name != "success"
        ]

        # ---- Проверка инвариантов по факту (данные — в одном сообщении).
        with self.SessionLocal() as session:
            wallet = session.scalar(
                select(Wallet).where(
                    Wallet.player_id == player_id,
                    Wallet.currency == "ROOT",
                )
            )
            self.assertIsNotNone(wallet, "Кошелёк ROOT не найден")
            final_balance = wallet.available_balance
            debit_count = session.scalar(
                select(func.count(WalletTransaction.id)).where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.transaction_type == "debit",
                )
            )
            distinct_ref_ids = session.scalars(
                select(WalletTransaction.reference_id)
                .where(
                    WalletTransaction.wallet_id == wallet.id,
                    WalletTransaction.transaction_type == "debit",
                )
                .distinct()
            ).all()
            entitlement = session.scalar(
                select(PlayerFallbackEntitlement).where(
                    PlayerFallbackEntitlement.id == entitlement_id
                )
            )
            self.assertIsNotNone(entitlement, "Entitlement не найден")
            consumed_count = entitlement.consumed_count
            entitlement_status = entitlement.status
            player_item = session.scalar(
                select(PlayerItem).where(
                    PlayerItem.player_id == player_id,
                    PlayerItem.item_id == item_id,
                )
            )
            if player_item is None:
                player_item_quantity = -1
                inventory_event_count = -1
            else:
                player_item_quantity = player_item.quantity
                inventory_event_count = session.scalar(
                    select(func.count(InventoryEvent.id)).where(
                        InventoryEvent.player_item_id == player_item.id,
                        InventoryEvent.event_type == "credited",
                        InventoryEvent.reference_type == "fallback_purchase",
                    )
                )

        problems: list[str] = []
        if successes != 2:
            problems.append(
                f"successes={successes}, ожидалось 2 (второй поток должен "
                "вернуть идемпотентный успех через committed-guard)"
            )
        if final_balance != 0:
            problems.append(
                f"final_balance={final_balance}, ожидалось {price} - {price} = 0"
            )
        if debit_count != 1:
            problems.append(f"debit_count={debit_count}, ожидалось 1")
        if len(distinct_ref_ids) != 1:
            problems.append(
                f"distinct_reference_ids={distinct_ref_ids}, ожидалось {1}"
            )
        if consumed_count != 1:
            problems.append(f"consumed_count={consumed_count}, ожидалось 1")
        if entitlement_status != "exhausted":
            problems.append(f"status={entitlement_status}, ожидалось 'exhausted'")
        if player_item_quantity != 1:
            problems.append(
                f"PlayerItem.quantity={player_item_quantity}, ожидалось 1"
            )
        if inventory_event_count != 1:
            problems.append(
                f"InventoryEvent count={inventory_event_count}, ожидалось 1"
            )
        unexpected = [
            f"{name}: {detail}"
            for _, (name, detail) in outcomes
            if name not in ("success", "MissionEngineError")
        ]
        if unexpected:
            problems.append(f"неожиданные классы исключений: {unexpected}")

        if problems:
            self.fail(
                "Гонка fallback-покупки нарушила инвариант 9.3.1-c: "
                + "; ".join(problems)
                + f" | errors={errors}"
            )

