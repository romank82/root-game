"""Поиск jetton-перевода ROOT в блокчейне по query_id (шаг 4).

Подтверждение выплаты не может опираться на слова админа: нужно увидеть
транзакцию в цепочке. Ищем исходящие сообщения с кошелька выплат, разбираем
тело TEP-74 и сверяем query_id + сумму.

Почему по query_id, а не по хешу транзакции: админ не знает хеш заранее, а
query_id сервер сам выдал при формировании батча — он и есть связь между
заявкой и переводом.

Особенность TON: перевод ROOT идёт в два шага. Кошелёк -> jetton-wallet
владельца (OP 0xf8a7ea5), затем jetton-wallet -> jetton-wallet получателя
(OP 0x178d4519, internal_transfer) с ТЕМ ЖЕ query_id. Поэтому смотрим
исходящие сообщения с адреса кошелька выплат и ищем transfer с нашим query_id.

Транспорт: tonapi.io, а НЕ TonCenter. Причина проверена на живом testnet:
TonCenter v2 getTransactions отдаёт 500 «LITE_SERVER_UNKNOWN: cannot locate
transaction in block with specified logical time» (и для кошелька выплат, и
для jetton-кошельков), а с archival=True — 542 «no workers available».
tonapi.io ту же историю отдаёт стабильно. Если бы поиск остался на TonCenter,
подтверждение выплат никогда бы ничего не находило: владелец заплатил бы,
а заявки висели бы в processing до авто-откката.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pytoniq_core import Cell

from app.config import settings
from app.ton_service import _TonCenterProvider, _boc_bytes
from app.ton_connect_parser import JETTON_TRANSFER_OP

logger = logging.getLogger(__name__)

# TEP-74 internal_transfer: его публикует jetton-кошелёк ОТПРАВИТЕЛЯ и
# присылает jetton-кошельку ПОЛУЧАТЕЛЯ. Наличие такого входящего сообщения с
# нашим query_id — доказательство, что токены реально зачислены.
INTERNAL_TRANSFER_OP = 0x178D4519
INTERNAL_TRANSFER_OP_TONAPI = "0x178d4519"

# Сколько транзакций за один запрос к индексеру (максимум у tonapi — 100).
LOOKUP_LIMIT = 100

# Сколько страниц истории пролистывать (по LOOKUP_LIMIT за страницу).
MAX_PAGES = 5


def _parse_transfer_from_out_msg(out_msg: dict) -> dict[str, Any] | None:
    """Разобрать исходящее сообщение jetton-перевода (OP 0xf8a7ea5)."""
    msg_data = out_msg.get("msg_data")
    if isinstance(msg_data, dict):
        body = msg_data.get("body")
    else:
        body = out_msg.get("raw_body") or out_msg.get("body")
    if not body:
        return None
    try:
        cell = Cell.one_from_boc(_boc_bytes(body))
    except Exception:  # noqa: BLE001 — не наш формат
        return None

    try:
        parser = cell.begin_parse()
        if parser.load_uint(32) != JETTON_TRANSFER_OP:
            return None
        query_id = parser.load_uint(64)
        amount_nano = parser.load_coins()
        recipient = parser.load_address()
    except Exception:  # noqa: BLE001 — обрезанное/чужое тело
        return None
    if recipient is None:
        return None

    return {
        "queryId": str(query_id),
        "amountNano": amount_nano,
        "recipient": recipient.to_str(is_user_friendly=True),
    }


def _indexer_endpoint() -> str:
    """Адрес индексера tonapi: явная настройка или по сети."""
    configured = (settings.ton_indexer_endpoint or "").strip().rstrip("/")
    if configured:
        return configured
    if (settings.ton_network or "testnet").lower() == "mainnet":
        return "https://tonapi.io/v2"
    return "https://testnet.tonapi.io/v2"


def _parse_internal_transfer(in_msg: dict) -> dict[str, Any] | None:
    """Разобрать входящий internal_transfer (0x178d4519) из tonapi.

    Тело: op(32) + query_id(64) + amount:coins + from:MsgAddress + ...
    Это сообщение приходит на jetton-кошелёк получателя, и его наличие
    доказывает зачисление токенов.
    """
    raw_body = in_msg.get("raw_body")
    if not raw_body:
        return None
    try:
        cell = Cell.one_from_boc(_boc_bytes(raw_body))
    except Exception:  # noqa: BLE001 — не наш формат
        return None

    try:
        parser = cell.begin_parse()
        if parser.load_uint(32) != INTERNAL_TRANSFER_OP:
            return None
        query_id = parser.load_uint(64)
        amount_nano = parser.load_coins()
    except Exception:  # noqa: BLE001 — обрезанное тело
        return None

    return {"queryId": str(query_id), "amountNano": amount_nano}


async def _lookup_async(
    query_id: str, amount_nano: int, jetton_wallet: str | None = None
) -> dict[str, Any] | None:
    """Проверить, что ROOT ДОШЛИ получателю, а не просто отправлены.

    Почему так: исходящее сообщение transfer (0xf8a7ea5) с кошелька выплат
    ещё не значит, что игрок получил токены. Если jetton-кошелёк получателя
    не существует (или не хватило газа), сообщение отбивается (bounce,
    op 0xffffffff) — деньги остаются у владельца. Это случилось на первой
    реальной выплате: транзакция «успешна», заявка подтверждена, а игрок
    ничего не получил.

    Доказательство доставки — ВХОДЯЩИЙ internal_transfer (0x178d4519) на
    jetton-кошелёк получателя с нашим query_id и суммой. Его публикует
    jetton-кошелёк отправителя, и он существует, только если перевод реально
    принят.

    Транспорт — tonapi: TonCenter getTransactions на тестнете отдаёт 500.
    """
    endpoint = _indexer_endpoint()
    timeout = httpx.Timeout(20.0)

    from pytoniq_core import Address

    async with httpx.AsyncClient(timeout=timeout) as client:
        # --- Основной путь: смотрим входящие на jetton-кошелёк получателя ---
        if jetton_wallet:
            raw = Address(jetton_wallet).to_str(is_user_friendly=False)
            url = (
                f"{endpoint}/blockchain/accounts/"
                f"{raw.replace(':', '%3A')}/transactions"
            )
            before_lt: str | None = None
            for _page in range(MAX_PAGES):
                params: dict[str, Any] = {"limit": LOOKUP_LIMIT}
                if before_lt:
                    params["before_lt"] = before_lt
                response = await client.get(url, params=params)
                response.raise_for_status()
                transactions = response.json().get("transactions") or []
                if not transactions:
                    break

                for tx in transactions:
                    if not tx.get("success"):
                        # Неуспешная транзакция не доказывает доставку.
                        continue
                    incoming = tx.get("in_msg") or {}
                    if incoming.get("op_code") != INTERNAL_TRANSFER_OP_TONAPI:
                        continue
                    if incoming.get("bounced"):
                        continue

                    parsed = _parse_internal_transfer(incoming)
                    if parsed is None:
                        continue
                    if parsed["queryId"] != str(query_id):
                        continue
                    if parsed["amountNano"] != amount_nano:
                        logger.warning(
                            "internal_transfer с query_id %s найден, но сумма "
                            "%s != %s",
                            query_id,
                            parsed["amountNano"],
                            amount_nano,
                        )
                        continue
                    return {
                        "txHash": tx.get("hash"),
                        "lt": tx.get("lt"),
                        "recipient": jetton_wallet,
                        "amountNano": parsed["amountNano"],
                        "delivered": True,
                    }

                last = transactions[-1]
                next_lt = last.get("lt")
                if next_lt is None:
                    break
                before_lt = str(next_lt)
            return None

        # --- Фолбэк: адрес получателя неизвестен, проверяем отправку ---
        wallet = _read_payout_wallet()
        if not wallet:
            raise RuntimeError("ton.payout_wallet не настроен.")

        raw_wallet = Address(wallet).to_str(is_user_friendly=False).replace(":", "%3A")
        url = f"{endpoint}/blockchain/accounts/{raw_wallet}/transactions"
        before_lt = None
        for _page in range(MAX_PAGES):
            params: dict[str, Any] = {"limit": LOOKUP_LIMIT}
            if before_lt:
                params["before_lt"] = before_lt
            response = await client.get(url, params=params)
            response.raise_for_status()
            transactions = response.json().get("transactions") or []
            if not transactions:
                break

            for tx in transactions:
                if not tx.get("success"):
                    continue
                for out_msg in tx.get("out_msgs") or []:
                    if out_msg.get("bounced"):
                        # Отбитое сообщение — деньги вернулись.
                        continue
                    parsed = _parse_transfer_from_out_msg(out_msg)
                    if parsed is None:
                        continue
                    if parsed["queryId"] != str(query_id):
                        continue
                    if parsed["amountNano"] != amount_nano:
                        logger.warning(
                            "query_id %s найден, но сумма %s != %s",
                            query_id, parsed["amountNano"], amount_nano,
                        )
                        continue
                    # Отправлено, но доставка не подтверждена — помечаем явно.
                    return {
                        "txHash": tx.get("hash"),
                        "lt": tx.get("lt"),
                        "recipient": parsed["recipient"],
                        "amountNano": parsed["amountNano"],
                        "delivered": False,
                    }
            last = transactions[-1]
            next_lt = last.get("lt")
            if next_lt is None:
                break
            before_lt = str(next_lt)
    return None


def _read_payout_wallet() -> str:
    """Адрес кошелька выплат из CMS (без сессии — короткоживущий коннект)."""
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SystemSetting

    with SessionLocal() as session:
        setting = session.scalar(
            select(SystemSetting).where(
                SystemSetting.key == "ton.payout_wallet",
                SystemSetting.status == "active",
            )
        )
        value = getattr(setting, "value_json", "")
        return value.strip() if isinstance(value, str) else ""


def lookup_transfer_by_query_id(
    query_id: str, amount_nano: int, jetton_wallet: str | None = None
) -> dict[str, Any] | None:
    """Синхронная обёртка: дошли ли ROOT до получателя.

    jetton_wallet — jetton-кошелёк получателя. Если известен, проверяется
    факт зачисления (входящий internal_transfer); иначе — только факт
    отправки, и результат помечается delivered=False.
    """
    return asyncio.run(_lookup_async(query_id, amount_nano, jetton_wallet))


async def _resolve_many_async(addresses: list[str]) -> dict[str, str | None]:
    """Адреса jetton-кошельков ROOT для списка владельцев.

    Нужно для оплаты: переводить надо на jetton-wallet получателя, а не на
    его обычный адрес. Адрес считает сам контракт минтера (get_wallet_address),
    поэтому без TON API его не получить — тогда возвращаем None, и фронт
    блокирует оплату с понятным сообщением.
    """
    from pytoniq_core import Address

    from app.ton_service import get_jetton_wallet_address

    if not addresses:
        return {}
    endpoint = settings.ton_api_endpoint
    master = settings.ton_root_jetton_master
    if not endpoint or not master:
        logger.warning(
            "Jetton wallet resolution skipped: TON_API_ENDPOINT/мастер не настроены"
        )
        return {address: None for address in addresses}

    try:
        minter = Address(master)
    except Exception:  # noqa: BLE001
        logger.warning("Некорректный TON_ROOT_JETTON_MASTER: %s", master)
        return {address: None for address in addresses}

    result: dict[str, str | None] = {}
    provider = _TonCenterProvider(endpoint)
    try:
        for address in addresses:
            try:
                jetton_wallet = await get_jetton_wallet_address(
                    minter, Address(address), provider
                )
                result[address] = jetton_wallet.to_str(is_user_friendly=True)
            except Exception as error:  # noqa: BLE001 — один адрес не должен
                # ронять весь список
                logger.warning(
                    "Jetton wallet lookup failed for %s: %s", address, error
                )
                result[address] = None
    finally:
        await provider.aclose()
    return result


def resolve_jetton_wallets(addresses: list[str]) -> dict[str, str | None]:
    """Синхронная обёртка: владелец -> адрес его jetton-кошелька ROOT."""
    return asyncio.run(_resolve_many_async(addresses))
