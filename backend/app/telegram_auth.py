from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl


class TelegramAuthError(Exception):
    """Expected Telegram Mini App authentication error."""

    def __init__(self, detail: str, status_code: int = 401) -> None:
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


@dataclass(frozen=True)
class VerifiedTelegramUser:
    telegram_id: str
    first_name: str
    last_name: str | None
    username: str | None
    photo_url: str | None


def normalize_telegram_username(value: str | None) -> str | None:
    """Normalize @username for case-insensitive player lookup."""
    if not value:
        return None

    normalized = value.strip().lstrip("@").lower()

    if not normalized:
        return None

    # Telegram usernames: letters, digits and underscores; max length is 32.
    if len(normalized) > 32 or not all(
        character.isascii()
        and (character.isalnum() or character == "_")
        for character in normalized
    ):
        return None

    return normalized


def verify_init_data(
    init_data: str,
    bot_token: str,
    max_age_seconds: int,
) -> VerifiedTelegramUser:
    """
    Verify the original Telegram.WebApp.initData string.

    Never trust initDataUnsafe or a Telegram ID supplied separately by a browser.
    """
    if not init_data:
        raise TelegramAuthError("Требуется авторизация Telegram. Откройте игру заново.")

    if not bot_token:
        raise TelegramAuthError(
            "Авторизация Telegram временно недоступна. Попробуйте позже.",
            status_code=503,
        )

    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as error:
        raise TelegramAuthError("Ошибка авторизации Telegram. Откройте игру заново.") from error

    values: dict[str, str] = {}
    for key, value in pairs:
        if key in values:
            raise TelegramAuthError("Ошибка авторизации Telegram. Откройте игру заново.")
        values[key] = value

    received_hash = values.pop("hash", None)
    if not received_hash:
        raise TelegramAuthError("Ошибка авторизации Telegram. Откройте игру заново.")

    data_check_string = "\n".join(
        f"{key}={values[key]}" for key in sorted(values)
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    expected_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramAuthError("Ошибка авторизации Telegram. Откройте игру заново.")

    try:
        auth_date = int(values["auth_date"])
    except (KeyError, TypeError, ValueError) as error:
        raise TelegramAuthError("Ошибка авторизации Telegram. Откройте игру заново.") from error

    now = int(time.time())
    if auth_date > now + 60:
        raise TelegramAuthError(
            "Неверное время авторизации Telegram. Проверьте время на устройстве."
        )

    if now - auth_date > max_age_seconds:
        raise TelegramAuthError(
            "Сессия авторизации Telegram истекла. Откройте игру заново."
        )

    try:
        raw_user: Any = json.loads(values["user"])
        telegram_id = str(raw_user["id"])
        first_name = str(raw_user["first_name"]).strip()
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        raise TelegramAuthError(
            "Не удалось получить данные Telegram. Откройте игру заново."
        ) from error

    if not telegram_id.isdigit() or not first_name:
        raise TelegramAuthError(
            "Не удалось получить данные Telegram. Откройте игру заново."
        )

    username_raw = raw_user.get("username")
    username = str(username_raw).strip() if username_raw else None

    last_name_raw = raw_user.get("last_name")
    last_name = str(last_name_raw).strip() if last_name_raw else None

    photo_url_raw = raw_user.get("photo_url")
    photo_url = str(photo_url_raw).strip() if photo_url_raw else None

    return VerifiedTelegramUser(
        telegram_id=telegram_id,
        first_name=first_name[:128],
        last_name=last_name[:128] if last_name else None,
        username=normalize_telegram_username(username),
        photo_url=photo_url[:2048] if photo_url else None,
    )


def create_session_token(
    player_id: str,
    session_secret: str,
    lifetime_seconds: int,
) -> str:
    """Create a compact HMAC-signed opaque game session token."""
    if not session_secret:
        raise RuntimeError("GAME_SESSION_SECRET is not configured.")

    payload = {
        "player_id": player_id,
        "iat": int(time.time()),
        "exp": int(time.time()) + lifetime_seconds,
    }
    payload_json = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload_encoded = base64.urlsafe_b64encode(payload_json).rstrip(b"=")

    signature = hmac.new(
        session_secret.encode("utf-8"),
        payload_encoded,
        hashlib.sha256,
    ).digest()
    signature_encoded = base64.urlsafe_b64encode(signature).rstrip(b"=")

    return f"{payload_encoded.decode('ascii')}.{signature_encoded.decode('ascii')}"


def verify_session_token(session_token: str, session_secret: str) -> str:
    """Verify the signed CHIMERA session cookie and return its player_id."""
    if not session_token:
        raise TelegramAuthError("Требуется авторизация Telegram.")

    if not session_secret:
        raise TelegramAuthError(
            "Игровые сессии не настроены на сервере.",
            status_code=503,
        )

    try:
        payload_encoded, signature_encoded = session_token.split(".", 1)

        expected_signature = hmac.new(
            session_secret.encode("utf-8"),
            payload_encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()

        padding = "=" * (-len(signature_encoded) % 4)
        received_signature = base64.urlsafe_b64decode(
            (signature_encoded + padding).encode("ascii")
        )

        if not hmac.compare_digest(expected_signature, received_signature):
            raise TelegramAuthError("Игровая сессия недействительна.")

        payload_padding = "=" * (-len(payload_encoded) % 4)
        payload_raw = base64.urlsafe_b64decode(
            (payload_encoded + payload_padding).encode("ascii")
        )
        payload = json.loads(payload_raw.decode("utf-8"))

        player_id = str(payload["player_id"])
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
    except TelegramAuthError:
        raise
    except (
        ValueError,
        KeyError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as error:
        raise TelegramAuthError("Игровая сессия имеет неверный формат.") from error

    now = int(time.time())

    if issued_at > now + 60:
        raise TelegramAuthError("Игровая сессия имеет неверное время создания.")

    if expires_at <= now:
        raise TelegramAuthError("Игровая сессия истекла. Откройте игру заново.")

    if not player_id.startswith("player-") and player_id != "demo-player":
        raise TelegramAuthError("Игровая сессия содержит неверный профиль.")

    return player_id
