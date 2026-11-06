"""Sprint Referral R-5: HTTP-слой рефералки (app.main).

1. ``test_get_my_referral`` — GET /api/v1/engine/me/referral: enabled и
   rewardRoot из CMS (фолбэк на каталог), shareLink из
   settings.telegram_bot_username, referredBy — кто пригласил игрока.
2. ``test_auth_with_ref_param`` — тело POST /api/v1/auth/telegram (slowapi
   обойдён через ``__wrapped__``, как в test_player_events.py): новый игрок
   с start_param="ref_<пригласивший>" получает referred_by_player_id и
   pending-запись ReferralReward.

Мокается только verify_init_data (внешняя крипто-проверка Telegram); upsert
игрока, привязка реферера и PlayerEvent — реальный код. БД — изолированная
SQLite in-memory (``Base.metadata.create_all``), SessionLocal патчится в
app.main/app.db; settings подменяется безопасными тестовыми значениями
(реальные секреты из .env не читаются и не печатаются).
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from starlette.responses import Response

import app.main as main_module
from app.config import settings as real_settings
from app.db import Base
from app.models import GamePlayer, ReferralReward, SystemSetting
from app.telegram_auth import VerifiedTelegramUser

REFERRER_ID = "player-referrer"
REFERRED_ID = "player-referred"
NEW_TELEGRAM_ID = "500500"
TEST_BOT_USERNAME = "test_bot"
TEST_SESSION_SECRET = "test-session-secret-not-a-real-one"


class ReferralEndpointTests(unittest.TestCase):
    """Изолированная in-memory SQLite + подменённые SessionLocal и settings."""

    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )
        self._patches = [
            patch("app.main.SessionLocal", self.SessionLocal),
            patch("app.db.SessionLocal", self.SessionLocal),
            patch(
                "app.main.settings",
                replace(
                    real_settings,
                    telegram_bot_username=TEST_BOT_USERNAME,
                    game_session_secret=TEST_SESSION_SECRET,
                ),
            ),
        ]
        for patcher in self._patches:
            patcher.start()

        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=REFERRER_ID,
                    display_name="Referrer",
                    auth_provider="telegram",
                    external_id="777",
                    status="active",
                )
            )

    def tearDown(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        self.engine.dispose()

    def _set_setting(self, key: str, value, category: str) -> None:
        with self.SessionLocal.begin() as session:
            session.merge(
                SystemSetting(
                    key=key,
                    value_json=value,
                    value_type="boolean" if isinstance(value, bool) else "integer",
                    category=category,
                    title=key,
                    description="Seeded by referral endpoint test",
                    is_sensitive=False,
                    status="active",
                )
            )

    def test_get_my_referral(self) -> None:
        """Карточка рефералки: фолбэк каталога, CMS-значения, shareLink, referredBy."""
        # 1. Настроек в БД нет -> defaults каталога (False / 25).
        first = main_module.get_my_referral_route(
            request=SimpleNamespace(),
            player_id=REFERRER_ID,
        )
        self.assertFalse(first["enabled"])
        self.assertEqual(first["rewardRoot"], 25)
        self.assertEqual(
            first["shareLink"],
            f"https://t.me/{TEST_BOT_USERNAME}?start=ref_{REFERRER_ID}",
        )
        self.assertIsNone(first["referredBy"])

        # 2. CMS включила программу и изменила награду; игрок привязан.
        self._set_setting("referral.enabled", True, "referral")
        self._set_setting("referral.reward_root", 40, "referral")
        with self.SessionLocal.begin() as session:
            session.add(
                GamePlayer(
                    id=REFERRED_ID,
                    display_name="Referred",
                    auth_provider="telegram",
                    external_id="888",
                    status="active",
                    referred_by_player_id=REFERRER_ID,
                )
            )

        second = main_module.get_my_referral_route(
            request=SimpleNamespace(),
            player_id=REFERRED_ID,
        )
        self.assertTrue(second["enabled"])
        self.assertEqual(second["rewardRoot"], 40)
        self.assertEqual(
            second["shareLink"],
            f"https://t.me/{TEST_BOT_USERNAME}?start=ref_{REFERRED_ID}",
        )
        self.assertEqual(second["referredBy"], REFERRER_ID)

    def test_auth_with_ref_param(self) -> None:
        """Новый игрок со start_param="ref_<id>" получает реферера и pending-запись."""
        fake_telegram_user = VerifiedTelegramUser(
            telegram_id=NEW_TELEGRAM_ID,
            first_name="New Player",
            last_name=None,
            username="newplayer",
            photo_url=None,
            start_param=f"ref_{REFERRER_ID}",
        )

        # __wrapped__: обходим slowapi-обёртку limiter.limit (вызов вне
        # FastAPI/request-контекста), тело endpoint исполняется полностью.
        with patch(
            "app.main.verify_init_data", return_value=fake_telegram_user
        ):
            response = main_module.authenticate_telegram.__wrapped__(
                request=SimpleNamespace(state=None),
                payload=main_module.TelegramAuthPayload(
                    init_data="unused-init-data"
                ),
                response=Response(),
            )

        new_player_id = response["player"]["id"]
        self.assertTrue(new_player_id.startswith("player-"))

        with self.SessionLocal() as session:
            player = session.get(GamePlayer, new_player_id)
            reward = session.scalar(
                select(ReferralReward).where(
                    ReferralReward.referred_player_id == new_player_id
                )
            )

        assert player is not None
        self.assertEqual(player.referred_by_player_id, REFERRER_ID)
        self.assertIsNotNone(reward)
        assert reward is not None
        self.assertEqual(reward.referrer_player_id, REFERRER_ID)
        self.assertEqual(reward.status, "pending")
        self.assertEqual(reward.amount_root, 25)  # default каталога


if __name__ == "__main__":
    unittest.main()
