"""Sprint Referral R-3: start_param в verify_init_data (app.telegram_auth).

Проверяется только чтение start_param из original initData: значение
возвращается, если поле присутствует, и None, если поля нет. initData
подписывается тем же алгоритмом, который проверяет verify_init_data
(HMAC-SHA256 с ключом HMAC(b"WebAppData", bot_token)); сеть и БД не
используются, реальный bot token из .env не читается и не печатается —
в тестах используется фиктивная строка.

Формат значения (``ref_<player_id>``) здесь сознательно не валидируется:
это задача ReferralService (R-4/R-5), поэтому «битый» start_param обязан
вернуться из verify_init_data как есть.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import unittest
from urllib.parse import urlencode

from app.telegram_auth import verify_init_data

# Фиктивный токен: подпись считается локально, к реальному боту отношения нет.
BOT_TOKEN = "123456:test-bot-token-not-a-real-secret"
INIT_DATA_MAX_AGE_SECONDS = 3600


def _sign_init_data(fields: dict[str, str]) -> str:
    """Собрать initData с корректной подписью (алгоритм verify_init_data).

    hash вырезается из data_check_string (как в app/telegram_auth.py) и
    добавляется в query-строку последним.
    """
    data_check_string = "\n".join(
        f"{key}={fields[key]}" for key in sorted(fields)
    )
    secret_key = hmac.new(
        b"WebAppData",
        BOT_TOKEN.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return urlencode({**fields, "hash": signature})


def _base_fields() -> dict[str, str]:
    """Минимальный набор подписанных полей initData (без start_param)."""
    return {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(
            {
                "id": 987654321,
                "first_name": "Referral",
                "username": "ref_user",
            },
            separators=(",", ":"),
        ),
    }


class VerifyInitDataStartParamTests(unittest.TestCase):
    """Referral-3: start_param читается из подписанного initData."""

    def test_start_param_present(self) -> None:
        """Подписанный initData со start_param -> значение возвращается.

        Дополнительно проверяется, что значение без префикса ref_ не
        отбрасывается и не нормализуется: валидация формата живёт в
        ReferralService (R-4/R-5), а не в auth-слое.
        """
        result = verify_init_data(
            init_data=_sign_init_data(
                {**_base_fields(), "start_param": "ref_player-abc"}
            ),
            bot_token=BOT_TOKEN,
            max_age_seconds=INIT_DATA_MAX_AGE_SECONDS,
        )

        self.assertEqual(result.start_param, "ref_player-abc")
        # Остальные поля разобраны как раньше — регрессии нет.
        self.assertEqual(result.telegram_id, "987654321")
        self.assertEqual(result.username, "ref_user")

        malformed = verify_init_data(
            init_data=_sign_init_data(
                {**_base_fields(), "start_param": "not-a-ref-param"}
            ),
            bot_token=BOT_TOKEN,
            max_age_seconds=INIT_DATA_MAX_AGE_SECONDS,
        )

        self.assertEqual(malformed.start_param, "not-a-ref-param")

    def test_start_param_absent(self) -> None:
        """initData без start_param -> None (запуск без реферальной ссылки)."""
        result = verify_init_data(
            init_data=_sign_init_data(_base_fields()),
            bot_token=BOT_TOKEN,
            max_age_seconds=INIT_DATA_MAX_AGE_SECONDS,
        )

        self.assertIsNone(result.start_param)


if __name__ == "__main__":
    unittest.main()
