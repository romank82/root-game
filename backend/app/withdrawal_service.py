"""Сервис заявок на вывод ROOT в TON (этапы 11.5-a/11.5-b, roadmap-detailed.md).

Игрок подаёт заявку (status="pending"), ROOT списывается немедленно в холд:
wallet.available_balance -= amount_root + immutable WalletTransaction
(transaction_type="debit", reference_type="withdrawal_hold"). Валидации
(CMS-first): глобальный переключатель ton.withdrawal_enabled, TON-адрес
(ton_service.validate_ton_address), минимальная сумма ton.min_amount_root,
активное ограничение withdrawal_restricted, баланс кошелька, дневной лимит
ton.daily_withdrawal_limit (UTC-сутки). Всё — в одной транзакции
(SessionLocal.begin()): при MissionEngineError транзакция откатывается,
баланс не меняется.

11.5-b: process_withdrawal_batch — админский батч-выплата pending-заявок
(игроки с активным withdrawal_restricted пропускаются): processing ->
send_jetton_transfer_sync (Jetton ROOT из payout-кошелька ton_service) ->
confirmed + ton_tx_hash; при ошибке — failed + автоматический возврат холда
игроку (_refund_withdrawal_hold). reject_withdrawal — отклонение одной
заявки с возвратом холда. Админский HTTP-слой — этап 11.6.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin_player_wallet import ACTIVE_SETTING_STATUS
from app.db import SessionLocal
from app.mission_engine import (
    MissionEngineError,
    ROOT_CURRENCY,
    _get_root_wallet_for_update,
    _new_id,
    _utcnow,
)
from app.models import (
    PlayerRestriction,
    SystemSetting,
    Wallet,
    WalletTransaction,
    WithdrawalRequest,
)
from app.player_restrictions_engine import get_active_restrictions
from app.system_settings_catalog import get_definition
from app.ton_service import send_jetton_transfer_sync, validate_ton_address

logger = logging.getLogger(__name__)

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

# Reference type возврата холда (failed/rejected) — immutable credit-проводка.
WITHDRAWAL_REFUND_REFERENCE_TYPE = "withdrawal_refund"

# Статусы, в которых можно отклонить заявку (холд ещё не выплачен).
WITHDRAWAL_REJECTABLE_STATUSES = ("pending", "approved", "processing")

# Лимит заявок в одном батч-выплате (админский операционный лимит).
WITHDRAWAL_BATCH_DEFAULT_LIMIT = 50

# Sprint 11.8 NanoROOT: 1 ROOT = 10^8 наноROOT.
NANO_PER_ROOT = 100_000_000


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
        # Sprint 11.8 NanoROOT: зеркальная запись (dual-write).
        wallet.available_balance_nano = (
            wallet.available_balance * NANO_PER_ROOT
        )
        session.add(
            WalletTransaction(
                id=_new_id("wallet-transaction"),
                wallet_id=wallet.id,
                amount=amount_root,
                amount_nano=amount_root * NANO_PER_ROOT,
                balance_after=wallet.available_balance,
                balance_after_nano=wallet.available_balance_nano,
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
                amount_root_nano=amount_root * NANO_PER_ROOT,
                to_address=canonical_address,
                status="pending",
            )
        )

        session.flush()

        return {
            "withdrawalId": withdrawal_id,
            "amountRoot": amount_root,
            # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
            "amountRootNano": amount_root * NANO_PER_ROOT,
            "toAddress": canonical_address,
            "status": "pending",
        }


def _refund_withdrawal_hold(
    session: Session, withdrawal: WithdrawalRequest
) -> None:
    """Возврат холда ROOT в кошелёк игрока + immutable credit-проводка.

    Вызывается при failed (батч) и rejected (reject_withdrawal).
    Баланс кэша правится атомарно с проводкой — ledger остаётся источником.
    """
    wallet = session.scalar(
        select(Wallet).where(
            Wallet.player_id == withdrawal.player_id,
            Wallet.currency == ROOT_CURRENCY,
        )
    )
    if wallet is None:
        raise MissionEngineError(
            409, "ROOT-кошелёк игрока не найден при возврате холда."
        )

    wallet.available_balance += withdrawal.amount_root
    # Sprint 11.8 NanoROOT: зеркальная запись (dual-write).
    wallet.available_balance_nano = (
        wallet.available_balance * NANO_PER_ROOT
    )
    session.add(
        WalletTransaction(
            id=_new_id("wallet-transaction"),
            wallet_id=wallet.id,
            amount=withdrawal.amount_root,
            amount_nano=withdrawal.amount_root * NANO_PER_ROOT,
            balance_after=wallet.available_balance,
            balance_after_nano=wallet.available_balance_nano,
            transaction_type="credit",
            reason=f"Withdrawal refund {withdrawal.id}",
            reference_type=WITHDRAWAL_REFUND_REFERENCE_TYPE,
            reference_id=withdrawal.id,
            metadata_json={},
        )
    )


def process_withdrawal_batch(
    admin_id: str, limit: int = WITHDRAWAL_BATCH_DEFAULT_LIMIT
) -> dict:
    """Батч-выплата pending-заявок (этап 11.5-b).

    Берутся pending (кроме игроков с активным withdrawal_restricted) по
    created_at, лимитом. Каждая помечается processing, шлётся Jetton
    ROOT через send_jetton_transfer_sync (sync-обёртка ton_service с
    asyncio.run); успех -> confirmed + ton_tx_hash, ошибка -> failed +
    возврат холда в кошелёк игрока. Всё в одной транзакции.

    Возвращает {"batchId", "confirmed", "failed"}.
    """
    batch_id = _new_id("batch")
    confirmed = 0
    failed = 0

    with SessionLocal.begin() as session:
        restricted_player_ids = select(PlayerRestriction.player_id).where(
            PlayerRestriction.restriction_type == "withdrawal_restricted",
            PlayerRestriction.status == "active",
        )
        withdrawals = session.scalars(
            select(WithdrawalRequest)
            .where(
                WithdrawalRequest.status == "pending",
                WithdrawalRequest.player_id.not_in(restricted_player_ids),
            )
            .order_by(WithdrawalRequest.created_at)
            .limit(limit)
        ).all()

        for withdrawal in withdrawals:
            withdrawal.status = "processing"
            withdrawal.batch_id = batch_id
            withdrawal.admin_id = admin_id
            session.flush()
            try:
                amount_nano = withdrawal.amount_root_nano  # уже в nano (Sprint 11.8)
                if amount_nano is None:
                    # Fallback для legacy-заявок без _nano: вычислить из ROOT.
                    amount_nano = withdrawal.amount_root * NANO_PER_ROOT
                tx_hash = send_jetton_transfer_sync(
                    withdrawal.to_address, amount_nano
                )
                withdrawal.status = "confirmed"
                withdrawal.ton_tx_hash = tx_hash
                session.flush()
                confirmed += 1
            except Exception as error:  # noqa: BLE001 — сеть/пайлоад/конфиг
                withdrawal.status = "failed"
                _refund_withdrawal_hold(session, withdrawal)
                session.flush()
                failed += 1
                logger.warning(
                    "Withdrawal %s failed in batch %s: %s",
                    withdrawal.id,
                    batch_id,
                    error,
                )

    return {"batchId": batch_id, "confirmed": confirmed, "failed": failed}


def reject_withdrawal(
    admin_id: str, withdrawal_id: str, reason: str
) -> dict:
    """Отклонить одну заявку (11.5-b): refund холда + status='rejected'.

    404, если заявки нет или она не в статусе pending/approved/processing
    (failed/confirmed/rejected уже закрыты).
    Возвращает {"withdrawalId", "status": "rejected", "reason"}.
    """
    with SessionLocal.begin() as session:
        withdrawal = session.scalar(
            select(WithdrawalRequest).where(
                WithdrawalRequest.id == withdrawal_id,
                WithdrawalRequest.status.in_(WITHDRAWAL_REJECTABLE_STATUSES),
            )
        )
        if withdrawal is None:
            raise MissionEngineError(404, "Активная заявка на вывод не найдена.")

        withdrawal.status = "rejected"
        withdrawal.reason = reason
        withdrawal.admin_id = admin_id
        session.flush()
        _refund_withdrawal_hold(session, withdrawal)
        session.flush()

        return {
            "withdrawalId": withdrawal.id,
            "status": "rejected",
            "reason": reason,
        }

def _serialize_player_withdrawal(withdrawal: WithdrawalRequest) -> dict:
    """Заявка для игрока (11.7-a): только игровые поля.

    id/playerId/batchId/adminId игроку не отдаются — не нужны и лишнее.
    """
    return {
        "withdrawalId": withdrawal.id,
        "amountRoot": withdrawal.amount_root,
        # Sprint 11.8 NanoROOT: параллельное дробное значение (nano).
        "amountRootNano": (
            withdrawal.amount_root_nano
            if withdrawal.amount_root_nano is not None
            else withdrawal.amount_root * NANO_PER_ROOT
        ),
        "toAddress": withdrawal.to_address,
        "status": withdrawal.status,
        "tonTxHash": withdrawal.ton_tx_hash,
        "reason": withdrawal.reason,
        "createdAt": (
            withdrawal.created_at.isoformat() if withdrawal.created_at else None
        ),
        "updatedAt": (
            withdrawal.updated_at.isoformat() if withdrawal.updated_at else None
        ),
    }


def list_player_withdrawals(
    player_id: str,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Список заявок игрока (11.7-a): свои заявки, новее сверху.

    LIMIT clamp 1..200, offset >= 0. Read-only — SessionLocal() без begin(),
    как в admin_withdrawals. Возвращает {withdrawals, total, limit, offset}.
    """
    safe_limit = max(1, min(limit, 200))
    safe_offset = max(0, offset)

    with SessionLocal() as session:
        total = (
            session.scalar(
                select(func.count())
                .select_from(WithdrawalRequest)
                .where(WithdrawalRequest.player_id == player_id)
            )
            or 0
        )
        rows = session.scalars(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.player_id == player_id)
            .order_by(
                WithdrawalRequest.created_at.desc(),
                WithdrawalRequest.id.desc(),
            )
            .offset(safe_offset)
            .limit(safe_limit)
        ).all()

    return {
        "withdrawals": [_serialize_player_withdrawal(row) for row in rows],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }