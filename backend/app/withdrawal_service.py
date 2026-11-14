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
(игроки с активным withdrawal_restricted пропускаются). A6+A7 (durable
outbox): перед сетевым вызовом в отдельной транзакции создаётся immutable
PayoutAttempt(status='sending', query_id=uint64) и заявка переводится в
processing; затем send_jetton_transfer_sync (Jetton ROOT из payout-кошелька
ton_service) с query_id попытки; результат фиксируется отдельной транзакцией
(sent + ton_tx_hash -> confirmed; либо failed + возврат холда игроку
_refund_withdrawal_hold). Повторный batch не отправляет выплату, если для
заявки уже есть sending/sent попытка. reject_withdrawal — отклонение одной
заявки с возвратом холда. Админский HTTP-слой — этап 11.6.
"""
from __future__ import annotations

import logging
import secrets

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
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
    PayoutAttempt,
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

# A6+A7: статусы immutable-попытки выплаты (payout_attempts) — durable outbox.
PAYOUT_ATTEMPT_SENDING = "sending"
PAYOUT_ATTEMPT_SENT = "sent"
PAYOUT_ATTEMPT_FAILED = "failed"
# Попытки, после которых повторная отправка перевода запрещена.
PAYOUT_ATTEMPT_ACTIVE_STATUSES = (PAYOUT_ATTEMPT_SENDING, PAYOUT_ATTEMPT_SENT)
# Предел длины текста ошибки попытки (обрезка перед записью в БД).
MAX_PAYOUT_ERROR_LENGTH = 2000

# Sprint 11.8 NanoROOT: 1 ROOT = 10^8 наноROOT.
NANO_PER_ROOT = 100_000_000


def _new_payout_query_id() -> str:
    """Уникальный uint64 query_id (строкой) для TON-перевода (A7).

    TON query_id — uint64; храним его строкой в PayoutAttempt.query_id
    (String(64)), чтобы не терять точность в SQLite. Значение 0 исключаем:
    раньше 0 был «нет id», теперь это признак отсутствия идемпотентности.
    """
    value = secrets.randbits(64)
    return str(value if value else 1)


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


def _serialize_created_withdrawal(withdrawal: WithdrawalRequest) -> dict:
    """Ответ создания заявки (в т.ч. idempotent-повтора), 11.5-a."""
    return {
        "withdrawalId": withdrawal.id,
        "amountRoot": withdrawal.amount_root,
        "amountRootNano": (
            withdrawal.amount_root_nano
            if withdrawal.amount_root_nano is not None
            else withdrawal.amount_root * NANO_PER_ROOT
        ),
        "toAddress": withdrawal.to_address,
        "status": withdrawal.status,
    }


def _find_withdrawal_by_request_id(
    session: Session,
    player_id: str,
    request_id: str,
) -> WithdrawalRequest | None:
    """Найти заявку игрока по клиентскому idempotency key (A10)."""
    return session.scalar(
        select(WithdrawalRequest).where(
            WithdrawalRequest.player_id == player_id,
            WithdrawalRequest.request_id == request_id,
        )
    )


def _create_withdrawal_request_impl(
    player_id: str,
    amount_root: int,
    to_address: str,
    request_id: str | None = None,
) -> dict:
    """Подать заявку на вывод ROOT в TON (этап 11.5-a; реализация).

    Возвращает {"withdrawalId", "amountRoot", "toAddress", "status"}.
    ROOT списывается сразу в холд; возврат при failed/rejected — отдельный
    механизм (11.5-b). Все проверки и проводки — в одной транзакции.

    A10: при переданном request_id повторный вызов с тем же
    (player_id, request_id) возвращает уже созданную заявку без второго
    списания (early-return ниже; гонку закрывает unique-индекс и обёртка
    create_withdrawal_request).
    """
    if request_id:
        with SessionLocal() as session:
            existing = _find_withdrawal_by_request_id(
                session, player_id, request_id
            )
        if existing is not None:
            return _serialize_created_withdrawal(existing)

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

        # A9: сначала блокируем ROOT-кошелёк (row-lock), чтобы параллельные
        # заявки ИГРОКА сериализовались; потом проверяем дневной лимит.
        # Иначе два параллельных вызова видели бы один и тот же daily_sum
        # и вместе превышали лимит.
        wallet = _get_root_wallet_for_update(session, player_id)

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

        # 6. Баланс.
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
        withdrawal = WithdrawalRequest(
            id=withdrawal_id,
            player_id=player_id,
            amount_root=amount_root,
            amount_root_nano=amount_root * NANO_PER_ROOT,
            to_address=canonical_address,
            status="pending",
            request_id=request_id,
        )
        session.add(withdrawal)

        session.flush()

        return _serialize_created_withdrawal(withdrawal)


def create_withdrawal_request(
    player_id: str,
    amount_root: int,
    to_address: str,
    request_id: str | None = None,
) -> dict:
    """Подать заявку на вывод ROOT в TON (11.5-a; A10 idempotency).

    request_id — клиентский idempotency key: повторный вызов с тем же
    (player_id, request_id) возвращает уже созданную заявку без второго
    списания. API передаёт ключ обязательно; None допустим только для
    внутренних вызовов (совместимость).

    Гонка двух параллельных запросов: unique-индекс
    uq_withdrawal_requests_player_request отклонит вторую вставку
    (IntegrityError), после чего возвращается уже созданная заявка.
    """
    try:
        return _create_withdrawal_request_impl(
            player_id, amount_root, to_address, request_id=request_id
        )
    except IntegrityError:
        if not request_id:
            raise
        with SessionLocal() as session:
            existing = _find_withdrawal_by_request_id(
                session, player_id, request_id
            )
        if existing is None:
            raise
        return _serialize_created_withdrawal(existing)


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


def _complete_payout_attempt(
    attempt_id: str, withdrawal_id: str, tx_hash: str
) -> None:
    """Зафиксировать успешную отправку: attempt='sent' + заявка 'confirmed'.

    Отдельная короткая транзакция (сеть уже отработала): attempt и заявка
    обновляются вместе, чтобы 'sent' и 'confirmed' не разъезжались.
    """
    with SessionLocal.begin() as session:
        attempt = session.scalar(
            select(PayoutAttempt)
            .where(PayoutAttempt.id == attempt_id)
            .with_for_update()
        )
        if attempt is not None and attempt.status == PAYOUT_ATTEMPT_SENDING:
            attempt.status = PAYOUT_ATTEMPT_SENT
            attempt.tx_hash = tx_hash
        withdrawal = session.scalar(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.id == withdrawal_id)
            .with_for_update()
        )
        if withdrawal is not None and withdrawal.status == "processing":
            withdrawal.status = "confirmed"
            withdrawal.ton_tx_hash = tx_hash
        session.flush()


def _fail_payout_attempt(
    attempt_id: str, withdrawal_id: str, error: BaseException
) -> None:
    """Зафиксировать провал: attempt='failed' + refund холда + 'failed'.

    Отдельная короткая транзакция: возврат холда (immutable credit-проводка)
    выполняется вместе с переводом заявки в 'failed'.
    """
    with SessionLocal.begin() as session:
        attempt = session.scalar(
            select(PayoutAttempt)
            .where(PayoutAttempt.id == attempt_id)
            .with_for_update()
        )
        if attempt is not None and attempt.status == PAYOUT_ATTEMPT_SENDING:
            attempt.status = PAYOUT_ATTEMPT_FAILED
            attempt.error = str(error)[:MAX_PAYOUT_ERROR_LENGTH]
        withdrawal = session.scalar(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.id == withdrawal_id)
            .with_for_update()
        )
        if withdrawal is not None and withdrawal.status == "processing":
            withdrawal.status = "failed"
            _refund_withdrawal_hold(session, withdrawal)
        session.flush()


def process_withdrawal_batch(
    admin_id: str, limit: int = WITHDRAWAL_BATCH_DEFAULT_LIMIT
) -> dict:
    """Батч-выплата pending-заявок (11.5-b; durable outbox A6+A7).

    Для каждой заявки: (1) отдельная транзакция создаёт immutable
    PayoutAttempt(status='sending', query_id=uint64) и переводит заявку в
    'processing' — коммит ДО сетевого вызова; (2) TON-перевод с
    query_id=attempt.query_id; (3) отдельная транзакция фиксирует результат
    (sent+tx_hash -> confirmed; либо failed + refund холда).

    Повторный batch не отправит выплату снова: заявка уже не 'pending', а
    partial unique index (withdrawal_id) WHERE status IN ('sending','sent')
    не даст создать вторую активную попытку даже при гонке двух запусков.

    Возвращает {"batchId", "confirmed", "failed"}.
    """
    batch_id = _new_id("batch")
    confirmed = 0
    failed = 0

    # 1. Только чтение: кандидаты pending без активного restriction.
    with SessionLocal() as session:
        restricted_player_ids = select(PlayerRestriction.player_id).where(
            PlayerRestriction.restriction_type == "withdrawal_restricted",
            PlayerRestriction.status == "active",
        )
        candidates = [
            (row.id, row.to_address)
            for row in session.scalars(
                select(WithdrawalRequest)
                .where(
                    WithdrawalRequest.status == "pending",
                    WithdrawalRequest.player_id.not_in(restricted_player_ids),
                )
                .order_by(WithdrawalRequest.created_at)
                .limit(limit)
            ).all()
        ]

    for withdrawal_id, to_address in candidates:
        attempt_id = _new_id("payout-attempt")
        query_id = _new_payout_query_id()
        amount_nano = 0

        # 2. Durable outbox: attempt='sending' + заявка 'processing' (commit).
        try:
            with SessionLocal.begin() as session:
                withdrawal = session.scalar(
                    select(WithdrawalRequest)
                    .where(WithdrawalRequest.id == withdrawal_id)
                    .with_for_update()
                )
                if withdrawal is None or withdrawal.status != "pending":
                    # Уже обработана другим batch/админом между выборкой и lock.
                    continue

                active_attempt = session.scalar(
                    select(PayoutAttempt.id).where(
                        PayoutAttempt.withdrawal_id == withdrawal_id,
                        PayoutAttempt.status.in_(PAYOUT_ATTEMPT_ACTIVE_STATUSES),
                    )
                )
                if active_attempt is not None:
                    logger.warning(
                        "Withdrawal %s already has an active payout attempt; "
                        "batch %s skips it",
                        withdrawal_id,
                        batch_id,
                    )
                    continue

                amount_nano = withdrawal.amount_root_nano
                if amount_nano is None:
                    # Fallback для legacy-заявок без _nano: вычислить из ROOT.
                    amount_nano = withdrawal.amount_root * NANO_PER_ROOT

                withdrawal.status = "processing"
                withdrawal.batch_id = batch_id
                withdrawal.admin_id = admin_id
                session.add(
                    PayoutAttempt(
                        id=attempt_id,
                        withdrawal_id=withdrawal_id,
                        status=PAYOUT_ATTEMPT_SENDING,
                        query_id=query_id,
                    )
                )
                session.flush()
        except IntegrityError:
            # Гонка: параллельный batch уже создал активную попытку.
            logger.warning(
                "Withdrawal %s payout attempt conflict; batch %s skips it",
                withdrawal_id,
                batch_id,
            )
            continue

        # 3. Сетевой вызов — вне транзакции БД (attempt уже durable).
        try:
            tx_hash = send_jetton_transfer_sync(
                to_address, amount_nano, query_id=int(query_id)
            )
        except Exception as error:  # noqa: BLE001 — сеть/пайлоад/конфиг
            _fail_payout_attempt(attempt_id, withdrawal_id, error)
            failed += 1
            logger.warning(
                "Withdrawal %s failed in batch %s: %s",
                withdrawal_id,
                batch_id,
                error,
            )
            continue

        # 4. Успех: attempt='sent' + заявка 'confirmed' (одна транзакция).
        _complete_payout_attempt(attempt_id, withdrawal_id, tx_hash)
        confirmed += 1

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