"""Подтверждение батча выплат по подписанному BOC (шаг 4).

Порядок проверок — от дешёвых к дорогим, чтобы не ходить в блокчейн зря:
  1. Батч существует и открыт (ready/submitted).
  2. BOC подписан ключом кошелька выплат (ed25519).
  3. Отправитель в BOC — именно ton.payout_wallet (не чужой кошелёк).
  4. Переводы в BOC совпадают с заявками батча по query_id, сумме и адресу.
  5. Каждый перевод подтверждается ОТДЕЛЬНО через блокчейн.

Почему по одной заявке, а не по хешу батча: TON может выполнить часть
переводов и отклонить остальные (bounce). Подтверждение «весь батч целиком по
одному хешу» записало бы в базу неоплаченные выплаты как оплаченные.

Инварианты:
  * заявка не может подтвердиться дважды (статус проверяется под блокировкой);
  * confirmed ставится только при реальном попадании в блокчейн;
  * неподтверждённые остаются processing — их судьбу решает шаг 5 (откат).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.mission_engine import MissionEngineError
from app.models import PayoutAttempt, PayoutBatch, WithdrawalRequest
from app.ton_connect_parser import (
    BocParseError,
    extract_sender_address,
    parse_jetton_transfers,
    same_address,
    verify_boc_signature,
)
from app.withdrawal_service import (
    NANO_PER_ROOT,
    PAYOUT_ATTEMPT_ACTIVE_STATUSES,
    PAYOUT_ATTEMPT_SENDING,
    PAYOUT_ATTEMPT_SENT,
    _utcnow,
)

logger = logging.getLogger(__name__)

BATCH_STATUS_SUBMITTED = "submitted"
BATCH_STATUS_CONFIRMED = "confirmed"


class BatchConfirmError(MissionEngineError):
    """Ошибка подтверждения с привязкой к HTTP-статусу."""


def _read_setting(session: Session, key: str) -> str:
    """Активная CMS-настройка -> строковое значение ('' если нет).

    Хранится в value_json (JSON-колонка) и только активная запись считается
    действующей — та же логика, что в ton_service._read_string_setting.
    """
    from app.models import SystemSetting

    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.status == "active",
        )
    )
    value = getattr(setting, "value_json", "")
    return value.strip() if isinstance(value, str) else ""


def _load_batch(session: Session, batch_id: str) -> PayoutBatch:
    batch = session.get(PayoutBatch, batch_id)
    if batch is None:
        raise BatchConfirmError(404, "Батч не найден.")
    if batch.status == BATCH_STATUS_CONFIRMED:
        raise BatchConfirmError(409, "Батч уже подтверждён.")
    if batch.status == "rolled_back":
        raise BatchConfirmError(409, "Батч откачен, подтверждение невозможно.")
    if batch.status not in ("ready", BATCH_STATUS_SUBMITTED):
        raise BatchConfirmError(
            409, f"Батч в статусе {batch.status}: подтверждение невозможно."
        )
    return batch


def _batch_items(session: Session, batch_id: str) -> list[tuple]:
    """Пары (заявка, АКТУАЛЬНАЯ попытка) по заявкам батча.

    У заявки может быть несколько попыток за историю (после отката прежняя
    становится 'failed', новый батч создаёт свежую 'sending'). Простой join
    на withdrawal_id вернул бы заявку дважды, и подтверждение увидело бы
    лишний query_id. Берём только активную попытку.
    """
    withdrawals = list(
        session.scalars(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.batch_id == batch_id)
            .order_by(WithdrawalRequest.created_at, WithdrawalRequest.id)
        ).all()
    )
    if not withdrawals:
        return []

    attempts = list(
        session.scalars(
            select(PayoutAttempt)
            .where(
                PayoutAttempt.withdrawal_id.in_([w.id for w in withdrawals]),
                PayoutAttempt.status.in_(PAYOUT_ATTEMPT_ACTIVE_STATUSES),
            )
            .order_by(PayoutAttempt.created_at.desc())
        ).all()
    )
    by_withdrawal: dict[str, PayoutAttempt] = {}
    for attempt in attempts:
        by_withdrawal.setdefault(attempt.withdrawal_id, attempt)

    return [(w, by_withdrawal.get(w.id)) for w in withdrawals]


def _verify_local_checks(
    session: Session,
    batch_id: str,
    boc_base64: str,
) -> list[dict[str, Any]]:
    """Проверки 2-4 без обращения к блокчейну.

    Возвращает подтверждённые локально переводы, уже привязанные к заявкам.
    Любое расхождение — отказ целиком: если BOC не соответствует батчу,
    непонятно, что вообще произошло.
    """
    public_key_setting = _read_setting(session, "ton.payout_wallet_public_key")
    payout_wallet = _read_setting(session, "ton.payout_wallet")

    if not public_key_setting:
        raise BatchConfirmError(
            503,
            "Не настроен публичный ключ кошелька выплат "
            "(ton.payout_wallet_public_key).",
        )
    if not payout_wallet:
        raise BatchConfirmError(
            503, "Не настроен кошелёк выплат (ton.payout_wallet)."
        )

    try:
        public_key = bytes.fromhex(public_key_setting.removeprefix("0x"))
    except ValueError as error:
        raise BatchConfirmError(
            503, "Публичный ключ кошелька выплат не является hex-строкой."
        ) from error

    # 2. Подпись.
    try:
        verify_boc_signature(boc_base64, public_key)
    except BocParseError as error:
        raise BatchConfirmError(422, f"Подпись BOC не подтверждена: {error}") from error

    # 3. Отправитель — наш кошелёк выплат.
    try:
        sender = extract_sender_address(boc_base64)
    except BocParseError as error:
        raise BatchConfirmError(
            422, f"Не удалось определить отправителя BOC: {error}"
        ) from error
    if not same_address(sender, payout_wallet):
        raise BatchConfirmError(
            403,
            "BOC подписан другим кошельком. Ожидался кошелёк выплат, "
            f"получен {sender}.",
        )

    # 4. Переводы против заявок батча.
    try:
        transfers = parse_jetton_transfers(boc_base64)
    except BocParseError as error:
        raise BatchConfirmError(422, f"BOC не разобран: {error}") from error

    items = _batch_items(session, batch_id)
    if not items:
        raise BatchConfirmError(409, "В батче нет заявок.")

    by_query: dict[str, tuple[WithdrawalRequest, PayoutAttempt]] = {}
    for withdrawal, attempt in items:
        if attempt is None or not attempt.query_id:
            raise BatchConfirmError(
                500,
                f"У заявки {withdrawal.id} нет query_id — батч сформирован "
                "некорректно.",
            )
        by_query[attempt.query_id] = (withdrawal, attempt)

    # Переводы в BOC обязаны соответствовать заявкам: иначе админ мог
    # подписать не тот список (например, старый батч).
    seen: set[str] = set()
    matched: list[dict[str, Any]] = []
    for transfer in transfers:
        query_id = transfer["queryId"]
        if query_id in seen:
            raise BatchConfirmError(
                422, f"query_id {query_id} встречается в BOC дважды."
            )
        seen.add(query_id)

        pair = by_query.get(query_id)
        if pair is None:
            raise BatchConfirmError(
                422,
                f"В BOC есть перевод с query_id {query_id}, "
                "которого нет в этом батче.",
            )
        withdrawal, attempt = pair

        expected_nano = withdrawal.amount_root_nano or (
            withdrawal.amount_root * NANO_PER_ROOT
        )
        if transfer["amountNano"] != expected_nano:
            raise BatchConfirmError(
                422,
                f"Сумма по заявке {withdrawal.id} не совпадает: в BOC "
                f"{transfer['amountNano']}, ожидалось {expected_nano}.",
            )
        if not same_address(transfer["recipient"], withdrawal.to_address):
            raise BatchConfirmError(
                422,
                f"Получатель по заявке {withdrawal.id} не совпадает с адресом "
                "заявки.",
            )

        matched.append(
            {
                "withdrawalId": withdrawal.id,
                "queryId": query_id,
                "amountNano": transfer["amountNano"],
            }
        )

    # Заявки батча, которых нет в BOC: батч оплачен частично. Это не ошибка
    # формата — просто эти заявки останутся processing до отката.
    missing = set(by_query) - seen
    if missing:
        logger.warning(
            "Batch %s: %d заявок отсутствуют в подписанном BOC: %s",
            batch_id,
            len(missing),
            sorted(missing),
        )

    return matched


def confirm_payout_batch(
    batch_id: str,
    boc_base64: str,
    admin_id: str | None = None,
    blockchain_lookup: Callable[[str, int], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    """Подтвердить батч по подписанному BOC.

    blockchain_lookup(query_id, amount_nano) -> {"txHash": str} | None —
    проверка факта перевода в блокчейне. Вынесена параметром, чтобы тесты
    не ходили в сеть, а прод подставлял реальный поиск по TonCenter.

    Возвращает:
      {batchId, status, confirmedCount, pendingCount, items: [...]}

    status: 'confirmed' — подтверждены все заявки; 'submitted' — часть ещё
    не видна в блокчейне (или блокчейн не подтвердил), они остались processing.
    """
    if blockchain_lookup is None:
        raise BatchConfirmError(
            503, "Проверка блокчейна не подключена (blockchain_lookup)."
        )

    with SessionLocal() as session:
        _load_batch(session, batch_id)
        matched = _verify_local_checks(session, batch_id, boc_base64)
        items = _batch_items(session, batch_id)
        total_items = len(items)

    # 5. По одной заявке: подтверждаем только то, что реально в блокчейне.
    confirmed: list[dict[str, Any]] = []
    still_pending: list[dict[str, Any]] = []

    for entry in matched:
        withdrawal_id = entry["withdrawalId"]
        query_id = entry["queryId"]
        amount_nano = entry["amountNano"]

        try:
            found = blockchain_lookup(query_id, amount_nano)
        except Exception as error:  # noqa: BLE001 — сеть/API
            logger.warning(
                "Blockchain lookup failed for query_id %s: %s", query_id, error
            )
            still_pending.append(
                {
                    "withdrawalId": withdrawal_id,
                    "queryId": query_id,
                    "reason": "blockchain_unavailable",
                }
            )
            continue

        if found is None:
            still_pending.append(
                {
                    "withdrawalId": withdrawal_id,
                    "queryId": query_id,
                    "reason": "not_found_in_blockchain",
                }
            )
            continue

        tx_hash = str(found.get("txHash") or "")
        if not tx_hash:
            still_pending.append(
                {
                    "withdrawalId": withdrawal_id,
                    "queryId": query_id,
                    "reason": "no_tx_hash",
                }
            )
            continue

        try:
            _confirm_one(withdrawal_id, query_id, tx_hash)
        except IntegrityError:
            logger.warning(
                "Withdrawal %s already confirmed by another worker", withdrawal_id
            )
            continue
        confirmed.append(
            {
                "withdrawalId": withdrawal_id,
                "queryId": query_id,
                "txHash": tx_hash,
            }
        )

    with SessionLocal.begin() as session:
        batch = session.scalar(
            select(PayoutBatch)
            .where(PayoutBatch.id == batch_id)
            .with_for_update()
        )
        if batch is None:  # pragma: no cover
            raise BatchConfirmError(404, "Батч исчез во время подтверждения.")

        remaining = session.scalar(
            select(WithdrawalRequest.id)
            .where(
                WithdrawalRequest.batch_id == batch_id,
                WithdrawalRequest.status == "processing",
            )
            .limit(1)
        )
        all_confirmed = remaining is None

        if all_confirmed:
            batch.status = BATCH_STATUS_CONFIRMED
            batch.terminal_at = _utcnow()
            if confirmed:
                batch.tx_hash = confirmed[0]["txHash"]
        else:
            batch.status = BATCH_STATUS_SUBMITTED
            if confirmed and not batch.tx_hash:
                batch.tx_hash = confirmed[0]["txHash"]
        session.flush()

        status = batch.status

    logger.info(
        "Batch %s confirm: %d confirmed, %d pending, status=%s",
        batch_id,
        len(confirmed),
        len(still_pending),
        status,
    )

    return {
        "batchId": batch_id,
        "status": status,
        "confirmedCount": len(confirmed),
        # Всё, что не подтверждено: и переданные в BOC, но не найденные в
        # блокчейне, и вообще не попавшие в BOC.
        "pendingCount": total_items - len(confirmed),
        "totalCount": total_items,
        "confirmed": confirmed,
        "pending": still_pending,
    }


def _confirm_one(withdrawal_id: str, query_id: str, tx_hash: str) -> None:
    """Подтвердить одну заявку: attempt='sent' + заявка 'confirmed'.

    Отдельная короткая транзакция на заявку: если сеть/БД откажет на пятой
    заявке, первые четыре останутся подтверждёнными, а не откатятся все.
    """
    with SessionLocal.begin() as session:
        withdrawal = session.scalar(
            select(WithdrawalRequest)
            .where(WithdrawalRequest.id == withdrawal_id)
            .with_for_update()
        )
        if withdrawal is None:
            return
        if withdrawal.status != "processing":
            return
        attempt = session.scalar(
            select(PayoutAttempt)
            .where(
                PayoutAttempt.withdrawal_id == withdrawal_id,
                PayoutAttempt.query_id == query_id,
            )
            .with_for_update()
        )
        if attempt is None:
            raise BatchConfirmError(
                500, f"Для заявки {withdrawal_id} нет попытки с query_id."
            )
        if attempt.status == PAYOUT_ATTEMPT_SENDING:
            attempt.status = PAYOUT_ATTEMPT_SENT
            attempt.tx_hash = tx_hash
        withdrawal.status = "confirmed"
        withdrawal.ton_tx_hash = tx_hash
        session.flush()
