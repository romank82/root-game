"""Sprint Referral R-4: ReferralService (app.referral_service).

Два блока проверок:

1. ``AssignReferrerTests`` — привязка по ``ref_<player_id>``: успешная
   привязка (pending-запись + ``GamePlayer.referred_by_player_id``), self,
   невалидный/пустой параметр, повторная привязка.
2. ``CheckAndRewardTests`` — начисление пригласившему: выключенная программа,
   earned ROOT ниже порога, успешное начисление (одна credit-проводка +
   status="credited"), повторный вызов не дублирует ledger.

Изолированная SQLite in-memory (``Base.metadata.create_all``), без alembic,
сети и реальной БД: тесты не зависят от backend/chimera.db и его настроек.
CMS-значения задаются строками system_settings; там, где ключа нет,
срабатывает default каталога (referral.reward_root=25,
economy.transfer_minimum_earned_root=50) — это тоже проверяется.
"""

from __future__ import annotations

import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.mission_engine import _get_root_wallet_for_update, _new_id
from app.models import (
    GamePlayer,
    ReferralReward,
    SystemSetting,
    Wallet,
    WalletTransaction,
)
from app.referral_service import (
    EARNED_THRESHOLD_KEY,
    REFERRAL_ENABLED_KEY,
    REFERRAL_REFERENCE_TYPE,
    assign_referrer,
    check_and_reward,
)

REFERRER_ID = "player-referrer"
REFERRED_ID = "player-referred"
CATALOG_REWARD_ROOT = 25  # default каталога referral.reward_root
CATALOG_EARNED_THRESHOLD = 50  # default каталога economy.transfer_minimum_earned_root


class ReferralServiceTestCase(unittest.TestCase):
    """Общий setUp: изолированная in-memory SQLite и два игрока."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self._make_player(REFERRER_ID)
        self._make_player(REFERRED_ID)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _make_player(self, player_id: str, status: str = "active") -> None:
        self.session.add(
            GamePlayer(
                id=player_id,
                display_name=player_id,
                auth_provider="telegram",
                external_id=f"tg-{player_id}",
                status=status,
            )
        )
        self.session.flush()

    def _set_setting(self, key: str, value, category: str) -> None:
        """Активная строка system_settings (как её создаёт seed-миграция)."""
        self.session.merge(
            SystemSetting(
                key=key,
                value_json=value,
                value_type="boolean" if isinstance(value, bool) else "integer",
                category=category,
                title=key,
                description="Seeded by referral service test",
                is_sensitive=False,
                status="active",
            )
        )
        self.session.flush()

    def _seed_mission_reward(
        self,
        player_id: str,
        amount: int,
        reference_id: str,
    ) -> None:
        """Credit с reference_type='mission_reward' — то, что даёт earned ROOT."""
        wallet = _get_root_wallet_for_update(self.session, player_id)
        wallet.available_balance += amount
        self.session.add(
            WalletTransaction(
                id=_new_id("wallet-transaction"),
                wallet_id=wallet.id,
                amount=amount,
                balance_after=wallet.available_balance,
                transaction_type="credit",
                reason="Mission reward: seed",
                reference_type="mission_reward",
                reference_id=reference_id,
            )
        )
        self.session.flush()

    def _wallet_balance(self, player_id: str) -> int:
        wallet = self.session.scalar(
            select(Wallet).where(Wallet.player_id == player_id)
        )
        return wallet.available_balance if wallet is not None else 0

    def _referral_transactions(self) -> list[WalletTransaction]:
        return list(
            self.session.scalars(
                select(WalletTransaction).where(
                    WalletTransaction.reference_type == REFERRAL_REFERENCE_TYPE
                )
            ).all()
        )


class AssignReferrerTests(ReferralServiceTestCase):
    """Referral-4: привязка приглашённого по start_param."""

    def test_assign_referrer_ok(self) -> None:
        """ref_<пригласивший> -> pending-запись + referred_by_player_id."""
        reward = assign_referrer(
            self.session, REFERRED_ID, f"ref_{REFERRER_ID}"
        )
        self.session.commit()

        self.assertIsNotNone(reward)
        assert reward is not None
        self.assertEqual(reward.referrer_player_id, REFERRER_ID)
        self.assertEqual(reward.referred_player_id, REFERRED_ID)
        self.assertEqual(reward.status, "pending")
        # Значения нет в БД -> берётся default каталога.
        self.assertEqual(reward.amount_root, CATALOG_REWARD_ROOT)

        referred = self.session.get(GamePlayer, REFERRED_ID)
        assert referred is not None
        self.assertEqual(referred.referred_by_player_id, REFERRER_ID)

        # Награды ещё нет: ledger не тронут.
        self.assertEqual(self._referral_transactions(), [])

    def test_assign_referrer_self(self) -> None:
        """Приглашение самого себя -> None, привязки нет."""
        reward = assign_referrer(
            self.session, REFERRED_ID, f"ref_{REFERRED_ID}"
        )
        self.session.commit()

        self.assertIsNone(reward)
        referred = self.session.get(GamePlayer, REFERRED_ID)
        assert referred is not None
        self.assertIsNone(referred.referred_by_player_id)
        self.assertIsNone(self.session.scalar(select(ReferralReward)))

    def test_assign_referrer_invalid(self) -> None:
        """None / пустая строка / без префикса / пустой id -> None."""
        for ref_param in (None, "", "   ", "not-a-ref", "ref_", "ref_   "):
            with self.subTest(ref_param=ref_param):
                self.assertIsNone(
                    assign_referrer(self.session, REFERRED_ID, ref_param)
                )

        self.session.commit()
        self.assertIsNone(self.session.scalar(select(ReferralReward)))
        referred = self.session.get(GamePlayer, REFERRED_ID)
        assert referred is not None
        self.assertIsNone(referred.referred_by_player_id)

    def test_assign_referrer_already(self) -> None:
        """Повторная привязка (у игрока уже есть реферер) -> None, одна запись."""
        first = assign_referrer(
            self.session, REFERRED_ID, f"ref_{REFERRER_ID}"
        )
        self.session.commit()
        self.assertIsNotNone(first)

        # Даже с другим (несуществующим) реферером второй привязки не будет.
        second = assign_referrer(
            self.session, REFERRED_ID, "ref_player-someone-else"
        )
        self.session.commit()

        self.assertIsNone(second)
        rewards = list(self.session.scalars(select(ReferralReward)).all())
        self.assertEqual(len(rewards), 1)
        self.assertEqual(rewards[0].referrer_player_id, REFERRER_ID)


class CheckAndRewardTests(ReferralServiceTestCase):
    """Referral-4: начисление награды при достижении порога earned ROOT."""

    def _enable_referral(self) -> None:
        self._set_setting(REFERRAL_ENABLED_KEY, True, "referral")
        self._set_setting(EARNED_THRESHOLD_KEY, CATALOG_EARNED_THRESHOLD, "economy")

    def test_check_and_reward_disabled(self) -> None:
        """referral.enabled=False -> None, запись остаётся pending."""
        self._set_setting(REFERRAL_ENABLED_KEY, False, "referral")
        reward = assign_referrer(
            self.session, REFERRED_ID, f"ref_{REFERRER_ID}"
        )
        self._seed_mission_reward(REFERRED_ID, 100, "seed-disabled")
        self.session.commit()
        self.assertIsNotNone(reward)

        self.assertIsNone(check_and_reward(self.session, REFERRED_ID))
        self.session.commit()

        stored = self.session.scalar(select(ReferralReward))
        assert stored is not None
        self.assertEqual(stored.status, "pending")
        self.assertEqual(self._referral_transactions(), [])
        self.assertEqual(self._wallet_balance(REFERRER_ID), 0)

    def test_check_and_reward_below_threshold(self) -> None:
        """earned < порога -> None (порог берётся из CMS)."""
        self._enable_referral()
        assign_referrer(self.session, REFERRED_ID, f"ref_{REFERRER_ID}")
        self._seed_mission_reward(
            REFERRED_ID, CATALOG_EARNED_THRESHOLD - 1, "seed-below"
        )
        self.session.commit()

        self.assertIsNone(check_and_reward(self.session, REFERRED_ID))
        self.session.commit()

        stored = self.session.scalar(select(ReferralReward))
        assert stored is not None
        self.assertEqual(stored.status, "pending")
        self.assertEqual(self._referral_transactions(), [])

    def test_check_and_reward_ok(self) -> None:
        """earned >= порога -> credit пригласившему + status='credited'."""
        self._enable_referral()
        reward = assign_referrer(
            self.session, REFERRED_ID, f"ref_{REFERRER_ID}"
        )
        self._seed_mission_reward(
            REFERRED_ID, CATALOG_EARNED_THRESHOLD, "seed-ok"
        )
        self.session.commit()
        assert reward is not None

        credited = check_and_reward(self.session, REFERRED_ID)
        self.session.commit()

        self.assertIsNotNone(credited)
        assert credited is not None
        self.assertEqual(credited.status, "credited")
        self.assertEqual(credited.id, reward.id)

        # Пригласивший получил ровно reward_root (default каталога — 25).
        self.assertEqual(self._wallet_balance(REFERRER_ID), CATALOG_REWARD_ROOT)

        transactions = self._referral_transactions()
        self.assertEqual(len(transactions), 1)
        transaction = transactions[0]
        self.assertEqual(transaction.transaction_type, "credit")
        self.assertEqual(transaction.amount, CATALOG_REWARD_ROOT)
        self.assertEqual(transaction.balance_after, CATALOG_REWARD_ROOT)
        self.assertEqual(transaction.reference_id, reward.id)
        self.assertEqual(transaction.reason, "Referral reward")

    def test_check_and_reward_idempotent(self) -> None:
        """Повторный check -> None; в ledger одна проводка, баланс не растёт."""
        self._enable_referral()
        assign_referrer(self.session, REFERRED_ID, f"ref_{REFERRER_ID}")
        self._seed_mission_reward(
            REFERRED_ID, CATALOG_EARNED_THRESHOLD, "seed-idempotent"
        )
        self.session.commit()

        first = check_and_reward(self.session, REFERRED_ID)
        self.session.commit()
        self.assertIsNotNone(first)

        second = check_and_reward(self.session, REFERRED_ID)
        self.session.commit()

        self.assertIsNone(second)
        self.assertEqual(len(self._referral_transactions()), 1)
        self.assertEqual(self._wallet_balance(REFERRER_ID), CATALOG_REWARD_ROOT)


if __name__ == "__main__":
    unittest.main()
