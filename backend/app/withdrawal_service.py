"""Сервис заявок на вывод ROOT в TON (этап 11.5-a, roadmap-detailed.md).

Игрок подаёт заявку (status="pending"), ROOT списывается немедленно в холд:
wallet.available_balance -= amount_root + immutable WalletTransaction
(transaction_type="debit", reference_type="withdrawal_hold"). Валидации
(CMS-first): глобальный переключатель ton.withdrawal_enabled, TON-адрес
(ton_service.validate_ton_address), минимальная сумма ton.min_amount_root,
активное ограничение withdrawal_restricted, баланс кошелька, дневной лимит
ton.daily_withdrawal_limit (UTC-сутки). Всё — в одной транзакции
(SessionLocal.begin()): при MissionEngineError транзакция откатывается,
баланс не меняется.

Батч-выплата (process_withdrawal_batch) — этап 11.5-b, здесь НЕ реализуется.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin_player_wallet import ACTIVE_SETTING_STATUS
from app.db import SessionLocal
from app.mission_engine import (
    MissionEngineError,
    _get_root_wallet_for_update,
    _new_id,
    _utcnow,
)
from app.models import SystemSetting, WalletTransaction, WithdrawalRequest
from app.player_restrictions_engine import get_active_restrictions
from app.system_settings_catalog import get_definition
from app.ton_service import validate_ton_address

# --- Ключи CMS (system_settings_catalog.py, категория ton) -------------------

# Глобальный переключатель вывода ROOT → TON (boolean в value_json).
WITHDRAWAL_ENABLED_KEY = "ton.withdrawal_enabled"
# Минимальная сумма вывода в целых ROOT (integer).
WITHDRAWAL_MIN_AMOUNT_KEY = "ton.min_amount_root"
# Дневной лимит вывода на игрока в целых ROOT (integer).
WITHDRAWAL_DAILY_LIMIT_KEY = "ton.daily_withdrawal_limit"

# Reference type immutable-проводки списания в холд.
WITHDRAWAL_HOLD_REFERENCE_TYPE = "withdrawal_hold"

# Статусы заявок, «весящие» в дневном лимите (холд до выплаты/reject).
WITHDRAWAL_HOLD_STATUSES = ("pending", "approved", "processing", "confirmed")


def _read_int_setting(session: Session, key: str, fallback: int) -> int:
    """Активная SystemSetting-запись -> default каталога -> fallback.

    Копия паттерна transfer_service._read_int_setting: лимиты целые,
    неотрицательные; секретов не читаем, только числовые лимиты.
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


def _read_bool_setting(session: Session, key: str, fallback: bool) -> bool:
    """Активная SystemSetting-запись с bool-значением (True/False).

    bool в Python — подкласс int, поэтому читается отдельным ридером:
    иначе True/False попали бы в int-ветку со сдвигом смысла.
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
        and isinstance(setting.value_json, bool)
    ):
        return setting.value_json
    definition = get_definition(key)
    if definition is not None and isinstance(definition.default_value, bool):
        return definition.default_value
    return fallback


def create_withdrawal_request(
    player_id: str,
    amount_root: int,
    to_address: str,
) -> dict:
    """Подать заявку на вывод ROOT в TON (этап 11.5-a).

    Возвращает {"withdrawalId", "amountRoot", "toAddress", "status"}.
    ROOT списывается сразу в холд; возврат при failed/rejected — отдельный
    механизм (11.5-b). Все проверки и проводки — в одной транзакции.
    """
    with SessionLocal.begin() as session:
        # 1. Глобальный переключатель вывода (CMS, ton.withdrawal_enabled).
        if not _read_bool_setting(session, WITHDRAWAL_ENABLED_KEY, False):
            raise MissionEngineError(503, "Вывод ROOT в TON отключён.")

        # 2. TON-адрес: каноническая user-friendly форма (pytoniq).
        canonical_address = validate_ton_address(to_address)

        # 3. Сумма и минимальный вывод (CMS, ton.min_amount_root).
        if amount_root <= 0:
            raise MissionEngineError(422, "Сумма должна быть положительной.")
        min_amount = _read_int_setting(session, WITHDRAWAL_MIN_AMOUNT_KEY, 10)
        if amount_root < min_amount:
            raise MissionEngineError(
                422, f"Сумма меньше минимальной ({min_amount})."
            )

        # 4. Активное ограничение withdrawal_restricted.
        if any(
            r.restriction_type == "withdrawal_restricted"
            for r in get_active_restrictions(session, player_id)
        ):
            raise MissionEngineError(403, "Вывод средств для вас ограничен.")

        # 5. Дневной лимит (UTC-сутки): суммы холд-заявок за сегодня.
        start_of_day = _utcnow().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        daily_sum = session.scalar(
            select(func.coalesce(func.sum(WithdrawalRequest.amount_root), 0)).where(
                WithdrawalRequest.player_id == player_id,
                WithdrawalRequest.status.in_(WITHDRAWAL_HOLD_STATUSES),
                WithdrawalRequest.created_at >= start_of_day,
            )
        ) or 0
        daily_limit = _read_int_setting(
            session, WITHDRAWAL_DAILY_LIMIT_KEY, 5000
        )
        if daily_sum + amount_root > daily_limit:
            raise MissionEngineError(
                429,
                f"Превышен дневной лимит вывода ({daily_limit} ROOT).",
            )

        # 6. ROOT-кошелёк (FOR UPDATE на Postgres) и баланс.
        wallet = _get_root_wallet_for_update(session, player_id)
        if wallet.available_balance < amount_root:
            raise MissionEngineError(409, "Недостаточно ROOT.")

        # 7. Холд: списание + immutable-проводка + заявка pending.
        withdrawal_id = _new_id("withdrawal")
        wallet.available_balance -= amount_root
        session.add(
            WalletTransaction(
                id=_new_id("wallet-transaction"),
                wallet_id=wallet.id,
                amount=amount_root,
                balance_after=wallet.available_balance,
                transaction_type="debit",
                reason=f"Withdrawal hold {withdrawal_id}",
                reference_type=WITHDRAWAL_HOLD_REFERENCE_TYPE,
                reference_id=withdrawal_id,
                metadata_json={"toAddress": canonical_address},
            )
        )
        session.add(
            WithdrawalRequest(
                id=withdrawal_id,
                player_id=player_id,
                amount_root=amount_root,
                to_address=canonical_address,
                status="pending",
            )
        )

        session.flush()

        return {
            "withdrawalId": withdrawal_id,
            "amountRoot": amount_root,
            "toAddress": canonical_address,
            "status": "pending",
        }