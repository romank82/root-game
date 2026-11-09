"""Реферальная программа: привязка приглашённого и награда (Sprint Referral R-4).

Модуль содержит только механизм — ни HTTP, ни UI, ни регистрации:

- ``assign_referrer`` — по ``start_param`` вида ``ref_<player_id>`` привязать
  приглашённого к пригласившему и создать ``ReferralReward`` в статусе
  ``pending`` (награда ещё не начислена);
- ``check_and_reward`` — когда приглашённый достиг порога earned ROOT,
  начислить пригласившему ``referral.reward_root`` ровно одной immutable-
  проводкой ``WalletTransaction``.

CMS-first: включённость программы (``referral.enabled``), размер награды
(``referral.reward_root``) и порог
(``economy.transfer_minimum_earned_root``) живут в system_settings; в коде —
только чтение и механизм. Секретов не читаем, только числовые/булевы
параметры.

«Earned ROOT» считается так же, как в ``transfer_service.transfer_root``:
сумма credit-проводок с ``reference_type='mission_reward'`` (подтверждённые
игровые награды; переводы, магазин и админ-корректировки в зачёт не идут).

Идемпотентность:
- одна запись ``ReferralReward`` на приглашённого —
  ``uq_referral_rewards_referred`` + быстрый признак
  ``GamePlayer.referred_by_player_id``;
- ledger — unique ``(wallet_id, reference_type, reference_id)``, где
  ``reference_id = ReferralReward.id``, поэтому повторная проводка невозможна
  даже при гонке; статус ``credited`` дополнительно исключает повторное
  начисление на уровне домена.

Транзакцию открывает вызывающий: ``session`` передаётся снаружи, ``commit``
делает он же (R-5 — регистрация в ``_upsert_telegram_player``, R-6 — награда
миссии в ``_award_mission_rewards``).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.mission_engine import (
    ROOT_CURRENCY,
    _get_root_wallet_for_update,
    _new_id,
)
from app.models import (
    GamePlayer,
    ReferralReward,
    SystemSetting,
    Wallet,
    WalletTransaction,
)
from app.system_settings_catalog import get_definition

# Ключи CMS (system_settings_catalog.py, категории referral/economy/telegram).
REFERRAL_ENABLED_KEY = "referral.enabled"
REFERRAL_REWARD_ROOT_KEY = "referral.reward_root"
EARNED_THRESHOLD_KEY = "economy.transfer_minimum_earned_root"

# Sprint 11.8 NanoROOT: 1 ROOT = 10^8 наноROOT.
NANO_PER_ROOT = 100_000_000
# Sprint 8.x-ref-link-cms: имя бота (CMS-first, фолбэк на env).
TELEGRAM_BOT_USERNAME_KEY = "telegram.bot_username"

# Префикс реферального start_param: "ref_<player_id>" (Referral-3 читает
# start_param из подписанного initData, формат валидируется здесь).
REF_PREFIX = "ref_"

# Reference-тип проводки награды. Уникальный индекс ledger
# (wallet_id, reference_type, reference_id) делает начисление идемпотентным
# через reference_id = ReferralReward.id.
REFERRAL_REFERENCE_TYPE = "referral_reward"
# В mission_engine "mission_reward" — инлайн-строка; зеркало здесь (как в
# transfer_service.MISSION_REWARD_REFERENCE_TYPE): эти кредиты дают earned.
MISSION_REWARD_REFERENCE_TYPE = "mission_reward"

# Зеркало admin_player_wallet.ACTIVE_SETTING_STATUS: импортировать админ-модуль
# в игровой путь (запрос миссии) не хотим — тянет FastAPI-роутеры и approvals.
ACTIVE_SETTING_STATUS = "active"

# Фолбэки, если ключа нет ни в БД, ни в каталоге (каталог — источник истины).
DEFAULT_REFERRAL_REWARD_ROOT = 25
DEFAULT_EARNED_THRESHOLD = 50


def _read_setting(session: Session, key: str) -> SystemSetting | None:
    """Активная SystemSetting-запись по ключу (или None)."""
    return session.scalar(
        select(SystemSetting).where(
            SystemSetting.key == key,
            SystemSetting.status == ACTIVE_SETTING_STATUS,
        )
    )


def _read_int_setting(session: Session, key: str, fallback: int) -> int:
    """Активная SystemSetting-запись -> default каталога -> fallback.

    Локальная копия паттерна ``transfer_service._read_int_setting``
    (согласовано в R-4: общий helper не выносим, чтобы не трогать два
    существующих модуля). ``bool`` исключается явно: в Python bool —
    подкласс int, а JSON-``true`` не должен превращаться в 1 ROOT.
    """
    setting = _read_setting(session, key)
    if (
        setting is not None
        and isinstance(setting.value_json, int)
        and not isinstance(setting.value_json, bool)
        and setting.value_json >= 0
    ):
        return setting.value_json

    definition = get_definition(key)
    if (
        definition is not None
        and isinstance(definition.default_value, int)
        and not isinstance(definition.default_value, bool)
    ):
        return definition.default_value

    return fallback


def _read_bool_setting(session: Session, key: str, fallback: bool = False) -> bool:
    """Активная SystemSetting-запись (boolean) -> default каталога -> fallback."""
    setting = _read_setting(session, key)
    if setting is not None and isinstance(setting.value_json, bool):
        return setting.value_json

    definition = get_definition(key)
    if definition is not None and isinstance(definition.default_value, bool):
        return definition.default_value

    return fallback


def _read_string_setting(session: Session, key: str, fallback: str = "") -> str:
    """Активная SystemSetting-запись (string) -> default каталога -> fallback.

    Порядок тот же, что у ``_read_int_setting``: сперва активная запись из БД,
    затем default_value из код-каталога, в конце явный fallback. Если тип в БД
    не совпадает с ожидаемым («string») — значение не доверяем и идём дальше
    (несовместимая запись не должна протекать в ссылку).
    """
    setting = _read_setting(session, key)
    if setting is not None and setting.value_type == "string":
        value = setting.value_json
        if isinstance(value, str):
            return value

    definition = get_definition(key)
    if definition is not None and definition.value_type == "string":
        default = definition.default_value
        if isinstance(default, str):
            return default

    return fallback


def _earned_root(session: Session, player_id: str) -> int:
    """Заработанный ROOT: сумма credit-проводок типа mission_reward.

    Полное зеркало условия ``transfer_service.transfer_root`` (шаг 4), поэтому
    «порог для переводов» и «порог для реферальной награды» — одно и то же
    событие для игрока.
    """
    wallet_id = session.scalar(
        select(Wallet.id).where(
            Wallet.player_id == player_id,
            Wallet.currency == ROOT_CURRENCY,
        )
    )
    if wallet_id is None:
        return 0

    return session.scalar(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            WalletTransaction.wallet_id == wallet_id,
            WalletTransaction.transaction_type == "credit",
            WalletTransaction.reference_type == MISSION_REWARD_REFERENCE_TYPE,
        )
    ) or 0


def assign_referrer(
    session: Session,
    referred_player_id: str,
    ref_param: str | None,
) -> ReferralReward | None:
    """Привязать приглашённого к пригласившему по start_param.

    Возвращает созданный ``ReferralReward`` (status="pending") либо None, если
    привязка не требуется или невозможна:
    - параметра нет / он не начинается с ``ref_`` / id пустой;
    - попытка пригласить самого себя;
    - игрок не найден;
    - у игрока уже есть реферер (повторный вход по чужой ссылке);
    - реферер не найден или не active;
    - запись ReferralReward уже существует (idempotent, unique);
    - размер награды из CMS <= 0 (CHECK amount_root > 0 не позволил бы
      записать такую строку).

    Никаких исключений наружу: привязка — побочный эффект регистрации и не
    должна ломать вход игрока.
    """
    if not ref_param:
        return None

    normalized = ref_param.strip()
    if not normalized.startswith(REF_PREFIX):
        return None

    referrer_id = normalized[len(REF_PREFIX):].strip()
    if not referrer_id or referrer_id == referred_player_id:
        return None

    referred = session.get(GamePlayer, referred_player_id)
    if referred is None:
        return None
    if referred.referred_by_player_id is not None:
        return None

    referrer = session.get(GamePlayer, referrer_id)
    if referrer is None or referrer.status != "active":
        return None

    existing = session.scalar(
        select(ReferralReward).where(
            ReferralReward.referred_player_id == referred_player_id
        )
    )
    if existing is not None:
        return None

    amount = _read_int_setting(
        session, REFERRAL_REWARD_ROOT_KEY, DEFAULT_REFERRAL_REWARD_ROOT
    )
    if amount <= 0:
        return None

    reward = ReferralReward(
        id=_new_id("referral-reward"),
        referrer_player_id=referrer_id,
        referred_player_id=referred_player_id,
        amount_root=amount,
        amount_root_nano=amount * NANO_PER_ROOT,
        status="pending",
    )
    session.add(reward)
    session.flush()

    referred.referred_by_player_id = referrer_id
    session.flush()

    return reward


def check_and_reward(
    session: Session,
    player_id: str,
) -> ReferralReward | None:
    """Начислить награду пригласившему, если приглашённый достиг порога.

    Порядок проверок: программа включена -> у игрока есть реферер -> есть
    pending-запись -> earned >= порога. Начисление — одна credit-проводка
    пригласившему с ``reference_type='referral_reward'`` и
    ``reference_id = ReferralReward.id``, затем статус ``credited``.

    Возвращает начисленную запись или None (нечего начислять/повтор).
    Кошелёк пригласившего берётся через ``_get_root_wallet_for_update``
    (PostgreSQL — FOR UPDATE, SQLite — no-op); баланс — кэш, ledger —
    источник истины.
    """
    if not _read_bool_setting(session, REFERRAL_ENABLED_KEY, False):
        return None

    player = session.get(GamePlayer, player_id)
    if player is None or player.referred_by_player_id is None:
        return None

    reward = session.scalar(
        select(ReferralReward).where(
            ReferralReward.referred_player_id == player_id
        )
    )
    if reward is None or reward.status != "pending":
        return None

    threshold = _read_int_setting(
        session, EARNED_THRESHOLD_KEY, DEFAULT_EARNED_THRESHOLD
    )
    if _earned_root(session, player_id) < threshold:
        return None

    wallet = _get_root_wallet_for_update(session, reward.referrer_player_id)
    wallet.available_balance += reward.amount_root
    # Sprint 11.8 NanoROOT: зеркальная запись (dual-write).
    wallet.available_balance_nano = (
        wallet.available_balance * NANO_PER_ROOT
    )
    session.add(
        WalletTransaction(
            id=_new_id("wallet-transaction"),
            wallet_id=wallet.id,
            amount=reward.amount_root,
            amount_nano=reward.amount_root * NANO_PER_ROOT,
            balance_after=wallet.available_balance,
            balance_after_nano=wallet.available_balance_nano,
            transaction_type="credit",
            reason="Referral reward",
            reference_type=REFERRAL_REFERENCE_TYPE,
            reference_id=reward.id,
            metadata_json={
                "referralRewardId": reward.id,
                "referrerPlayerId": reward.referrer_player_id,
                "referredPlayerId": reward.referred_player_id,
            },
        )
    )

    reward.status = "credited"
    session.flush()

    return reward
