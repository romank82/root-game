"""Sprint Referral R-6: реферальный бонус как побочный эффект награды миссии.

Проверяется вставка в ``mission_engine._award_mission_rewards``:

1. ``test_referral_reward_on_mission_reward`` — приглашённый получает ROOT
   миссии >= порога -> пригласивший получает referral.reward_root одной
   проводкой (reference_type="referral_reward"), запись -> "credited".
2. ``test_referral_reward_idempotent`` — повторная награда миссии не
   начисляет бонус второй раз (ledger неизменен, баланс тот же).
3. ``test_referral_failure_does_not_break_mission_reward`` — падение
   check_and_reward (мок) не ломает награду миссии: SAVEPOINT откатывает
   только бонус, транзакция остаётся пригодной для commit.

Изолированная SQLite in-memory (``Base.metadata.create_all``), без alembic и
сети. CMS-цепочка минимальная: Season -> Chapter -> Mission -> MissionReward.
referral.reward_root и порог earned не задаются строками system_settings —
берутся defaults каталога (25 и 50), что тоже является проверкой фолбэка.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.mission_engine import _award_mission_rewards
from app.models import (
    Chapter,
    GamePlayer,
    Mission,
    MissionReward,
    ReferralReward,
    Season,
    SystemSetting,
    Wallet,
    WalletTransaction,
)
from app.referral_service import REFERRAL_REFERENCE_TYPE, assign_referrer

REFERRER_ID = "player-referrer"
REFERRED_ID = "player-referred"
MISSION_ID = "mission-referral"
REWARD_ROOT = 25  # default каталога referral.reward_root
EARNED_THRESHOLD = 50  # default каталога economy.transfer_minimum_earned_root
MISSION_REWARD_ROOT = 50  # equals порогу: награда миссии сразу его достигает


class ReferralMissionRewardTestCase(unittest.TestCase):
    """Общий setUp: игроки, миссия с ROOT-наградой, CMS-флаг программы."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self._seed_content()
        self._make_player(REFERRER_ID, "777")
        self._make_player(REFERRED_ID, "888")
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _seed_content(self) -> None:
        """Season -> Chapter -> Mission -> MissionReward (50 ROOT)."""
        self.session.add(
            Season(
                id="season-referral",
                slug="season-referral",
                title="Season",
                status="published",
            )
        )
        self.session.flush()
        self.session.add(
            Chapter(
                id="chapter-referral",
                season_id="season-referral",
                slug="chapter-referral",
                title="Chapter",
                status="published",
            )
        )
        self.session.flush()
        self.session.add(
            Mission(
                id=MISSION_ID,
                chapter_id="chapter-referral",
                slug="referral-mission",
                mission_type="text_answer",
                title="Referral mission",
                description="Grants ROOT reward",
                content={"schemaVersion": 1},
                validation_config={
                    "validator": "normalized_text_match",
                    "acceptedAnswers": ["ok"],
                },
                status="published",
                sort_order=1,
            )
        )
        self.session.flush()
        self.session.add(
            MissionReward(
                id="reward-referral-root",
                mission_id=MISSION_ID,
                reward_type="currency",
                amount=MISSION_REWARD_ROOT,
                reward_value={"currency": "ROOT"},
                sort_order=1,
            )
        )
        self.session.flush()

    def _make_player(self, player_id: str, external_id: str) -> None:
        self.session.add(
            GamePlayer(
                id=player_id,
                display_name=player_id,
                auth_provider="telegram",
                external_id=external_id,
                status="active",
            )
        )
        self.session.flush()

    def _enable_referral(self) -> None:
        """Включить программу; reward_root и порог — defaults каталога."""
        self.session.merge(
            SystemSetting(
                key="referral.enabled",
                value_json=True,
                value_type="boolean",
                category="referral",
                title="referral.enabled",
                description="Seeded by referral mission reward test",
                is_sensitive=False,
                status="active",
            )
        )
        self.session.flush()

    def _attach_referral(self) -> ReferralReward:
        """Привязать приглашённого к рефереру (pending-запись)."""
        reward = assign_referrer(
            self.session, REFERRED_ID, f"ref_{REFERRER_ID}"
        )
        assert reward is not None, "assign_referrer не создал pending-запись"
        return reward

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


class MissionRewardReferralTests(ReferralMissionRewardTestCase):
    """R-6: награда миссии у приглашённого триггерит бонус рефереру."""

    def test_referral_reward_on_mission_reward(self) -> None:
        """ROOT-награда миссии достигла порога -> реферер получает 25 ROOT."""
        self._enable_referral()
        reward = self._attach_referral()
        self.session.commit()

        awarded = _award_mission_rewards(
            self.session,
            REFERRED_ID,
            self.session.get(Mission, MISSION_ID),
        )
        self.session.commit()

        # Награда миссии выдана как обычно.
        self.assertEqual(awarded["root"], MISSION_REWARD_ROOT)
        self.assertEqual(self._wallet_balance(REFERRED_ID), MISSION_REWARD_ROOT)

        # Бонус рефереру: одна проводка, ссылка — на ReferralReward.
        self.assertEqual(self._wallet_balance(REFERRER_ID), REWARD_ROOT)
        transactions = self._referral_transactions()
        self.assertEqual(len(transactions), 1)
        self.assertEqual(transactions[0].reference_id, reward.id)
        self.assertEqual(transactions[0].amount, REWARD_ROOT)
        self.assertEqual(transactions[0].transaction_type, "credit")

        stored = self.session.get(ReferralReward, reward.id)
        assert stored is not None
        self.assertEqual(stored.status, "credited")

    def test_referral_reward_idempotent(self) -> None:
        """Повторная награда миссии не начисляет бонус второй раз."""
        self._enable_referral()
        reward = self._attach_referral()
        self.session.commit()
        mission = self.session.get(Mission, MISSION_ID)

        first = _award_mission_rewards(self.session, REFERRED_ID, mission)
        self.session.commit()
        self.assertEqual(first["root"], MISSION_REWARD_ROOT)

        # Новый per-run reference_id: награда миссии проводится снова,
        # но бонус уже credited -> второй проводки быть не должно.
        second = _award_mission_rewards(
            self.session, REFERRED_ID, mission, reference_id="run-2"
        )
        self.session.commit()

        self.assertEqual(second["root"], MISSION_REWARD_ROOT)
        self.assertEqual(
            self._wallet_balance(REFERRED_ID), MISSION_REWARD_ROOT * 2
        )
        self.assertEqual(self._wallet_balance(REFERRER_ID), REWARD_ROOT)
        self.assertEqual(len(self._referral_transactions()), 1)

        stored = self.session.get(ReferralReward, reward.id)
        assert stored is not None
        self.assertEqual(stored.status, "credited")

    def test_referral_failure_does_not_break_mission_reward(self) -> None:
        """Падение бонуса не ломает награду миссии (SAVEPOINT откатывает бонус)."""
        self._enable_referral()
        reward = self._attach_referral()
        self.session.commit()
        mission = self.session.get(Mission, MISSION_ID)

        with patch(
            "app.referral_service.check_and_reward",
            side_effect=RuntimeError("boom"),
        ):
            awarded = _award_mission_rewards(
                self.session, REFERRED_ID, mission
            )
            # Транзакция не отравлена: commit проходит (иначе был бы
            # PendingRollbackError и награда миссии потерялась бы).
            self.session.commit()

        self.assertEqual(awarded["root"], MISSION_REWARD_ROOT)
        self.assertEqual(self._wallet_balance(REFERRED_ID), MISSION_REWARD_ROOT)
        # Бонус откатился целиком: ни баланса, ни проводки, запись pending.
        self.assertEqual(self._wallet_balance(REFERRER_ID), 0)
        self.assertEqual(self._referral_transactions(), [])
        stored = self.session.get(ReferralReward, reward.id)
        assert stored is not None
        self.assertEqual(stored.status, "pending")


if __name__ == "__main__":
    unittest.main()
