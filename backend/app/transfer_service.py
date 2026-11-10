from __future__ import annotations

import logging
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin_player_wallet import ACTIVE_SETTING_STATUS
from app.country_policy import is_feature_restricted
from app.db import SessionLocal
from app.mission_engine import (
    ROOT_CURRENCY,
    MissionEngineError,
    _get_root_wallet_for_update,
    _new_id,
    _utcnow,
)
from app.models import (
    GamePlayer,
    GasTransaction,
    GasWallet,
    PlayerTransfer,
    SystemSetting,
    Wallet,
    WalletTransaction,
)
from app.player_restrictions_engine import get_active_restrictions
from app.system_settings_catalog import get_definition

logger = logging.getLogger(__name__)

# Ключи лимитов из CMS (system_settings_catalog.py, категория economy).
TRANSFER_MIN_KEY = "economy.transfer_min_amount"
TRANSFER_MAX_KEY = "economy.transfer_max_amount"
DAILY_TRANSFER_LIMIT_KEY = "economy.daily_transfer_limit"
TRANSFER_MINIMUM_EARNED_ROOT_KEY = "economy.transfer_minimum_earned_root"
GAS_FEE_PERCENT_KEY = "economy.gas_fee_percent"

# Reference types проводок перевода: у debit и credit общий reference_id = request_id.
TRANSFER_DEBIT_REFERENCE_TYPE = "player_transfer_debit"
TRANSFER_CREDIT_REFERENCE_TYPE = "player_transfer_credit"
# Комиссия за перевод списывается газом (10.4-i): debit gas-проводка.
TRANSFER_FEE_GAS_REFERENCE_TYPE = "transfer_fee_gas"

# Sprint 11.8 NanoROOT: 1 ROOT = 10^8 наноROOT.
NANO_PER_ROOT = 100_000_000
# В mission_engine "mission_reward" — инлайн-строка (константы нет); зеркало здесь.
MISSION_REWARD_REFERENCE_TYPE = "mission_reward"


def _read_int_setting(session: Session, key: str, fallback: int) -> int:
    """Активная SystemSetting-запись -> default каталога -> fallback.

    Паттерн _read_threshold (admin_player_wallet). Значения лимитов целые,
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


def _read_limits(session: Session) -> dict:
    """Лимиты переводов из CMS (min/max/daily/earned) с фолбэком на каталог."""
    return {
        "min": _read_int_setting(session, TRANSFER_MIN_KEY, 1),
        "max": _read_int_setting(session, TRANSFER_MAX_KEY, 10000),
        "daily": _read_int_setting(session, DAILY_TRANSFER_LIMIT_KEY, 50000),
        "earned": _read_int_setting(
            session, TRANSFER_MINIMUM_EARNED_ROOT_KEY, 50
        ),
    }


def _is_blocked_or_suspended(session: Session, player_id: str) -> bool:
    return any(
        r.restriction_type in ("blocked", "suspended")
        for r in get_active_restrictions(session, player_id)
    )


def _has_transfer_restricted(session: Session, player_id: str) -> bool:
    return any(
        r.restriction_type == "transfer_restricted"
        for r in get_active_restrictions(session, player_id)
    )


def _wallet_balance_or_zero(session: Session, player_id: str) -> int:
    """Баланс ROOT без блокировки (для идемпотентного ответа)."""
    wallet = session.scalar(
        select(Wallet).where(
            Wallet.player_id == player_id,
            Wallet.currency == ROOT_CURRENCY,
        )
    )
    return wallet.available_balance if wallet is not None else 0


def _wallet_balance_nano_or_zero(session: Session, player_id: str) -> int:
    """Баланс ROOT в наноROOT без блокировки (для идемпотентного ответа).

    Sprint 8.x-fractional-transfer (шаг B): additive-поле fromBalanceNano/
    toBalanceNano для идемпотентного повтора; NULL-nano fallback на legacy.
    """
    wallet = session.scalar(
        select(Wallet).where(
            Wallet.player_id == player_id,
            Wallet.currency == ROOT_CURRENCY,
        )
    )
    if wallet is None:
        return 0
    if wallet.available_balance_nano is not None:
        return wallet.available_balance_nano
    return wallet.available_balance * NANO_PER_ROOT


def _wallet_id_or_none(session: Session, player_id: str) -> str | None:
    return session.scalar(
        select(Wallet.id).where(
            Wallet.player_id == player_id,
            Wallet.currency == ROOT_CURRENCY,
        )
    )


def transfer_root(
    session: Session,
    from_player_id: str,
    to_player_id: str,
    amount: int | None = None,
    request_id: str | None = None,
    amount_nano: int | None = None,
) -> dict:
    """Атомарный перевод ROOT между игроками (10.5-a).

    Транзакцию открывает вызывающий (entrypoint/роутер через
    SessionLocal.begin()). Здесь — только проверки, проводки и flush.
    Идемпотентность — уникальный (from_player_id, reference_id): повторный
    запрос с тем же request_id возвращает сохранённый результат без
    повторного перевода.

    Sprint 8.x-fractional-transfer (шаг A1): additive-приём ``amount_nano``.
    Достаточно передать одну из сумм; ``amount`` (целый ROOT) сохранён для
    обратной совместимости (позиция 4-го аргумента не менялась). Вся логика
    (балансы, ledger) ведётся по ``amount_nano``; legacy-поле ``amount``
    пишется как floor(amount_nano / 10^8) — для старых читателей.
    Если переданы оба поля, приоритет у ``amount_nano``.
    """
    # 0. Нормализация суммы: nanoROOT — источник истины.
    if amount is None and amount_nano is None:
        raise ValueError("amount or amount_nano required")
    if not request_id:
        raise ValueError("request_id required")
    if amount_nano is None:
        # amount задан: оба None отсечены проверкой выше.
        amount_nano = amount * NANO_PER_ROOT
    if amount_nano <= 0:
        raise MissionEngineError(422, "Сумма должна быть положительной.")
    # Legacy целое ROOT (старые поля, ответ, CheckConstraint
    # ck_player_transfers_amount_positive: amount > 0 — models.py:1576-1579).
    # При сумме < 1 ROOT floor даёт 0, поэтому временно max(1, ...).
    # TODO(A2): решение по constraint/legacy-полю — отдельной append-only
    # миграцией; здесь constraint не меняем.
    amount = max(1, amount_nano // NANO_PER_ROOT)

    # 1. Идемпотентность ДО блокировок кошельков.
    existing = session.scalar(
        select(PlayerTransfer).where(
            PlayerTransfer.from_player_id == from_player_id,
            PlayerTransfer.reference_id == request_id,
        )
    )
    if existing is not None:
        return {
            "transferId": existing.id,
            "fromPlayerId": existing.from_player_id,
            "toPlayerId": existing.to_player_id,
            "amount": existing.amount,
            # Sprint 8.x-fractional-transfer (шаг B): additive-нано-поля
            # для идемпотентного ответа (NULL-nano -> legacy * 10^8).
            "amountNano": (
                existing.amount_nano
                if existing.amount_nano is not None
                else existing.amount * NANO_PER_ROOT
            ),
            "status": existing.status,
            "fromBalance": _wallet_balance_or_zero(session, from_player_id),
            "toBalance": _wallet_balance_or_zero(session, to_player_id),
            "fromBalanceNano": _wallet_balance_nano_or_zero(session, from_player_id),
            "toBalanceNano": _wallet_balance_nano_or_zero(session, to_player_id),
        }

    # 2. Валидация сторон.
    if from_player_id == to_player_id:
        raise MissionEngineError(422, "Нельзя переводить самому себе.")

    from_player = session.get(GamePlayer, from_player_id)
    if from_player is None:
        raise MissionEngineError(404, "Отправитель не найден.")

    # 13.2-b-2: страна отправителя — restricted с transfer в списке.
    if is_feature_restricted(session, from_player.country, "transfer"):
        raise MissionEngineError(403, "Переводы из вашей страны ограничены.")

    to_player = session.get(GamePlayer, to_player_id)
    if to_player is None:
        raise MissionEngineError(404, "Получатель не найден.")
    if to_player.status != "active":
        raise MissionEngineError(403, "Получатель недоступен.")

    if _is_blocked_or_suspended(session, from_player_id):
        raise MissionEngineError(403, "Отправитель заблокирован или приостановлен.")
    if _is_blocked_or_suspended(session, to_player_id):
        raise MissionEngineError(403, "Получатель заблокирован или приостановлен.")
    if _has_transfer_restricted(session, from_player_id):
        raise MissionEngineError(403, "Переводы для отправителя ограничены.")

    # 3. Лимиты суммы из CMS (значения — целые ROOT, сравнение — в наноROOT).
    limits = _read_limits(session)
    if amount_nano < limits["min"] * NANO_PER_ROOT:
        raise MissionEngineError(422, f"Сумма меньше минимальной ({limits['min']}).")
    if amount_nano > limits["max"] * NANO_PER_ROOT:
        raise MissionEngineError(422, f"Сумма больше максимальной ({limits['max']}).")

    # 4. Порог заработанного ROOT: только подтверждённые mission_reward-кредиты.
    from_wallet_id = _wallet_id_or_none(session, from_player_id)
    earned = 0
    if from_wallet_id is not None:
        earned = session.scalar(
            select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
                WalletTransaction.wallet_id == from_wallet_id,
                WalletTransaction.transaction_type == "credit",
                WalletTransaction.reference_type == MISSION_REWARD_REFERENCE_TYPE,
            )
        ) or 0
    if earned < limits["earned"]:
        raise MissionEngineError(
            403,
            f"Нужно заработать минимум {limits['earned']} ROOT в игре для переводов.",
        )

    # 5. Дневной лимит (UTC-сутки). Sprint 8.x-fractional-transfer (A2-1):
    # сумма считается в наноROOT по точной amount_nano; для старых строк
    # (amount_nano IS NULL) — legacy amount * 10^8 внутри coalesce, чтобы
    # NULL-строки не выпадали из суммы.
    start_of_day = _utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    daily_sum_nano = session.scalar(
        select(
            func.coalesce(
                func.sum(
                    func.coalesce(
                        PlayerTransfer.amount_nano,
                        PlayerTransfer.amount * NANO_PER_ROOT,
                    )
                ),
                0,
            )
        ).where(
            PlayerTransfer.from_player_id == from_player_id,
            PlayerTransfer.status == "completed",
            PlayerTransfer.created_at >= start_of_day,
        )
    ) or 0
    if daily_sum_nano + amount_nano > limits["daily"] * NANO_PER_ROOT:
        raise MissionEngineError(
            429,
            f"Превышен дневной лимит переводов ({limits['daily']} ROOT).",
        )

    # 5b. Комиссия за перевод газом (10.4-i): fee = amount * percent / 100,
    # дробная (без ceil). Процент — из CMS (economy.gas_fee_percent).
    # При percent=0 газ не трогаем (обратная совместимость).
    gas_percent = _read_int_setting(session, GAS_FEE_PERCENT_KEY, 1)
    # Sprint 8.x-fractional-transfer: комиссия от точного наноROOT
    # (для целых сумм эквивалентно прежнему amount * percent / 100).
    gas_fee = (
        Decimal(amount_nano)
        * Decimal(gas_percent)
        / (Decimal(100) * Decimal(NANO_PER_ROOT))
        if gas_percent > 0
        else Decimal("0")
    )
    if gas_fee > 0:
        gas_wallet = session.scalar(
            select(GasWallet)
            .where(GasWallet.player_id == from_player_id)
            .with_for_update()
        )
        if gas_wallet is None or gas_wallet.balance < gas_fee:
            raise MissionEngineError(
                402, "Недостаточно газа для перевода. Купите газ."
            )
        gas_wallet.balance -= gas_fee
        session.add(
            GasTransaction(
                id=_new_id("gas-transaction"),
                gas_wallet_id=gas_wallet.id,
                amount=gas_fee,
                balance_after=gas_wallet.balance,
                transaction_type="debit",
                reason=f"Transfer fee {request_id}",
                reference_type=TRANSFER_FEE_GAS_REFERENCE_TYPE,
                reference_id=request_id,
                metadata_json={
                    "toPlayerId": to_player_id,
                    "percent": gas_percent,
                },
            )
        )

    # 6. Блокировка двух кошельков в детерминированном порядке
    # (sorted по player_id) — защита от deadlock при встречных переводах.
    first_id, second_id = sorted([from_player_id, to_player_id])
    wallet_first = _get_root_wallet_for_update(session, first_id)
    wallet_second = _get_root_wallet_for_update(session, second_id)
    if first_id == from_player_id:
        wallet_from, wallet_to = wallet_first, wallet_second
    else:
        wallet_from, wallet_to = wallet_second, wallet_first

    # Sprint 8.x-fractional-transfer: балансовая логика — по наноROOT.
    # Legacy available_balance (Integer ROOT) — производное floor(nano / 10^8):
    # при сумме < 1 ROOT дробная часть в старом поле не представима, точное
    # значение хранится в available_balance_nano. Если nano ещё NULL (старые
    # строки без backfill), восстанавливаем из legacy-поля.
    wallet_from_nano = wallet_from.available_balance_nano
    if wallet_from_nano is None:
        wallet_from_nano = wallet_from.available_balance * NANO_PER_ROOT
    if wallet_from_nano < amount_nano:
        raise MissionEngineError(409, "Недостаточно ROOT.")
    wallet_to_nano = wallet_to.available_balance_nano
    if wallet_to_nano is None:
        wallet_to_nano = wallet_to.available_balance * NANO_PER_ROOT

    # 7. Проводки debit/credit с фиксацией balance_after.
    transfer_id = _new_id("player-transfer")
    wallet_from_nano -= amount_nano
    wallet_from.available_balance_nano = wallet_from_nano
    wallet_from.available_balance = wallet_from_nano // NANO_PER_ROOT
    session.add(
        WalletTransaction(
            id=_new_id("wallet-transaction"),
            wallet_id=wallet_from.id,
            amount=amount,
            amount_nano=amount_nano,
            balance_after=wallet_from.available_balance,
            balance_after_nano=wallet_from.available_balance_nano,
            transaction_type="debit",
            reason=f"Transfer to {to_player_id}",
            reference_type=TRANSFER_DEBIT_REFERENCE_TYPE,
            reference_id=request_id,
            metadata_json={"toPlayerId": to_player_id, "transferId": transfer_id},
        )
    )
    wallet_to_nano += amount_nano
    wallet_to.available_balance_nano = wallet_to_nano
    wallet_to.available_balance = wallet_to_nano // NANO_PER_ROOT
    session.add(
        WalletTransaction(
            id=_new_id("wallet-transaction"),
            wallet_id=wallet_to.id,
            amount=amount,
            amount_nano=amount_nano,
            balance_after=wallet_to.available_balance,
            balance_after_nano=wallet_to.available_balance_nano,
            transaction_type="credit",
            reason=f"Transfer from {from_player_id}",
            reference_type=TRANSFER_CREDIT_REFERENCE_TYPE,
            reference_id=request_id,
            metadata_json={"fromPlayerId": from_player_id, "transferId": transfer_id},
        )
    )

    # 8. Запись перевода.
    session.add(
        PlayerTransfer(
            id=transfer_id,
            from_player_id=from_player_id,
            to_player_id=to_player_id,
            amount=amount,
            # Sprint 8.x-fractional-transfer: точная сумма в наноROOT
            # (раньше колонка оставалась NULL — баг dual-write).
            amount_nano=amount_nano,
            status="completed",
            reference_id=request_id,
        )
    )

    session.flush()

    # 13.3-b-3: лог transfer.completed (PlayerEvent, аналитика/модерация).
    # Перевод уже проведён: debit/credit + PlayerTransfer зафиксированы в
    # транзакции, transfer_id сгенерирован. Запись — в SAVEPOINT
    # (begin_nested): та же транзакция, собственный флаш; при сбое журнала
    # откатится только savepoint, транзакция перевода не будет отравлена
    # (иначе PendingRollbackError на commit — проверено эмпирически).
    # Лог не важнее перевода — logger.warning. Идемпотентный повтор (тот
    # же request_id) ушёл в early-return выше, поэтому событие пишется
    # один раз за перевод.
    try:
        # Lazy импорт: player_events импортирует _new_id из mission_engine,
        # который транзитивно импортирует и этот модуль — top-level импорт
        # сюда создал бы цикл.
        from app.player_events import record_player_event

        with session.begin_nested():
            record_player_event(
                session,
                from_player_id,
                "transfer.completed",
                payload={
                    "toPlayerId": to_player_id,
                    "amount": amount,
                    "transferId": transfer_id,
                },
                correlation_id=None,
            )
    except Exception as error:  # noqa: BLE001 — лог не важнее перевода
        logger.warning("player_event transfer.completed failed: %s", error)

    return {
        "transferId": transfer_id,
        "fromPlayerId": from_player_id,
        "toPlayerId": to_player_id,
        "amount": amount,
        # Sprint 8.x-fractional-transfer (шаг B): точные наноROOT-суммы
        # (additive); старые целые ключи оставлены для совместимости.
        "amountNano": amount_nano,
        "status": "completed",
        "fromBalance": wallet_from.available_balance,
        "toBalance": wallet_to.available_balance,
        "fromBalanceNano": wallet_from.available_balance_nano,
        "toBalanceNano": wallet_to.available_balance_nano,
    }


def transfer_root_entrypoint(
    from_player_id: str,
    to_player_id: str,
    amount: int | None = None,
    request_id: str | None = None,
    amount_nano: int | None = None,
) -> dict:
    """Точка вызова из HTTP-слоя: перевод в одной атомарной транзакции.

    Sprint 8.x-fractional-transfer (шаг A1): принимает ``amount`` (целый
    ROOT) и/или ``amount_nano`` (наноROOT) — нормализация в transfer_root.
    """
    with SessionLocal.begin() as session:
        return transfer_root(
            session,
            from_player_id,
            to_player_id,
            amount,
            request_id,
            amount_nano,
        )
