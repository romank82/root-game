"""Раздел «Риск»: контейнер, разблокировка газом (docs/risk-section-contract.md).

Реализует ТОЛЬКО инфраструктуру раздела:
  - разрешение состояния для игрока (hidden / locked / unlocked);
  - атомарную разовую оплату газом с постоянным доступом;
  - чтение админ-настроек risk.access_mode / risk.unlock_gas_cost.

Сами мини-игры в этот модуль не входят и здесь не реализуются.

Газ списывается immutable-проводкой GasTransaction (reference_type=
'risk_unlock'), как комиссия за перевод в transfer_service. ROOT не
затрагивается.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin_player_wallet import ACTIVE_SETTING_STATUS
from app.models import GasTransaction, GasWallet, RiskAccessGrant, SystemSetting
from app.system_settings_catalog import get_definition


ACCESS_MODE_KEY = "risk.access_mode"
UNLOCK_GAS_COST_KEY = "risk.unlock_gas_cost"

ACCESS_MODE_HIDDEN = "hidden"
ACCESS_MODE_LOCKED = "locked"
ACCESS_MODE_OPEN = "open"
VALID_ACCESS_MODES = (ACCESS_MODE_HIDDEN, ACCESS_MODE_LOCKED, ACCESS_MODE_OPEN)

DEFAULT_ACCESS_MODE = ACCESS_MODE_HIDDEN
DEFAULT_UNLOCK_GAS_COST = 100

# reference_type газовой проводки за разблокировку раздела.
RISK_UNLOCK_GAS_REFERENCE_TYPE = "risk_unlock"

STATE_HIDDEN = "hidden"
STATE_LOCKED = "locked"
STATE_UNLOCKED = "unlocked"


class RiskError(Exception):
    """Ошибка домена раздела «Риск» с HTTP-статусом."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _read_setting(session: Session, key: str, fallback):
    """Активная SystemSetting -> default каталога -> fallback.

    Паттерн _read_int_setting из transfer_service: значение берём только у
    активной записи, иначе — default каталога, иначе — fallback.
    """
    setting = session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.status == ACTIVE_SETTING_STATUS,
        )
    )
    if setting is not None and getattr(setting, "status", None) == ACTIVE_SETTING_STATUS:
        return setting.value_json
    definition = get_definition(key)
    if definition is not None:
        return definition.default_value
    return fallback


def read_access_mode(session: Session) -> str:
    """Режим доступа из CMS; неизвестное значение трактуется как hidden."""
    raw = _read_setting(session, ACCESS_MODE_KEY, DEFAULT_ACCESS_MODE)
    if isinstance(raw, str) and raw in VALID_ACCESS_MODES:
        return raw
    return DEFAULT_ACCESS_MODE


def read_unlock_gas_cost(session: Session) -> Decimal:
    """Стоимость разблокировки в газе. Неотрицательная, дробная как gas."""
    raw = _read_setting(session, UNLOCK_GAS_COST_KEY, DEFAULT_UNLOCK_GAS_COST)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return Decimal(DEFAULT_UNLOCK_GAS_COST)
    value = Decimal(str(raw))
    if value < 0:
        return Decimal(DEFAULT_UNLOCK_GAS_COST)
    return value


def _get_grant(session: Session, player_id: str) -> RiskAccessGrant | None:
    return session.scalar(
        select(RiskAccessGrant).where(RiskAccessGrant.player_id == player_id)
    )


def _get_gas_balance(session: Session, player_id: str) -> Decimal:
    wallet = session.scalar(
        select(GasWallet).where(GasWallet.player_id == player_id)
    )
    return wallet.balance if wallet is not None else Decimal("0")


def resolve_state(session: Session, player_id: str) -> dict:
    """Состояние раздела для игрока.

    hidden перекрывает выданный грант: пока админ скрыл раздел, игрок его не
    видит, и оплата не предлагается. Грант при этом не отзывается.
    """
    mode = read_access_mode(session)
    cost = read_unlock_gas_cost(session)
    balance = _get_gas_balance(session, player_id)
    grant = _get_grant(session, player_id)

    if mode == ACCESS_MODE_HIDDEN:
        state = STATE_HIDDEN
    elif mode == ACCESS_MODE_OPEN or grant is not None:
        state = STATE_UNLOCKED
    else:
        state = STATE_LOCKED

    return {
        "state": state,
        "unlocked": state == STATE_UNLOCKED,
        "gasCost": str(cost),
        "gasBalance": str(balance),
        "mode": mode,
    }


def unlock_with_gas(session: Session, player_id: str) -> dict:
    """Разовая оплата газом: постоянный доступ к разделу «Риск».

    Одна транзакция: списание газа + создание гранта. Идемпотентно — повторный
    вызов после успеха не двигает газ и возвращает unlocked.
    """
    mode = read_access_mode(session)
    if mode == ACCESS_MODE_HIDDEN:
        raise RiskError(403, "Раздел «Риск» сейчас скрыт администратором.")

    existing = _get_grant(session, player_id)
    if existing is not None:
        # Уже оплачено: повторная оплата невозможна.
        return resolve_state(session, player_id)

    if mode == ACCESS_MODE_OPEN:
        # Оплата не требуется; клиент должен обновить состояние.
        raise RiskError(
            409,
            "Доступ к разделу открыт без оплаты — обновите состояние.",
        )

    cost = read_unlock_gas_cost(session)
    if cost <= 0:
        raise RiskError(
            409,
            "Стоимость разблокировки не задана — обновите состояние.",
        )

    gas_wallet = session.scalar(
        select(GasWallet)
        .where(GasWallet.player_id == player_id)
        .with_for_update()
    )
    if gas_wallet is None or gas_wallet.balance < cost:
        raise RiskError(
            402,
            f"Недостаточно газа. Нужно {cost} газа для разблокировки.",
        )

    grant_id = _new_id("risk-grant")

    gas_wallet.balance -= cost
    session.add(
        GasTransaction(
            id=_new_id("gas-transaction"),
            gas_wallet_id=gas_wallet.id,
            amount=cost,
            balance_after=gas_wallet.balance,
            transaction_type="debit",
            reason=f"Risk section unlock {player_id}",
            reference_type=RISK_UNLOCK_GAS_REFERENCE_TYPE,
            reference_id=grant_id,
            metadata_json={
                "playerId": player_id,
                "gasCost": str(cost),
            },
        )
    )
    session.add(
        RiskAccessGrant(
            id=grant_id,
            player_id=player_id,
            gas_cost_paid=cost,
            granted_at=_utcnow(),
        )
    )
    session.flush()

    return resolve_state(session, player_id)