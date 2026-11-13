"""Sprint 11.8 NanoROOT, этап 1, шаг 1.3: проверка dual-write.

Каждая мутирующая ROOT-операция должна параллельно со старыми *_root полями
записывать *_nano = *_root * 10^8. Тесты прогоняют сервисы на СВЕЖИХ данных
(изолированная in-memory SQLite + ``Base.metadata.create_all`` — колонки *_nano
уже в моделях; триггеры immutability для INSERT не нужны) и сверяют, что после
операции Wallet.available_balance_nano, WalletTransaction.amount_nano /
balance_after_nano согласованы с целыми значениями.

Сервисы вызываются напрямую с переданной Session (как в
test_referral_service), поэтому не зависят от backend/chimera.db. Для
withdrawal_service, который сам открывает SessionLocal, sessionmaker патчится
на изолированную БД.
"""

from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.mission_engine import _get_root_wallet_for_update, _new_id
from app.models import (
    GamePlayer,
    Item,
    Mission,
    MissionReward,
    ReferralReward,
    Season,
    SystemSetting,
    Wallet,
    WalletTransaction,
)

NANO = 100_000_000

# Валидный тестнет-адрес TON (каноническая форма, pytoniq валидирует локально).
VALID_TON_ADDRESS = "kQA5FajPC6c_6qcU5Ek2RgZfmmeZP_bftqYe16AuLXe6aMpH"


def _setting(key: str, value, category: str) -> SystemSetting:
    """Активная строка system_settings (как в seed-миграции)."""
    return SystemSetting(
        key=key,
        value_json=value,
        value_type="boolean" if isinstance(value, bool) else "integer",
        category=category,
        title=key,
        description="Seeded by nanoroot dual-write test",
        is_sensitive=False,
        status="active",
    )


class NanoRootDualWriteTests(unittest.TestCase):
    """Проверки *_nano == *_root * 10^8 после каждой мутирующей операции."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        # CMS-настройки: щедрые лимиты, чтобы операции не блокировались на
        # проверках (earned-порог, gas-процент, цена, вывод).
        self.session.add_all(
            [
                _setting("referral.enabled", True, "referral"),
                _setting("referral.reward_root", 25, "referral"),
                _setting("economy.transfer_minimum_earned_root", 0, "economy"),
                _setting("economy.gas_fee_percent", 0, "economy"),
                _setting("shop.catalog.enabled", True, "shop"),
                _setting("shop.catalog.default_price_root", 10, "shop"),
                _setting("ton.withdrawal_enabled", True, "ton"),
                _setting("ton.min_amount_root", 1, "ton"),
                _setting("ton.daily_withdrawal_limit", 100000, "ton"),
            ]
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    # ---- Хелперы ----------------------------------------------------------

    def _make_player(self, player_id: str) -> None:
        self.session.add(
            GamePlayer(
                id=player_id,
                display_name=player_id,
                auth_provider="test",
                external_id=f"tg-{player_id}",
                status="active",
            )
        )
        self.session.flush()

    def _make_wallet(self, player_id: str, root: int) -> Wallet:
        wallet = Wallet(
            id=_new_id("wallet"),
            player_id=player_id,
            currency="ROOT",
            available_balance=root,
            locked_balance=0,
            available_balance_nano=root * NANO,
            locked_balance_nano=0,
        )
        self.session.add(wallet)
        self.session.flush()
        return wallet

    def _wallet(self, player_id: str) -> Wallet:
        wallet = self.session.scalar(
            select(Wallet).where(Wallet.player_id == player_id)
        )
        self.assertIsNotNone(wallet)
        return wallet

    def _make_mission(self, slug: str) -> Mission:
        """Published text_answer-миссия с Season (FK NOT NULL)."""
        suffix = uuid.uuid4().hex
        season = Season(
            id=_new_id("season"),
            slug=f"season-{suffix}",
            title="Test season",
            description="Fixture",
            status="published",
            sort_order=1,
        )
        self.session.add(season)
        self.session.flush()
        mission = Mission(
            id=_new_id("mission"),
            season_id=season.id,
            mission_type="text_answer",
            slug=slug,
            title="Test mission",
            description="Fixture",
            content={"schemaVersion": 1},
            validation_config={"validator": "normalized_text_match"},
            status="published",
        )
        self.session.add(mission)
        self.session.flush()
        return mission

    def assert_nano_consistent(self, player_id: str, *, root_expected: int | None = None):
        """Сверить *_nano с *_root для Wallet и всех его WalletTransaction."""
        wallet = self._wallet(player_id)
        if root_expected is not None:
            self.assertEqual(
                wallet.available_balance,
                root_expected,
                f"available_balance != {root_expected}",
            )
        self.assertEqual(
            wallet.available_balance_nano,
            wallet.available_balance * NANO,
            "Wallet.available_balance_nano != available_balance * 10^8",
        )
        self.assertEqual(
            wallet.locked_balance_nano,
            wallet.locked_balance * NANO,
            "Wallet.locked_balance_nano != locked_balance * 10^8",
        )
        txs = self.session.scalars(
            select(WalletTransaction).where(WalletTransaction.wallet_id == wallet.id)
        ).all()
        self.assertTrue(txs, "ожидалась хотя бы одна проводка")
        for tx in txs:
            self.assertEqual(
                tx.amount_nano,
                tx.amount * NANO,
                f"WalletTransaction({tx.id}).amount_nano != amount * 10^8",
            )
            self.assertEqual(
                tx.balance_after_nano,
                tx.balance_after * NANO,
                f"WalletTransaction({tx.id}).balance_after_nano != balance_after * 10^8",
            )
        return wallet

    # ---- Тесты ------------------------------------------------------------

    def test_dual_write_transfer(self) -> None:
        """P2P-перевод: debit отправителю + credit получателю согласованы."""
        from app.transfer_service import transfer_root

        self._make_player("from-player")
        self._make_player("to-player")
        self._make_wallet("from-player", 100)
        self._make_wallet("to-player", 0)

        transfer_root(self.session, "from-player", "to-player", 40, "req-transfer-1")
        self.session.commit()

        self.assert_nano_consistent("from-player", root_expected=60)
        self.assert_nano_consistent("to-player", root_expected=40)

    def test_dual_write_referral_reward(self) -> None:
        """Реферальная награда: credit + ReferralReward.amount_root_nano."""
        from app.referral_service import check_and_reward

        self._make_player("referrer")
        self._make_player("referred")
        self._make_wallet("referrer", 0)
        self._make_wallet("referred", 0)

        reward = ReferralReward(
            id=_new_id("referral-reward"),
            referrer_player_id="referrer",
            referred_player_id="referred",
            amount_root=25,
            amount_root_nano=25 * NANO,
            status="pending",
        )
        self.session.add(reward)
        referred = self.session.get(GamePlayer, "referred")
        referred.referred_by_player_id = "referrer"
        self.session.flush()

        check_and_reward(self.session, "referred")
        self.session.commit()

        stored = self.session.scalar(
            select(ReferralReward).where(ReferralReward.id == reward.id)
        )
        self.assertEqual(stored.amount_root_nano, stored.amount_root * NANO)
        self.assert_nano_consistent("referrer", root_expected=25)

    def test_dual_write_withdrawal_hold_and_refund(self) -> None:
        """Вывод: hold (debit) и refund (credit) + WithdrawalRequest.amount_root_nano."""
        from sqlalchemy.orm import sessionmaker

        from app import withdrawal_service
        from app.models import WithdrawalRequest
        from app.withdrawal_service import (
            _refund_withdrawal_hold,
            create_withdrawal_request,
        )

        self._make_player("withdrawer")
        self._make_wallet("withdrawer", 100)

        # create_withdrawal_request открывает свой SessionLocal — патчим его.
        session_local = sessionmaker(bind=self.engine)
        with patch.object(withdrawal_service, "SessionLocal", session_local):
            result = create_withdrawal_request("withdrawer", 30, VALID_TON_ADDRESS)

        self.session.commit()
        self.assert_nano_consistent("withdrawer", root_expected=70)

        withdrawal = self.session.scalar(
            select(WithdrawalRequest).where(
                WithdrawalRequest.id == result["withdrawalId"]
            )
        )
        self.assertEqual(withdrawal.amount_root_nano, withdrawal.amount_root * NANO)

        # Refund (имитация reject/failed): возврат холда.
        _refund_withdrawal_hold(self.session, withdrawal)
        self.session.commit()
        self.assert_nano_consistent("withdrawer", root_expected=100)


    def test_dual_write_shop_purchase(self) -> None:
        """Покупка в каталоге: debit согласован."""
        from app.shop_service import purchase_catalog_item

        self._make_player("buyer")
        self._make_wallet("buyer", 50)
        item = Item(
            id=_new_id("item"),
            slug="shop-key",
            code="SHOP-KEY",
            title="Shop key",
            description="Key for purchase",
            symbol="K",
            category="KEY",
            rarity="common",
            is_unique=False,
            content={"schemaVersion": 1},
            status="published",
        )
        self.session.add(item)
        self.session.flush()

        purchase_catalog_item(self.session, "buyer", item.id)
        self.session.commit()

        self.assert_nano_consistent("buyer", root_expected=40)

    def test_dual_write_mission_award(self) -> None:
        """Награда миссии (credit ROOT) согласована."""
        from app.mission_engine import _award_mission_rewards

        self._make_player("earner")
        self._make_wallet("earner", 0)
        mission = self._make_mission("reward-mission")
        self.session.add(
            MissionReward(
                id=_new_id("reward"),
                mission_id=mission.id,
                reward_type="currency",
                amount=15,
                reward_value={"currency": "ROOT"},
                sort_order=1,
            )
        )
        self.session.flush()

        _award_mission_rewards(
            self.session, "earner", mission, reference_id=mission.id
        )
        self.session.commit()

        self.assert_nano_consistent("earner", root_expected=15)


    def test_dual_write_mission_entry_debit(self) -> None:
        """Списание за вход в миссию (debit ROOT) согласовано."""
        from app.mission_engine import _apply_entry_debit

        self._make_player("entrant")
        self._make_wallet("entrant", 100)
        mission = self._make_mission("entry-mission")

        _apply_entry_debit(
            self.session,
            player_id="entrant",
            mission=mission,
            root_debit=30,
            requirements=[],
            reference_id=f"{mission.id}_entry_1",
        )
        self.session.commit()

        self.assert_nano_consistent("entrant", root_expected=70)

    def test_dual_write_admin_credit_debit(self) -> None:
        """Ручные credit/debit админом: обе проводки согласованы."""
        from app import admin_player_wallet
        from app.models import AdminUser

        admin = AdminUser(
            id="admin-1",
            username="admin",
            password_hash="x",
            role="super_admin",
            is_super_admin=True,
            is_active=True,
            is_deleted=False,
        )
        self.session.add(admin)
        self._make_player("target")
        self._make_wallet("target", 0)
        self.session.flush()

        audit_patch = patch("app.admin_player_wallet.write_admin_audit")
        audit_patch.start()
        self.addCleanup(audit_patch.stop)

        # credit: кошелёк существует, начисляем 50.
        wallet = self._wallet("target")
        admin_player_wallet._apply_wallet_adjustment(
            self.session,
            wallet=wallet,
            player_id="target",
            direction="credit",
            amount=50,
            reason="test credit",
            request_id="req-credit-1",
            admin=admin,
            request=None,
        )
        self.session.commit()
        self.assert_nano_consistent("target", root_expected=50)

        # debit: списываем 20.
        wallet = self._wallet("target")
        admin_player_wallet._apply_wallet_adjustment(
            self.session,
            wallet=wallet,
            player_id="target",
            direction="debit",
            amount=20,
            reason="test debit",
            request_id="req-debit-1",
            admin=admin,
            request=None,
        )
        self.session.commit()
        self.assert_nano_consistent("target", root_expected=30)


if __name__ == "__main__":
    unittest.main()

