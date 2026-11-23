"""TON-интеграция (этап 11.4, roadmap-detailed.md): вывод ROOT в TON.

Валидация TON-адресов — через pytoniq-core (НЕ regex), как требует
docs/roadmap-detailed.md шаг 11.4. Jetton transfer — вариант B из плана:
выплата идёт со «спец» payout-кошелька (адрес в CMS ton.payout_wallet,
мнемоника в .env TON_PAYOUT_MNEMONIC, сеть — TON_NETWORK/TON_API_ENDPOINT).

pytoniq==0.1.43 в этом окружении поставляется без HTTP/TonCenter-клиента
и без JettonWallet, поэтому transfer собран вручную (TEP-74, OP 0xf8a7ea5)
поверх минимального HTTP-провайдера к TonCenter JSON-RPC. Логика заявок и
immutable-проводки — отдельно (шаг 11.5-a).
"""
from __future__ import annotations

import asyncio
import base64
import logging
import secrets

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from pytoniq import WalletV4R2
from pytoniq_core import Address, Cell, begin_cell

from app.admin_player_wallet import ACTIVE_SETTING_STATUS
from app.config import settings
from app.mission_engine import MissionEngineError
from app.models import SystemSetting

logger = logging.getLogger(__name__)

# --- Константы Jetton transfer (TEP-74) и CMS -------------------------------

# OP-код transfer у Jetton Wallet (TEP-74, https://docs.ton.org/t2/teps/jettons#transfer).
JETTON_TRANSFER_OP = 0xF8A7EA5
# OP-код internal_transfer (TEP-74) — уведомление о входящем jetton на сейф
# (депозит ROOT-jetton, Sprint 1.2). Тело: query_id, amount, from, ...
JETTON_INTERNAL_TRANSFER_OP = 0x178D4519
# get-метод Jetton wallet: (balance, owner, jetton_master, wallet_code).
JETTON_WALLET_DATA_METHOD = "get_wallet_data"
# Комиссия, которую Jetton wallet берёт за обработку transfer (наноTON):
# отправляем transfer-сообщением вместе с ним, чтобы кошельку хватило TON.
JETTON_TRANSFER_GAS = 60_000_000  # 0.06 TON

# query_id в TEP-74 transfer — uint64 (A7: уникальный id попытки выплаты).
MAX_TON_QUERY_ID = (1 << 64) - 1

# SystemSetting (CMS, категория ton) с адресом «спец» payout-кошелька.
PAYOUT_WALLET_SETTING_KEY = "ton.payout_wallet"


def validate_ton_address(address: str) -> str:
    """Валидация TON-адреса через pytoniq (шаг 11.4: НЕ regex).

    Возвращает каноническую user-friendly форму, сохраняя тестнет-флаг
    входного адреса (kQA… останется kQA…, EQA… — EQA…). Невалидный адрес
    (битый BOC, неверная CRC, неверный формат) — MissionEngineError(422).
    """
    if not isinstance(address, str) or not address.strip():
        raise MissionEngineError(422, "Невалидный TON-адрес.")

    try:
        parsed = Address(address.strip())
    except Exception:
        raise MissionEngineError(422, "Невалидный TON-адрес.") from None

    return parsed.to_str(
        is_user_friendly=True,
        is_url_safe=True,
        is_bounceable=True,
        is_test_only=parsed.is_test_only,
    )


def _read_string_setting(session: Session, key: str) -> str:
    """Активная SystemSetting (CMS) -> строковое значение ('' если нет)."""
    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.status == ACTIVE_SETTING_STATUS,
        )
    )
    value = getattr(setting, "value_json", "")
    return value if isinstance(value, str) else ""


def get_payout_wallet_address(session: Session) -> str:
    """Адрес «спец» payout-кошелька из CMS (ton.payout_wallet).

    Мнемоника кошелька живёт в .env (TON_PAYOUT_MNEMONIC), адрес — в CMS.
    Пусто/без активной записи — MissionEngineError(503): вывод не настроен.
    """
    address = _read_string_setting(session, PAYOUT_WALLET_SETTING_KEY).strip()
    if not address:
        raise MissionEngineError(
            503, "Вывод ROOT в TON не настроен (payout wallet)."
        )
    return address


def _boc_bytes(value: object) -> bytes:
    """Разбор значения slice/cell из стека TonCenter: hex или base64 BOC."""
    if not isinstance(value, str) or not value.strip():
        raise MissionEngineError(503, "Jetton wallet не определён (пустой ответ).")
    raw = value.strip()
    if raw.startswith("0x"):
        return bytes.fromhex(raw[2:])
    try:
        return bytes.fromhex(raw)
    except ValueError:
        return base64.b64decode(raw, validate=True)


class _TonCenterError(RuntimeError):
    """Ошибка ответа TonCenter (ok=false, HTTP, malformed)."""


class _TonCenterProvider:
    """Минимальный HTTP-провайдер pytoniq к TonCenter (TON_API_ENDPOINT).

    pytoniq 0.1.43 в этом окружении поставляется без HTTP/TonCenter-клиента
    (только LiteClient/liteserver по ADNL), поэтому реализуем ровно те методы
    интерфейса LiteClientLike, которые pytoniq реально вызывает в path
    WalletV4R2.from_mnemonic + transfer:

      * raw_get_account_state — эмулируем uninitialized-состояние (None, None):
        SimpleAccount.from_raw(None) строит пустой аккаунт, а для отправки
        внешнего сообщения этого достаточно; seqno берётся get-методом;
      * run_get_method — TonCenter runGetMethod: get_wallet_address/get_seqno;
      * raw_send_message — TonCenter sendBoc; возвращает hash внешнего
        сообщения (tx hash — в 11.5-a пишется в WithdrawalRequest.ton_tx_hash).

    Endpoint — база TonCenter v2 JSON-RPC (например,
    https://testnet.toncenter.com/api/v2). Секреты сюда не попадают.
    """

    def __init__(self, endpoint: str, timeout: float = 15.0) -> None:
        if not endpoint or not endpoint.strip():
            raise ValueError("TON_API_ENDPOINT must not be empty")
        self._endpoint = endpoint.rstrip("/")
        # Ключ TonCenter поднимает лимит с ~1 запроса/сек до 10/сек. Без него
        # батч на 50 получателей (по запросу на jetton-адрес) упирается в 429.
        headers = {}
        if settings.ton_api_key:
            headers["X-API-KEY"] = settings.ton_api_key
        self._client = httpx.AsyncClient(timeout=timeout, headers=headers)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, api_method: str, payload: dict) -> dict:
        response = await self._client.post(
            f"{self._endpoint}/{api_method}", json=payload
        )
        response.raise_for_status()
        data = response.json()
        if data.get("ok") is not True:
            raise _TonCenterError(f"{api_method}: ok={data.get('ok')!r}")
        return data.get("result") or {}

    async def raw_get_account_state(self, address, block=None) -> tuple:
        """Эмуляция: (None, None) — pytoniq умеет (uninitialized account)."""
        del address, block
        return None, None

    @staticmethod
    def _encode_stack(stack: list) -> list:
        """Стек pytoniq -> JSON-стек TonCenter runGetMethod."""
        encoded = []
        for entry in stack:
            if isinstance(entry, Address):
                cell = begin_cell().store_address(entry).end_cell()
                encoded.append(
                    {"type": "slice", "value": base64.b64encode(cell.to_boc()).decode()}
                )
            elif isinstance(entry, int):
                encoded.append({"type": "num", "value": str(entry)})
            else:
                raise _TonCenterError(
                    f"unsupported stack entry: {type(entry).__name__}"
                )
        return encoded

    @staticmethod
    def _decode_stack(entries: list) -> list:
        """JSON-стек TonCenter -> список; slice/cell трактуем как адрес."""
        decoded = []
        for entry in entries:
            entry_type = entry.get("type")
            value = entry.get("value")
            if entry_type in ("num", "int"):
                raw = str(value)
                decoded.append(int(raw, 16) if raw.lower().startswith("0x") else int(raw))
            elif entry_type in ("slice", "cell"):
                cell = Cell.one_from_boc(_boc_bytes(value))
                decoded.append(cell.begin_parse().load_address())
            else:
                raise _TonCenterError(f"unsupported result entry: {entry_type!r}")
        return decoded

    async def run_get_method(self, address, method, stack=None, block=None) -> list:
        """runGetMethod: seqno / get_wallet_address (см. get_jetton_wallet_address)."""
        del block
        if isinstance(address, Address):
            address = address.to_str(is_user_friendly=False)
        result = await self._post(
            "runGetMethod",
            {
                "address": address,
                "method": method,
                "stack": self._encode_stack(list(stack or [])),
            },
        )
        return self._decode_stack(result.get("stack") or [])

    async def raw_send_message(self, message: bytes) -> str:
        """sendBoc; tx hash = hash отправленного внешнего сообщения."""
        tx_hash = Cell.one_from_boc(message).hash.hex()
        await self._post("sendBoc", {"boc": base64.b64encode(message).decode()})
        return tx_hash

    async def get_transactions(
        self,
        address: str,
        limit: int = 20,
        lt: int | None = None,
        l_hash: str | None = None,
    ) -> list[dict]:
        """Список транзакций адреса через TonCenter getTransactions (Sprint 1.2).

        Возвращает raw JSON-список (как от TonCenter). lt/l_hash — курсор
        (последняя обработанная транзакция), чтобы поллер не дублировал и не
        пропускал переводы.
        """
        payload: dict = {"address": address, "limit": limit}
        if lt is not None:
            payload["lt"] = str(lt)
        if l_hash:
            payload["hash"] = l_hash
        return await self._post("getTransactions", payload)

    @staticmethod
    def _extract_in_msg_body(in_msg: dict) -> Cell | None:
        """Достать body входящего сообщения (Cell) из raw JSON TonCenter.

        Тело приходит в msg_data.body либо raw_body/body (base64/hex BOC).
        Невалидный/пустой BOC — None (значит «не jetton-перевод»).
        """
        msg_data = in_msg.get("msg_data")
        if isinstance(msg_data, dict):
            body = msg_data.get("body")
        else:
            body = in_msg.get("raw_body") or in_msg.get("body")
        if not body:
            return None
        try:
            return Cell.one_from_boc(_boc_bytes(body))
        except Exception:
            return None

    async def parse_jetton_transfer(
        self, tx: dict, session: Session | None = None
    ) -> dict | None:
        """Разобрать входящий jetton-перевод (internal_transfer 0x178d4519).

        Только парсинг: НЕ зачисляет и НЕ создаёт JettonDeposit (это Шаг 4).
        Проверяет OP-код in_msg, извлекает query_id/amount/sender jetton-wallet,
        через run_get_method(get_wallet_data) получает owner и jetton_master,
        сверяет jetton_master == settings.ton_root_jetton_master. Не
        jetton-перевод, чужой мастер или не сконфигурированный мастер — None.

        session — не используется (резерв под будущий deposit_service).
        """
        del session
        if not isinstance(tx, dict):
            return None
        in_msg = tx.get("in_msg")
        if not isinstance(in_msg, dict):
            return None

        body_cell = self._extract_in_msg_body(in_msg)
        if body_cell is None:
            return None

        try:
            parser = body_cell.begin_parse()
            if parser.load_uint(32) != JETTON_INTERNAL_TRANSFER_OP:
                return None
            query_id = parser.load_uint(64)
            amount_nano = parser.load_coins()
            sender_jetton_wallet = parser.load_address()
        except Exception:
            return None
        if sender_jetton_wallet is None:
            return None

        # get_wallet_data -> (balance, owner, jetton_master, wallet_code).
        wallet_data = await self.run_get_method(
            sender_jetton_wallet, JETTON_WALLET_DATA_METHOD
        )
        if not isinstance(wallet_data, list) or len(wallet_data) < 3:
            raise ValueError("Jetton wallet data: неожиданный ответ.")
        owner = wallet_data[1]
        jetton_master = wallet_data[2]
        if not isinstance(owner, Address) or not isinstance(jetton_master, Address):
            raise ValueError("Jetton wallet data: owner/master не адреса.")

        expected_master = settings.ton_root_jetton_master
        if not expected_master:
            return None
        if jetton_master.to_str(is_user_friendly=False) != Address(
            expected_master
        ).to_str(is_user_friendly=False):
            return None

        return {
            "tx_hash": tx.get("hash"),
            "lt": tx.get("lt"),
            "query_id": query_id,
            "from_address": owner.to_str(is_user_friendly=True),
            "to_address": in_msg.get("destination"),
            "jetton_master": jetton_master.to_str(is_user_friendly=True),
            "amount_nano": amount_nano,
            "raw_payload": tx,
        }


def _new_query_id() -> int:
    """Уникальный uint64 query_id (fallback, если вызывающий не передал свой)."""
    value = secrets.randbits(64)
    return value if value else 1


def _normalize_query_id(query_id: int | str | None) -> int:
    """Привести query_id к uint64; None -> сгенерировать уникальный."""
    if query_id is None:
        return _new_query_id()
    try:
        value = int(query_id)
    except (TypeError, ValueError):
        raise MissionEngineError(
            422, "query_id должен быть uint64."
        ) from None
    if not 0 <= value <= MAX_TON_QUERY_ID:
        raise MissionEngineError(
            422, "query_id должен быть uint64 (0..2^64-1)."
        )
    return value


def _jetton_transfer_body(
    to_address: Address, amount_nano: int, query_id: int
) -> Cell:
    """Тело transfer (TEP-74) в Jetton wallet: OP, сумма, получатель.

    Поля: query_id (uint64, A7 — id payout attempt), jetton_amount=amount_nano,
    to_owner, response_dest=None, custom_payload=None, forward_ton_amount=0,
    forward_payload=None.
    Комиссию за обработку transfer Jetton wallet берёт из value сообщения
    (передаётся через amount=JETTON_TRANSFER_GAS в wallet.transfer).
    """
    return (
        begin_cell()
        .store_uint(JETTON_TRANSFER_OP, 32)
        .store_uint(query_id, 64)  # query_id (A7: уникальный id выплаты)
        .store_coins(amount_nano)  # jetton_amount (сумма в наноROOT)
        .store_address(to_address)  # to_owner — TON-адрес игрока
        .store_address(None)  # response_dest
        .store_bit(0)  # custom_payload: None
        .store_coins(0)  # forward_ton_amount: 0 (без комментария)
        .store_bit(0)  # forward_payload: None
        .end_cell()
    )


async def get_jetton_wallet_address(
    minter: Address, owner: Address, provider
) -> Address:
    """Jetton-wallet адрес владельца у минтера ROOT (get_wallet_address).

    Адрес дочернего Jetton wallet'а вычисляет сам контракт минтера
    (get-method get_wallet_address(owner)) — надёжнее локальной симуляции.
    """
    result = await provider.run_get_method(
        minter, "get_wallet_address", stack=[owner]
    )
    if not result:
        raise MissionEngineError(503, "Jetton wallet не определён (пустой ответ).")
    jetton_wallet = result[0]
    if not isinstance(jetton_wallet, Address):
        raise MissionEngineError(
            503, "Jetton wallet не определён (неожиданный ответ)."
        )
    return jetton_wallet


async def send_jetton_transfer(
    to_address: str,
    amount_nano: int,
    query_id: int | str | None = None,
) -> str:
    """Перевод Jetton ROOT из «спец» payout-кошелька на TON-адрес игрока.

    Возвращает tx_hash (hash внешнего сообщения) — в 11.5-a он сохраняется
    в WithdrawalRequest.ton_tx_hash. Конфигурационные проверки — 503
    (мнемоника в .env, master/endpoint — env), игровые ошибки — 422.
    Сеть/endpoint не вшиваются: приходят из settings (TON_NETWORK).

    query_id (A7) — уникальный id попытки выплаты (uint64). Вызывающий
    (withdrawal_service) передаёт его из PayoutAttempt.query_id, чтобы
    blockchain-операция была идемпотентной. Без query_id генерируется
    уникальный uint64 (fallback для ручных вызовов).
    """
    if not settings.ton_payout_mnemonic:
        raise MissionEngineError(
            503, "TON payout wallet не настроен (нет мнемоники в .env)."
        )
    if not settings.ton_root_jetton_master:
        raise MissionEngineError(503, "Jetton master ROOT не настроен.")
    if not settings.ton_api_endpoint:
        raise MissionEngineError(503, "TON_API_ENDPOINT не настроен.")
    if not isinstance(amount_nano, (int,)) or amount_nano <= 0:
        raise MissionEngineError(
            422, "Сумма вывода должна быть положительным целым (наноROOT)."
        )

    normalized_query_id = _normalize_query_id(query_id)

    destination = Address(validate_ton_address(to_address))
    try:
        minter = Address(settings.ton_root_jetton_master)
    except Exception:
        raise MissionEngineError(
            503, "Некорректный Jetton master ROOT в конфигурации."
        ) from None

    provider = _TonCenterProvider(settings.ton_api_endpoint)
    try:
        mnemonics = settings.ton_payout_mnemonic.split()
        wallet = await WalletV4R2.from_mnemonic(mnemonics=mnemonics, provider=provider)
        jetton_wallet_address = await get_jetton_wallet_address(
            minter, wallet.address, provider
        )
        body = _jetton_transfer_body(
            destination, amount_nano, normalized_query_id
        )
        # tx hash приходит из provider.raw_send_message (hash сообщения).
        return await wallet.transfer(
            destination=jetton_wallet_address,
            amount=JETTON_TRANSFER_GAS,
            body=body,
        )
    finally:
        await provider.aclose()


def send_jetton_transfer_sync(
    to_address: str,
    amount_nano: int,
    query_id: int | str | None = None,
) -> str:
    """Синхронная обёртка для HTTP-слоя и админ-задач (FastAPI sync handler)."""
    return asyncio.run(
        send_jetton_transfer(to_address, amount_nano, query_id=query_id)
    )
