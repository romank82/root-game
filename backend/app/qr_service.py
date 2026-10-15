"""
DEPRECATED (Sprint 8.13, 2026-10-15): не используется в solo-flow.
Контент мини-игры берётся из bootstrap миссии (mission.content).
Оставлен для team-flow и возможного физического QR в будущем.
Спецификация: docs/minigame-cipher.md, раздел 8.

Генерация подписанных QR-payload для миссий (Sprint 8.6.c).

Игрок в статусе in_progress получает payload + HMAC-подпись. QR рисуется
на грани AR-куба, игрок сканирует — сервер проверяет подпись и запускает
мини-игру (8.8).

Индивидуальность: payload содержит player_id и mission_id, а также
одноразовый nonce и timestamp. HMAC считается от GAME_SESSION_SECRET
с domain separation (QR_HMAC_DOMAIN), поэтому QR-подпись нельзя
переиспользовать как игровую сессию и наоборот.

Модуль — чистый криптографический примитив: без БД, без FastAPI, без
побочных эффектов. Доменные проверки (опубликована ли миссия, статус
player_mission == in_progress, активен ли игрок) живут в
mission_engine.get_mission_qr_payload.

См. также: telegram_auth.py — образец HMAC-SHA256 с base64url.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings


QR_HMAC_DOMAIN = b"qr:v1"
QR_TTL_SECONDS = 300
QR_SCHEMA_VERSION = 1


def _get_qr_secret() -> bytes:
    """Производный ключ из GAME_SESSION_SECRET через domain separation."""
    base_secret = settings.game_session_secret.encode()
    if not base_secret:
        raise RuntimeError("GAME_SESSION_SECRET is not configured.")
    return hmac.new(base_secret, QR_HMAC_DOMAIN, hashlib.sha256).digest()


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(value: str) -> bytes:
    pad = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + pad)


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()


def generate_qr_payload(
    *,
    player_id: str,
    mission_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Возвращает:
        {"payload": "<base64url-json>", "hmac": "<base64url-signature>",
         "expiresAt": "<iso>"}
    """
    current = now or datetime.now(timezone.utc)
    expires = current + timedelta(seconds=QR_TTL_SECONDS)

    body: dict[str, Any] = {
        "v": QR_SCHEMA_VERSION,
        "playerId": player_id,
        "missionId": mission_id,
        "nonce": uuid.uuid4().hex,
        "iat": int(current.timestamp()),
        "exp": int(expires.timestamp()),
    }

    payload_bytes = _canonical_json(body)
    signature = hmac.new(_get_qr_secret(), payload_bytes, hashlib.sha256).digest()

    return {
        "payload": _b64url_encode(payload_bytes),
        "hmac": _b64url_encode(signature),
        "expiresAt": expires.isoformat(),
    }


def verify_qr_payload(
    *,
    payload_b64: str,
    hmac_b64: str,
    expected_player_id: str,
    expected_mission_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Проверяет подпись и свежесть. Возвращает распарсенный body при успехе.
    Raises ValueError при любой проблеме (caller отдаёт общее сообщение).
    """
    try:
        payload_bytes = _b64url_decode(payload_b64)
        signature = _b64url_decode(hmac_b64)
    except Exception as exc:
        raise ValueError("invalid_base64") from exc

    expected_sig = hmac.new(_get_qr_secret(), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(expected_sig, signature):
        raise ValueError("invalid_hmac")

    try:
        body = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid_payload_json") from exc

    if not isinstance(body, dict):
        raise ValueError("payload_not_object")

    if body.get("v") != QR_SCHEMA_VERSION:
        raise ValueError("unsupported_schema_version")

    if body.get("playerId") != expected_player_id:
        raise ValueError("player_mismatch")

    if body.get("missionId") != expected_mission_id:
        raise ValueError("mission_mismatch")

    current = now or datetime.now(timezone.utc)
    exp = body.get("exp")
    if not isinstance(exp, int) or exp < int(current.timestamp()):
        raise ValueError("expired")

    return body


def get_qr_ttl_seconds() -> int:
    return QR_TTL_SECONDS


def split_payload_and_hmac(raw: str) -> tuple[str, str]:
    """
    Разбирает строку "payload.hmac" на две части.
    Raises ValueError("invalid_format") если точек нет или их больше одной.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("invalid_format")
    cleaned = raw.strip()
    if "." not in cleaned:
        raise ValueError("invalid_format")
    payload_b64, hmac_b64 = cleaned.rsplit(".", 1)
    if not payload_b64 or not hmac_b64:
        raise ValueError("invalid_format")
    return payload_b64, hmac_b64
