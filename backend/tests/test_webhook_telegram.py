"""Unit-тесты Telegram webhook (10.4-h): POST /webhook/telegram.

Прямой вызов telegram_webhook с mock Request (SimpleNamespace с headers) —
в проекте TestClient не используется нигде (все — fake-объекты /
SimpleNamespace, см. test_admin_*), а эндпоинт использует только
request.headers.get(...). БД не нужна: stars_service-хендлеры
замоканы как module-level имена app.main (именно туда они импортированы).

Settings — dataclass(frozen=True) (config.py), поэтому
patch.object(settings, "telegram_webhook_secret", ...) упал бы на
FrozenInstanceError; вместо этого патчится сам объект app.main.settings
на SimpleNamespace с нужным значением secret.

Покрывает:
  1. пустой TELEGRAM_WEBHOOK_SECRET (dev) — 200 без проверки заголовка;
  2. заданный secret, нет/неверный заголовок — HTTPException 403;
  3. заданный secret, верный заголовок — 200, роутинг выполнен;
  4. pre_checkout_query -> вызывается только handle_pre_checkout_query;
  5. message.successful_payment -> вызывается только
     handle_successful_payment;
  6. неизвестный тип update (message.text) -> 200, оба хендлера молчат.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app.main import telegram_webhook

WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _dev_settings() -> SimpleNamespace:
    """settings-заглушка для dev (secret пустой)."""
    return SimpleNamespace(telegram_webhook_secret="")


class TelegramWebhookTests(unittest.TestCase):
    def setUp(self) -> None:
        """Хендлеры stars_service замоканы как имена модуля app.main."""
        self._patch_pre_checkout = patch("app.main.handle_pre_checkout_query")
        self._patch_successful_payment = patch("app.main.handle_successful_payment")
        self.mock_pre_checkout = self._patch_pre_checkout.start()
        self.mock_successful_payment = self._patch_successful_payment.start()

    def tearDown(self) -> None:
        self._patch_pre_checkout.stop()
        self._patch_successful_payment.stop()

    # ---- Хелперы ---------------------------------------------------------

    @staticmethod
    def _request_headers(headers: dict | None = None) -> dict:
        return dict(headers or {})

    @staticmethod
    def _update_pre_checkout() -> dict:
        """Update с pre_checkout_query (как присылает Telegram)."""
        return {
            "pre_checkout_query": {"id": "q1", "invoice_payload": "ref-1"},
        }

    @staticmethod
    def _update_successful_payment() -> dict:
        """Update с message.successful_payment."""
        return {
            "message": {
                "successful_payment": {
                    "invoice_payload": "ref-1",
                    "telegram_payment_charge_id": "charge-1",
                }
            }
        }

    @staticmethod
    def _update_unknown() -> dict:
        """Неизвестный тип update — должен игнорироваться."""
        return {"message": {"text": "hello"}}

    @staticmethod
    def _call(request_headers: dict, update: dict) -> dict:
        """Прямой вызов telegram_webhook c mock Request (headers)."""
        request = SimpleNamespace(headers=request_headers)
        return telegram_webhook(request, update)

    # ---- Тесты ---------------------------------------------------------------

    def test_webhook_secret_dev_empty_ok(self) -> None:
        """Пустой secret (dev): 200 без проверки заголовка, роутинг работает."""
        update = self._update_pre_checkout()
        with patch("app.main.settings", _dev_settings()):
            result = self._call(request_headers={}, update=update)

        self.assertEqual(result, {"ok": True})
        self.mock_pre_checkout.assert_called_once_with(update)
        self.mock_successful_payment.assert_not_called()

    def test_webhook_secret_mismatch_403(self) -> None:
        """Задан secret, но заголовка нет / он неверный -> 403.

        Оба случая обязаны отклоняться ДО роутинга — хендлеры молчат.
        """
        secured_settings = SimpleNamespace(telegram_webhook_secret="secret123")

        # Без заголовка.
        with patch("app.main.settings", secured_settings):
            with self.assertRaises(HTTPException) as context:
                self._call(request_headers={}, update=self._update_pre_checkout())
        self.assertEqual(context.exception.status_code, 403)

        # Неверный заголовок.
        with patch("app.main.settings", secured_settings):
            with self.assertRaises(HTTPException) as context:
                self._call(
                    request_headers={WEBHOOK_SECRET_HEADER: "wrong-secret"},
                    update=self._update_pre_checkout(),
                )
        self.assertEqual(context.exception.status_code, 403)

        self.mock_pre_checkout.assert_not_called()
        self.mock_successful_payment.assert_not_called()

    def test_webhook_secret_correct_200(self) -> None:
        """Задан secret и верный заголовок -> 200, роутинг выполнен."""
        update = self._update_pre_checkout()
        with patch(
            "app.main.settings",
            SimpleNamespace(telegram_webhook_secret="secret123"),
        ):
            result = self._call(
                request_headers={WEBHOOK_SECRET_HEADER: "secret123"},
                update=update,
            )

        self.assertEqual(result, {"ok": True})
        self.mock_pre_checkout.assert_called_once_with(update)
        self.mock_successful_payment.assert_not_called()

    def test_webhook_routes_pre_checkout(self) -> None:
        """pre_checkout_query -> вызывается только pre_checkout-хендлер."""
        update = self._update_pre_checkout()
        with patch("app.main.settings", _dev_settings()):
            result = self._call(request_headers={}, update=update)

        self.assertEqual(result, {"ok": True})
        self.mock_pre_checkout.assert_called_once_with(update)
        self.mock_successful_payment.assert_not_called()

    def test_webhook_routes_successful_payment(self) -> None:
        """message.successful_payment -> только successful_payment-хендлер."""
        update = self._update_successful_payment()
        with patch("app.main.settings", _dev_settings()):
            result = self._call(request_headers={}, update=update)

        self.assertEqual(result, {"ok": True})
        self.mock_successful_payment.assert_called_once_with(update)
        self.mock_pre_checkout.assert_not_called()

    def test_webhook_unknown_update_ignored(self) -> None:
        """Неизвестный update (message.text) -> 200, хендлеры не вызываются."""
        update = self._update_unknown()
        with patch("app.main.settings", _dev_settings()):
            result = self._call(request_headers={}, update=update)

        self.assertEqual(result, {"ok": True})
        self.mock_pre_checkout.assert_not_called()
        self.mock_successful_payment.assert_not_called()