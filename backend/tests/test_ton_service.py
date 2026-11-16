"""Тесты ton_service (этап 11.4): валидация TON-адресов, CMS ton.payout_wallet,
Jetton transfer (моки вместо сети).

Инфраструктура — паттерн test_stars_service.py: на каждый тест свежая
disposable SQLite + alembic upgrade head; SessionLocal патчится в app.db
(функции ton_service принимают session параметром, по образцу transfer_service).
Реальная сеть не вызывается: _TonCenterProvider и WalletV4R2 мокаются.

Покрывает:
  1. validate_ton_address — нормализация (тестнет-флаг сохраняется),
     невалидные адреса -> MissionEngineError(422, «Невалидный TON-адрес.»);
  2. get_payout_wallet_address — без CMS-записи 503, с активной записью
     ton.payout_wallet возвращает адрес;
  3. send_jetton_transfer — 503 на каждый незаполненный конфиг, 422 на
     сумму <= 0, и успешный path (tx hash + тело transfer с OP 0xf8a7ea5).
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
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from pytoniq_core import Address, begin_cell

from app import ton_service
from app.mission_engine import MissionEngineError
from app.models import SystemSetting
from app.ton_service import (
    get_payout_wallet_address,
    send_jetton_transfer_sync,
    validate_ton_address,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"

# Тестнет-адрес ROOT-минтера/Jetton wallet'а для assert'ов (kQA… — тестнет).
MINTER_ADDRESS = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"
AMOUNT_NANO = 1000
# Raw-адреса testnet для моков депозита (0:<64 hex>): jetton-wallet
# отправителя, owner (кошелёк игрока), ROOT-мастер, сейф, «чужой» мастер.
SENDER_JETTON_WALLET = Address("0:" + "1" * 64)
DEPOSITOR_OWNER = Address("0:" + "2" * 64)
ROOT_MASTER = Address("0:" + "3" * 64)
VAULT_ADDRESS_RAW = "0:" + "4" * 64
OTHER_MASTER = Address("0:" + "5" * 64)


class _FakeTonCenterProvider:
    """Заглушка HTTP-провайдера: сеть не трогаем, get-методы имитируем."""

    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.run_get_method = AsyncMock(return_value=[Address(MINTER_ADDRESS)])
        self.raw_get_account_state = AsyncMock(return_value=(None, None))
        self.raw_send_message = AsyncMock(return_value="fake-tx-hash")

    async def aclose(self) -> None:
        pass


class TonServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        """Захватываем модуль ton_service (SessionLocal не используется напрямую)."""
        cls.ton_service = ton_service
        cls._session_local_patches: list = []

    def setUp(self) -> None:
        """Свежая disposable SQLite с alembic upgrade head на каждый тест."""
        self._temporary_directory = tempfile.TemporaryDirectory(
            prefix="chimera-ton-tests-"
        )
        self.database_path = Path(self._temporary_directory.name) / "ton.sqlite3"
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
        # По образцу test_stars_service патчим app.db.SessionLocal; сервисные
        # функции принимают session параметром, отдельных каналов не нужно.
        self._session_local_patches = [
            patch("app.db.SessionLocal", self.SessionLocal),
        ]
        for session_local_patch in self._session_local_patches:
            session_local_patch.start()

    def tearDown(self) -> None:
        for session_local_patch in self._session_local_patches:
            session_local_patch.stop()
        self.engine.dispose()
        self._temporary_directory.cleanup()

    # ---- Fixtures и хелперы -------------------------------------------------

    def _seed_payout_wallet_setting(self, session, address: str) -> None:
        """Активная SystemSetting ton.payout_wallet (CMS-first), идемпотентно.

        Миграция dde2038a44d9 уже создаёт ton.payout_wallet из каталога,
        поэтому при существующей записи обновляем ТОЛЬКО value_json
        (+status): метаданные (value_type/category/title/description/
        is_sensitive) обязаны остаться каталоговыми, иначе
        admin_system_settings отдаёт 409.
        """
        key = ton_service.PAYOUT_WALLET_SETTING_KEY
        existing = session.get(SystemSetting, key)
        if existing is not None:
            existing.value_json = address
            existing.status = "active"
        else:
            session.add(
                SystemSetting(
                    key=key,
                    value_json=address,
                    value_type="string",
                    category="ton",
                    title=key,
                    description="Seeded by ton_service test",
                    is_sensitive=True,
                    status="active",
                )
            )
        session.flush()

    def _patch_ton_settings(self, **values):
        """Подменяет ton_service.settings целиком (config.settings — frozen dataclass).

        Дефолты берутся из реальных settings (в dev .env они пустые), поверх
        накладываются переопределённые поля; значения не выводятся наружу.
        """
        real = self.ton_service.settings
        defaults = {
            "ton_payout_mnemonic": getattr(real, "ton_payout_mnemonic", ""),
            "ton_root_jetton_master": getattr(real, "ton_root_jetton_master", ""),
            "ton_api_endpoint": getattr(real, "ton_api_endpoint", ""),
        }
        defaults.update(values)
        return patch.object(self.ton_service, "settings", SimpleNamespace(**defaults))

    def _make_provider(self) -> ton_service._TonCenterProvider:
        """Реальный _TonCenterProvider с закрытием httpx-клиента после теста."""
        provider = ton_service._TonCenterProvider(
            "https://testnet.toncenter.com/api/v2"
        )
        self.addCleanup(lambda: asyncio.run(provider.aclose()))
        return provider

    # ---- Тесты ---------------------------------------------------------------

    def test_validate_ton_address(self) -> None:
        """Валидные адреса нормализуются, тестнет-флаг сохраняется; невалид -> 422."""
        normalized = validate_ton_address(MINTER_ADDRESS)
        # kQA… (тестнет bounceable) остаётся тестнет-формой — флаг сохраняется.
        self.assertTrue(normalized.startswith("kQA"))
        self.assertEqual(
            Address(normalized).to_str(is_user_friendly=False),
            Address(MINTER_ADDRESS).to_str(is_user_friendly=False),
        )
        # Сырая (raw) форма того же адреса -> та же каноническая сущность.
        raw = Address(MINTER_ADDRESS).to_str(is_user_friendly=False)
        self.assertEqual(
            Address(validate_ton_address(raw)).to_str(is_user_friendly=False),
            raw,
        )

        for invalid in ("qwerty", "", "  ", "0:zz"):
            with self.assertRaises(MissionEngineError) as context:
                validate_ton_address(invalid)
            self.assertEqual(context.exception.status_code, 422)
            self.assertEqual(context.exception.detail, "Невалидный TON-адрес.")

    def test_get_payout_wallet_address_from_cms(self) -> None:
        """CMS ton.payout_wallet: пусто -> 503; активная запись -> адрес."""
        with self.SessionLocal() as session:
            with self.assertRaises(MissionEngineError) as context:
                get_payout_wallet_address(session)
        self.assertEqual(context.exception.status_code, 503)
        self.assertEqual(
            context.exception.detail, "Вывод ROOT в TON не настроен (payout wallet)."
        )

        with self.SessionLocal.begin() as session:
            self._seed_payout_wallet_setting(session, MINTER_ADDRESS)
        with self.SessionLocal() as session:
            self.assertEqual(get_payout_wallet_address(session), MINTER_ADDRESS)

    def test_send_jetton_transfer(self) -> None:
        """503 на незаполненный конфиг, 422 на сумму <= 0, успех с моками сети."""
        mnemonic = " ".join(["abandon"] * 12)
        valid_endpoint = "https://testnet.toncenter.com/api/v2/jsonRPC"
        valid_config = {
            "ton_payout_mnemonic": mnemonic,
            "ton_root_jetton_master": MINTER_ADDRESS,
            "ton_api_endpoint": valid_endpoint,
        }

        # 1. Нет мнемоники payout-кошелька в .env -> 503 (сеть не нужна).
        with self._patch_ton_settings(ton_payout_mnemonic=""):
            with self.assertRaises(MissionEngineError) as context:
                send_jetton_transfer_sync(MINTER_ADDRESS, AMOUNT_NANO)
        self.assertEqual(context.exception.status_code, 503)
        self.assertIn("мнемоники", context.exception.detail)

        # 2. Не заполнен Jetton master ROOT -> 503.
        with self._patch_ton_settings(
            ton_payout_mnemonic=mnemonic, ton_root_jetton_master=""
        ):
            with self.assertRaises(MissionEngineError) as context:
                send_jetton_transfer_sync(MINTER_ADDRESS, AMOUNT_NANO)
        self.assertEqual(context.exception.status_code, 503)
        self.assertIn("Jetton master", context.exception.detail)

        # 3. Не заполнен TON_API_ENDPOINT -> 503.
        with self._patch_ton_settings(
            ton_payout_mnemonic=mnemonic, ton_root_jetton_master=MINTER_ADDRESS
        ):
            with self.assertRaises(MissionEngineError) as context:
                send_jetton_transfer_sync(MINTER_ADDRESS, AMOUNT_NANO)
        self.assertEqual(context.exception.status_code, 503)
        self.assertIn("TON_API_ENDPOINT", context.exception.detail)

        # 4. Сумма вывода <= 0 -> 422 (игровая ошибка, до сетевых вызовов).
        with self._patch_ton_settings(**valid_config):
            with self.assertRaises(MissionEngineError) as context:
                send_jetton_transfer_sync(MINTER_ADDRESS, 0)
        self.assertEqual(context.exception.status_code, 422)

        # 5. Полный успех: мок провайдера/кошелька, проверяем tx hash и тело.
        wallet = MagicMock()
        wallet.address = Address(MINTER_ADDRESS)
        wallet.transfer = AsyncMock(return_value="fake-tx-hash")
        wallet_class = MagicMock()
        wallet_class.from_mnemonic = AsyncMock(return_value=wallet)

        with self._patch_ton_settings(**valid_config), \
            patch.object(self.ton_service, "_TonCenterProvider", _FakeTonCenterProvider), \
            patch.object(self.ton_service, "WalletV4R2", wallet_class):
            tx_hash = send_jetton_transfer_sync(MINTER_ADDRESS, AMOUNT_NANO)

        self.assertEqual(tx_hash, "fake-tx-hash")
        wallet_class.from_mnemonic.assert_awaited_once()
        wallet.transfer.assert_awaited_once()
        transfer_kwargs = wallet.transfer.await_args.kwargs
        self.assertEqual(
            transfer_kwargs["destination"].to_str(is_user_friendly=False),
            Address(MINTER_ADDRESS).to_str(is_user_friendly=False),
        )
        self.assertEqual(
            transfer_kwargs["amount"], ton_service.JETTON_TRANSFER_GAS
        )
        # Transfer-сообщение — ручной Jetton body (TEP-74) с OP 0xf8a7ea5.
        body = transfer_kwargs["body"]
        self.assertEqual(
            body.begin_parse().load_uint(32), ton_service.JETTON_TRANSFER_OP
        )

    # ---- Sprint 1.2: депозит (getTransactions + парсинг jetton) --------------

    def _make_internal_transfer_tx(self, op_code: int) -> dict:
        """Собрать raw tx TonCenter с in_msg internal_transfer (Sprint 1.2)."""
        body_cell = (
            begin_cell()
            .store_uint(op_code, 32)
            .store_uint(123, 64)  # query_id
            .store_coins(AMOUNT_NANO)  # amount
            .store_address(SENDER_JETTON_WALLET)  # sender jetton-wallet
            .end_cell()
        )
        return {
            "hash": "tx-hash-abc",
            "lt": "12345",
            "in_msg": {
                "source": SENDER_JETTON_WALLET.to_str(is_user_friendly=True),
                "destination": VAULT_ADDRESS_RAW,
                "msg_data": {"body": body_cell.to_boc().hex()},
            },
        }

    def test_get_transactions(self) -> None:
        """getTransactions: payload с курсором, raw список возвращается как есть."""
        provider = self._make_provider()
        provider._post = AsyncMock(return_value=[{"hash": "h1", "lt": "1"}])

        result = asyncio.run(
            provider.get_transactions("addr", limit=5, lt=10, l_hash="hash10")
        )

        self.assertEqual(result, [{"hash": "h1", "lt": "1"}])
        provider._post.assert_awaited_once()
        self.assertEqual(provider._post.await_args.args[0], "getTransactions")
        payload = provider._post.await_args.args[1]
        self.assertEqual(
            payload,
            {"address": "addr", "limit": 5, "lt": "10", "hash": "hash10"},
        )

    def test_parse_jetton_transfer(self) -> None:
        """internal_transfer 0x178d4519 + run_get_method -> dict с owner/master."""
        tx = self._make_internal_transfer_tx(
            ton_service.JETTON_INTERNAL_TRANSFER_OP
        )
        provider = self._make_provider()
        provider.run_get_method = AsyncMock(
            return_value=[0, DEPOSITOR_OWNER, ROOT_MASTER, None]
        )

        with self._patch_ton_settings(
            ton_root_jetton_master=ROOT_MASTER.to_str(is_user_friendly=False)
        ):
            result = asyncio.run(provider.parse_jetton_transfer(tx))

        self.assertIsNotNone(result)
        self.assertEqual(result["tx_hash"], "tx-hash-abc")
        self.assertEqual(result["lt"], "12345")
        self.assertEqual(result["query_id"], 123)
        self.assertEqual(result["amount_nano"], AMOUNT_NANO)
        self.assertEqual(
            result["from_address"], DEPOSITOR_OWNER.to_str(is_user_friendly=True)
        )
        self.assertEqual(result["to_address"], VAULT_ADDRESS_RAW)
        self.assertEqual(
            result["jetton_master"], ROOT_MASTER.to_str(is_user_friendly=True)
        )
        self.assertEqual(result["raw_payload"], tx)
        provider.run_get_method.assert_awaited_once()
        self.assertEqual(
            provider.run_get_method.await_args.args[0].to_str(is_user_friendly=False),
            SENDER_JETTON_WALLET.to_str(is_user_friendly=False),
        )
        self.assertEqual(
            provider.run_get_method.await_args.args[1],
            ton_service.JETTON_WALLET_DATA_METHOD,
        )

    def test_parse_non_jetton_transfer(self) -> None:
        """in_msg без OP 0x178d4519 -> None."""
        tx = self._make_internal_transfer_tx(0xDEADBEEF)
        provider = self._make_provider()
        result = asyncio.run(provider.parse_jetton_transfer(tx))
        self.assertIsNone(result)

    def test_parse_wrong_jetton_master(self) -> None:
        """jetton_master != TON_ROOT_JETTON_MASTER -> None."""
        tx = self._make_internal_transfer_tx(
            ton_service.JETTON_INTERNAL_TRANSFER_OP
        )
        provider = self._make_provider()
        provider.run_get_method = AsyncMock(
            return_value=[0, DEPOSITOR_OWNER, OTHER_MASTER, None]
        )

        with self._patch_ton_settings(
            ton_root_jetton_master=ROOT_MASTER.to_str(is_user_friendly=False)
        ):
            result = asyncio.run(provider.parse_jetton_transfer(tx))

        self.assertIsNone(result)


