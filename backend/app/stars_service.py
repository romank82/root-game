"""Сервис покупки газа за Telegram Stars (10.4-g-2).

- create_invoice_link: создаёт инвойс Stars (createInvoiceLink,
  currency="XTR", provider_token="").
- handle_pre_checkout_query: отвечает answerPreCheckoutQuery (10 сек).
- handle_successful_payment: сохраняет telegram_payment_charge_id и
  начисляет газ в GasWallet (идемпотентно).

Пакеты газа: фронт передаёт gas_amount (10/100/1000); цена — из CMS
economy.gas_pack_{gas_amount}: активная SystemSetting, иначе default
каталога (паттерн transfer_service._read_int_setting).
"""
from __future__ import annotations

import logging
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_player_wallet import ACTIVE_SETTING_STATUS
from app.config import settings
from app.db import SessionLocal
from app.mission_engine import MissionEngineError, _new_id
from app.models import (
    GamePlayer,
    GasWallet,
    GasTransaction,
    StarsPayment,
    SystemSetting,
)
from app.system_settings_catalog import get_definition

logger = logging.getLogger(__name__)


def _bot_api(method: str, payload: dict) -> dict:
    """Вызов Bot API. Возвращает result; ошибки → MissionEngineError(502)."""
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/{method}"
    try:
        response = httpx.post(url, json=payload, timeout=10.0)
    except httpx.HTTPError as exc:
        raise MissionEngineError(502, f"Telegram API недоступен: {exc}") from exc
    data = response.json()
    if not data.get("ok"):
        description = data.get("description", "unknown error")
        raise MissionEngineError(502, f"Telegram API error: {description}")
    return data.get("result") or {}


def _read_int_setting(session: Session, key: str, fallback: int) -> int:
    """Активная SystemSetting-запись -> default каталога -> fallback.

    Паттерн transfer_service._read_int_setting: админ может переопределить
    значение в CMS, иначе берётся default каталога.
    """
    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.status == ACTIVE_SETTING_STATUS,
        )
    )
    if (
        setting is not None
        and getattr(setting, "status", None) == ACTIVE_SETTING_STATUS
        and isinstance(setting.value_json, int)
        and setting.value_json >= 0
    ):
        return setting.value_json
    definition = get_definition(key)
    if definition is not None and isinstance(definition.default_value, int):
        return definition.default_value
    return fallback


def _gas_pack_price(gas_amount: int) -> int:
    """Цена пакета газа в звёздах из CMS (economy.gas_pack_{N})."""
    key = f"economy.gas_pack_{gas_amount}"
    with SessionLocal() as session:
        price = _read_int_setting(session, key, -1)
    if price <= 0:
        raise MissionEngineError(400, f"Пакет газа {gas_amount} не настроен.")
    return price


def create_invoice_link(player_id: str, gas_amount: int) -> dict:
    """Создать инвойс Stars на покупку газа.

    Возвращает {invoiceLink, referenceId, gasAmount, amountStars}.
    """
    price = _gas_pack_price(gas_amount)
    reference_id = _new_id("stars-invoice")
    payload = reference_id  # payload инвойса = reference_id (для сопоставления)

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise MissionEngineError(404, "Игрок не найден.")
        session.add(
            StarsPayment(
                id=_new_id("stars-payment"),
                player_id=player_id,
                gas_amount=Decimal(gas_amount),
                amount_stars=price,
                telegram_payment_charge_id=None,
                status="pending",
                reference_id=reference_id,
                payload=payload,
            )
        )

    # Вызов Bot API вне транзакции (чтобы не держать lock на время сети).
    result = _bot_api(
        "createInvoiceLink",
        {
            "title": f"Газ: {gas_amount}",
            "description": f"Покупка {gas_amount} газа за {price} звёзд.",
            "payload": payload,
            "currency": "XTR",
            "provider_token": "",
            "prices": [{"label": f"{gas_amount} газа", "amount": price}],
        },
    )
    # Bot API возвращает result как строку-ссылку (не объект);
    # допускаем и объект с полем invoice_link.
    if isinstance(result, str):
        invoice_link = result
    else:
        invoice_link = (result or {}).get("invoice_link")
    if not invoice_link:
        raise MissionEngineError(502, "Telegram не вернул ссылку инвойса.")
    return {
        "invoiceLink": invoice_link,
        "referenceId": reference_id,
        "gasAmount": gas_amount,
        "amountStars": price,
    }


def send_gas_invoice(player_id: str, gas_amount: int) -> dict:
    """10.4-fix: отправить инвойс Stars в чат с ботом (sendInvoice).
    Обход бага Android (WebView openInvoice). Возвращает
    {referenceId, gasAmount, amountStars, chatId}."""
    price = _gas_pack_price(gas_amount)
    reference_id = _new_id("stars-invoice")
    payload = reference_id

    with SessionLocal.begin() as session:
        player = session.get(GamePlayer, player_id)
        if player is None:
            raise MissionEngineError(404, "Игрок не найден.")
        chat_id = player.external_id
        if not chat_id:
            raise MissionEngineError(400, "Нет Telegram chat_id.")
        session.add(
            StarsPayment(
                id=_new_id("stars-payment"),
                player_id=player_id,
                gas_amount=Decimal(gas_amount),
                amount_stars=price,
                telegram_payment_charge_id=None,
                status="pending",
                reference_id=reference_id,
                payload=payload,
            )
        )

    # Вызов Bot API вне транзакции (чтобы не держать lock на время сети).
    _bot_api(
        "sendInvoice",
        {
            "chat_id": chat_id,
            "title": f"Газ: {gas_amount}",
            "description": f"Покупка {gas_amount} газа за {price} звёзд.",
            "payload": payload,
            "currency": "XTR",
            "provider_token": "",
            "prices": [{"label": f"{gas_amount} газа", "amount": price}],
        },
    )
    return {
        "referenceId": reference_id,
        "gasAmount": gas_amount,
        "amountStars": price,
        "chatId": chat_id,
    }


def handle_pre_checkout_query(update: dict) -> None:
    """pre_checkout_query: ответить answerPreCheckoutQuery в течение 10 сек."""
    query = update.get("pre_checkout_query") or {}
    query_id = query.get("id")
    payload = query.get("invoice_payload") or ""
    if not query_id:
        return  # нечего отвечать

    ok = True
    # Проверка: StarsPayment с payload существует (pending).
    with SessionLocal() as session:
        payment = session.scalar(
            select(StarsPayment).where(
                StarsPayment.reference_id == payload,
                StarsPayment.status == "pending",
            )
        )
        if payment is None:
            ok = False
    _bot_api(
        "answerPreCheckoutQuery",
        {
            "pre_checkout_query_id": query_id,
            "ok": ok,
            **(
                {"error_message": "Платёж не найден или уже обработан."}
                if not ok
                else {}
            ),
        },
    )


def handle_successful_payment(update: dict) -> None:
    """successful_payment: сохранить charge_id + начислить газ (идемпотентно)."""
    message = update.get("message") or {}
    payment_info = message.get("successful_payment") or {}
    payload = payment_info.get("invoice_payload") or ""
    charge_id = payment_info.get("telegram_payment_charge_id")
    if not payload or not charge_id:
        return

    with SessionLocal.begin() as session:
        payment = session.scalar(
            select(StarsPayment)
            .where(StarsPayment.reference_id == payload)
            .with_for_update()
        )
        if payment is None:
            raise MissionEngineError(404, "Платёж не найден.")
        if payment.status == "completed":
            return  # идемпотентно: повтор successful_payment — не начислять
        payment.status = "completed"
        payment.telegram_payment_charge_id = charge_id

        # Начислить газ (GasWallet + GasTransaction, reference_type="stars_purchase").
        gas_wallet = session.scalar(
            select(GasWallet)
            .where(GasWallet.player_id == payment.player_id)
            .with_for_update()
        )
        if gas_wallet is None:
            gas_wallet = GasWallet(
                id=_new_id("gas-wallet"),
                player_id=payment.player_id,
                balance=Decimal("0"),
            )
            session.add(gas_wallet)
            session.flush()

        new_balance = gas_wallet.balance + payment.gas_amount
        gas_wallet.balance = new_balance
        session.add(
            GasTransaction(
                id=_new_id("gas-transaction"),
                gas_wallet_id=gas_wallet.id,
                amount=payment.gas_amount,
                balance_after=new_balance,
                transaction_type="credit",
                reason=f"Stars purchase {payment.reference_id}",
                reference_type="stars_purchase",
                reference_id=payment.reference_id,
                metadata_json={
                    "amountStars": payment.amount_stars,
                    "chargeId": charge_id,
                },
            )
        )
        session.flush()

        # 13.3-b-3: лог gas.purchased (PlayerEvent, аналитика/антифрод).
        # Газ начислен: GasWallet + GasTransaction зафиксированы в
        # транзакции. Запись — в SAVEPOINT (begin_nested): та же
        # транзакция, собственный флаш; при сбое журнала откатится только
        # savepoint, коммит начисления газа не будет отравлен (иначе
        # PendingRollbackError на commit — проверено эмпирически). Лог не
        # важнее начисления — logger.warning. Повтор successful_payment
        # (status == "completed") ушёл в return выше — событие пишется
        # один раз за покупку.
        try:
            # Lazy импорт: player_events импортирует _new_id из
            # mission_engine, который транзитивно импортирует и этот
            # модуль — top-level импорт сюда создал бы цикл.
            from app.player_events import record_player_event

            with session.begin_nested():
                record_player_event(
                    session,
                    payment.player_id,
                    "gas.purchased",
                    payload={
                        # gas_amount — Numeric(18,4)/Decimal: str()
                        # сохраняет точность без float-конверсий.
                        "gasAmount": str(payment.gas_amount),
                        "amountStars": payment.amount_stars,
                        "referenceId": payment.reference_id,
                        "chargeId": charge_id,
                    },
                    correlation_id=None,
                )
        except Exception as error:  # noqa: BLE001 — лог не важнее газа
            logger.warning("player_event gas.purchased failed: %s", error)
