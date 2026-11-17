"""Поллер входящих ROOT-jetton (Sprint 1.6): отдельный процесс.

Цикл: тонкий поллер поверх ton_service (getTransactions/parse_jetton_transfer)
и deposit_service (process_incoming_transfer). Работает как standalone-процесс
(systemd: deploy/root-game-deposit-poller.service), НЕ внутри gunicorn: иначе
при -w 3 было бы 3 поллера (пункт C8 аудита), а с учётом денег это критично.

poll_once:
  1. рубильник ton.deposit_enabled=false -> 0 (ничего не читаем);
  2. адрес сейфа = CMS ton.deposit_wallet (пусто -> 0, warning);
  3. курсор singleton (ton_poll_cursor) -> getTransactions(lt/hash);
  4. tx в обратном порядке (от старых к новым): parse -> process -> сдвиг курсора;
  5. commit; в finally закрываем httpx-клиент провайдера.

run_forever: бесконечный цикл с POLL_INTERVAL_SECONDS и защитой от исключений.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.deposit_service import (
    DEPOSIT_ENABLED_KEY,
    _read_bool_setting,
    get_deposit_wallet_address,
    process_incoming_transfer,
)
from app.mission_engine import MissionEngineError
from app.models import TonPollCursor
from app.ton_service import _TonCenterProvider

logger = logging.getLogger(__name__)

# Интервал опроса (сек) и размер страницы getTransactions.
POLL_INTERVAL_SECONDS = 30
POLL_LIMIT = 20
# Фиксированный id singleton-курсора (см. TonPollCursor).
CURSOR_ID = "ton_poll_cursor"


def _get_or_create_cursor(session: Session) -> TonPollCursor:
    """Singleton-курсор поллинга: получить или создать (last_lt=0, hash='')."""
    cursor = session.get(TonPollCursor, CURSOR_ID)
    if cursor is None:
        cursor = TonPollCursor(id=CURSOR_ID, last_lt=0, last_hash="")
        session.add(cursor)
        session.flush()
    return cursor


async def poll_once(session: Session) -> int:
    """Один проход поллинга. Возвращает число зачтённых/обработанных переводов.

    Транзакцию (commit) ведёт поллер. Ошибки конфигурации (нет deposit wallet,
    нет endpoint) — не исключение наружу, а warning + 0 (поллер не должен
    падать из-за незаполненной CMS).
    """
    # 1. Рубильник депозита (CMS ton.deposit_enabled).
    if not _read_bool_setting(session, DEPOSIT_ENABLED_KEY, False):
        return 0

    # 2. Адрес сейфа (CMS ton.deposit_wallet).
    try:
        address = get_deposit_wallet_address(session)
    except MissionEngineError as error:
        logger.warning("Deposit poller: %s", error.detail)
        return 0

    # 3. Курсор (singleton) и провайдер.
    cursor = _get_or_create_cursor(session)
    if not settings.ton_api_endpoint:
        logger.warning("Deposit poller: TON_API_ENDPOINT не настроен.")
        return 0

    provider = _TonCenterProvider(settings.ton_api_endpoint)
    processed = 0
    try:
        transactions = await provider.get_transactions(
            address,
            limit=POLL_LIMIT,
            lt=cursor.last_lt or None,
            l_hash=cursor.last_hash or None,
        )
        # От старых к новым: TonCenter отдаёт newest-first.
        for tx in reversed(transactions or []):
            parsed = await provider.parse_jetton_transfer(tx, session)
            if parsed is not None:
                process_incoming_transfer(session, parsed)
                processed += 1
            # TonCenter возвращает lt строкой (может превышать int64);
            # приводим к int для BigInteger, hash — к str.
            if tx.get("lt") is not None:
                cursor.last_lt = int(tx["lt"])
            if tx.get("hash"):
                cursor.last_hash = str(tx["hash"])
            session.flush()
        session.commit()
    finally:
        await provider.aclose()

    return processed


async def run_forever() -> None:
    """Бесконечный цикл поллинга с паузой POLL_INTERVAL_SECONDS.

    Любое исключение итерации логируется и не останавливает процесс.
    """
    while True:
        try:
            with SessionLocal() as session:
                await poll_once(session)
        except Exception as error:  # noqa: BLE001 — поллер не должен падать
            logger.exception("Deposit poller iteration failed: %s", error)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_forever())
