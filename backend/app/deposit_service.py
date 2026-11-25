"""Сервис депозита ROOT-jetton (Sprint 1.5): зачисление входящих переводов.

Ядро зачисления (поллер — отдельно, Sprint 1.6). Вход — распарсенный
incoming-перевод из ton_service.parse_jetton_transfer: dict
{tx_hash, lt, query_id, from_address (owner), to_address (сейф),
 jetton_master, amount_nano, raw_payload}.

Поток process_incoming_transfer:
  1. идемпотентность: JettonDeposit по tx_hash (unique) -> вернуть existing
     (первой, чтобы ни одна rejected-ветка не упёрлась в unique tx_hash);
  2. ton.deposit_enabled=False -> rejected (reason=disabled);
  3. amount_nano < ton.min_deposit_root * 10^8 -> rejected (reason=below_minimum);
  4. jetton_master != settings.ton_root_jetton_master -> rejected (wrong_jetton);
  5. адрес получателя != активный ton.deposit_wallet ->
     rejected (wrong_destination); кошелёк не настроен ->
     rejected (deposit_wallet_not_configured);
  6. сопоставление: TonWallet по from_address (active) -> player_id; нет -> pending;
  7. row-lock кошелька (_get_root_wallet_for_update);
  8. вторая линия идемпотентности: WalletTransaction unique
     (wallet_id, reference_type='jetton_deposit', reference_id=tx_hash);
  9. зачисление nano + ledger-credit + JettonDeposit(confirmed).

Физическое удаление записей запрещено: JettonDeposit append-only,
WalletTransaction immutable. Стиль — transfer_service/withdrawal_service.
"""

from __future__ import annotations

import logging

from pytoniq_core import Address
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_player_wallet import ACTIVE_SETTING_STATUS
from app.config import settings
from app.mission_engine import (
    MissionEngineError,
    _get_root_wallet_for_update,
    _new_id,
    _utcnow,
)
from app.models import (
    JettonDeposit,
    SystemSetting,
    TonWallet,
    Wallet,
    WalletTransaction,
)

logger = logging.getLogger(__name__)

# Ключи CMS (system_settings_catalog.py, категория ton).
DEPOSIT_ENABLED_KEY = "ton.deposit_enabled"
DEPOSIT_WALLET_KEY = "ton.deposit_wallet"
DEPOSIT_MIN_AMOUNT_KEY = "ton.min_deposit_root"

# Reference type immutable-проводки зачисления депозита.
DEPOSIT_REFERENCE_TYPE = "jetton_deposit"

# Sprint 11.8 NanoROOT: 1 ROOT = 10^8 наноROOT.
NANO_PER_ROOT = 100_000_000


def _read_bool_setting(session: Session, key: str, fallback: bool) -> bool:
    """Активная SystemSetting (bool) -> default каталога -> fallback."""
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
    from app.system_settings_catalog import get_definition

    definition = get_definition(key)
    if definition is not None and isinstance(definition.default_value, bool):
        return definition.default_value
    return fallback


def _read_int_setting(session: Session, key: str, fallback: int) -> int:
    """Активная SystemSetting (int >= 0) -> default каталога -> fallback."""
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
    from app.system_settings_catalog import get_definition

    definition = get_definition(key)
    if definition is not None and isinstance(definition.default_value, int):
        return definition.default_value
    return fallback


def _read_string_setting(session: Session, key: str) -> str:
    """Активная SystemSetting (str) -> строковое значение ('' если нет)."""
    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.status == ACTIVE_SETTING_STATUS,
        )
    )
    value = getattr(setting, "value_json", "")
    return value if isinstance(value, str) else ""


def get_deposit_wallet_address(session: Session) -> str:
    """Адрес «спец» кошелька приёма ROOT-jetton из CMS (ton.deposit_wallet).

    Пусто/без активной записи — MissionEngineError(503): депозит не настроен.
    """
    address = _read_string_setting(session, DEPOSIT_WALLET_KEY).strip()
    if not address:
        raise MissionEngineError(
            503, "Депозит ROOT-jetton не настроен (deposit wallet)."
        )
    return address


def normalize_address_for_compare(address):
    """Канонический raw-вид TON-адреса для сравнения (None — невалиден).

    TonCenter отдаёт `destination` в raw-форме (`0:hex`), а CMS хранит
    user-friendly (`EQA…`/`kQA…`), поэтому сравнивать строки нельзя —
    только нормализованные raw-адреса.
    """
    if not isinstance(address, str) or not address.strip():
        return None
    try:
        return Address(address.strip()).to_str(is_user_friendly=False)
    except Exception:
        return None


def _build_deposit(
    tx: dict,
    player_id: str | None,
    status: str,
    reason: str | None = None,
    confirmed_at=None,
) -> JettonDeposit:
    """Собрать JettonDeposit из распарсенного перевода.

    Поля модели NOT NULL (lt, from/to_address, jetton_master, amount_nano)
    обязаны присутствовать в tx — иначе ValueError. reason нет в модели:
    пишем в raw_payload.
    """
    required = (
        "tx_hash",
        "lt",
        "from_address",
        "to_address",
        "jetton_master",
        "amount_nano",
    )
    missing = [f for f in required if f not in tx or tx[f] is None]
    if missing:
        raise ValueError(f"Некорректный перевод: отсутствуют поля {missing}.")

    raw_payload = dict(tx.get("raw_payload") or {})
    if reason is not None:
        raw_payload["reason"] = reason

    return JettonDeposit(
        id=_new_id("jetton-deposit"),
        tx_hash=tx["tx_hash"],
        lt=tx["lt"],
        query_id=tx.get("query_id"),
        from_address=tx["from_address"],
        to_address=tx["to_address"],
        jetton_master=tx["jetton_master"],
        amount_nano=tx["amount_nano"],
        player_id=player_id,
        status=status,
        raw_payload=raw_payload,
        confirmed_at=confirmed_at,
    )


def process_incoming_transfer(session: Session, tx: dict) -> JettonDeposit:
    """Зачислить входящий ROOT-jetton перевод (ядро, Sprint 1.5).

    Транзакцию открывает вызывающий (поллер — SessionLocal.begin()).
    Здесь — проверки, row-lock, ledger-credit и flush; commit — снаружи.

    Возвращает JettonDeposit (confirmed / pending / rejected / существующий).
    Идемпотентность двухуровневая: unique tx_hash (модель) + unique
    (wallet_id, reference_type, reference_id=tx_hash) (ledger).
    """
    # 1. Идемпотентность по tx_hash (unique) — самая первая проверка.
    # Порядок принципиален: любая ветка rejected ниже вставляет строку
    # JettonDeposit, а tx_hash уникален. Если повторно обработать тот же
    # перевод при изменившихся настройках (например, после смены
    # ton.deposit_wallet), проверка адреса дала бы rejected и вторая вставка
    # упала бы с IntegrityError. Ранее записанная строка — единственный
    # правильный ответ на повтор.
    existing = session.scalar(
        select(JettonDeposit).where(JettonDeposit.tx_hash == tx["tx_hash"])
    )
    if existing is not None:
        return existing

    # 2. Рубильник депозита (CMS ton.deposit_enabled).
    if not _read_bool_setting(session, DEPOSIT_ENABLED_KEY, False):
        deposit = _build_deposit(tx, None, "rejected", reason="disabled")
        session.add(deposit)
        session.flush()
        return deposit

    # 3. Минимальная сумма (ton.min_deposit_root, целый ROOT).
    min_root = _read_int_setting(session, DEPOSIT_MIN_AMOUNT_KEY, 1)
    if tx.get("amount_nano", 0) < min_root * NANO_PER_ROOT:
        deposit = _build_deposit(tx, None, "rejected", reason="below_minimum")
        session.add(deposit)
        session.flush()
        return deposit

    # 4. Проверка jetton-мастера == TON_ROOT_JETTON_MASTER.
    expected_master = settings.ton_root_jetton_master
    if not expected_master or tx.get("jetton_master") != expected_master:
        deposit = _build_deposit(tx, None, "rejected", reason="wrong_jetton")
        session.add(deposit)
        session.flush()
        return deposit

    # 5. Адрес получателя == активный депозитный кошелёк из CMS.
    # Poller запрашивает историю только своего адреса, но проверка должна
    # жить в самом сервисе: вызывающий может передать любой tx-dict.
    expected_destination = _read_string_setting(session, DEPOSIT_WALLET_KEY).strip()
    if not expected_destination:
        deposit = _build_deposit(
            tx, None, "rejected", reason="deposit_wallet_not_configured"
        )
        session.add(deposit)
        session.flush()
        return deposit
    expected_raw = normalize_address_for_compare(expected_destination)
    actual_raw = normalize_address_for_compare(tx.get("to_address"))
    if expected_raw is None or actual_raw is None or expected_raw != actual_raw:
        deposit = _build_deposit(tx, None, "rejected", reason="wrong_destination")
        session.add(deposit)
        session.flush()
        return deposit

    # 6. Сопоставление отправителя с активным TonWallet игрока.
    ton_wallet = session.scalar(
        select(TonWallet).where(
            TonWallet.address == tx["from_address"],
            TonWallet.status == "active",
        )
    )
    if ton_wallet is None:
        deposit = _build_deposit(tx, None, "pending")
        session.add(deposit)
        session.flush()
        return deposit

    player_id = ton_wallet.player_id

    # 7. Row-lock ROOT-кошелька игрока (сериализация параллельных депозитов).
    wallet = _get_root_wallet_for_update(session, player_id)

    # 8. Вторая линия идемпотентности: ledger-проводка с этим reference_id.
    ledger_credit = session.scalar(
        select(WalletTransaction).where(
            WalletTransaction.wallet_id == wallet.id,
            WalletTransaction.reference_type == DEPOSIT_REFERENCE_TYPE,
            WalletTransaction.reference_id == tx["tx_hash"],
        )
    )
    if ledger_credit is not None:
        confirmed = session.scalar(
            select(JettonDeposit).where(JettonDeposit.tx_hash == tx["tx_hash"])
        )
        return confirmed if confirmed is not None else existing

    # 9. Зачисление по nano (legacy available_balance = floor(nano / 10^8)).
    wallet_nano = wallet.available_balance_nano
    if wallet_nano is None:
        wallet_nano = wallet.available_balance * NANO_PER_ROOT
    wallet_nano += tx["amount_nano"]
    wallet.available_balance_nano = wallet_nano
    wallet.available_balance = wallet_nano // NANO_PER_ROOT

    # 9. Immutable ledger-credit.
    session.add(
        WalletTransaction(
            id=_new_id("wallet-transaction"),
            wallet_id=wallet.id,
            amount=tx["amount_nano"] // NANO_PER_ROOT,
            amount_nano=tx["amount_nano"],
            balance_after=wallet.available_balance,
            balance_after_nano=wallet.available_balance_nano,
            transaction_type="credit",
            reason=f"Jetton deposit {tx['tx_hash']}",
            reference_type=DEPOSIT_REFERENCE_TYPE,
            reference_id=tx["tx_hash"],
            metadata_json={
                "fromAddress": tx["from_address"],
                "toAddress": tx["to_address"],
                "jettonMaster": tx["jetton_master"],
            },
        )
    )

    # 10. JettonDeposit(confirmed).
    deposit = _build_deposit(
        tx, player_id, "confirmed", confirmed_at=_utcnow()
    )
    session.add(deposit)
    session.flush()

    return deposit


