"""
Реестр обработчиков мини-игр (Sprint 8.17.14).

Каждая мини-игра — отдельный handler с двумя методами:
  - generate_session(settings: dict) -> dict — генерация сессии по параметрам сложности.
  - validate_submission(session_data: dict, sequence: list[str]) -> bool — проверка ответа.

Handler НЕ начисляет награды, НЕ меняет статус миссии, НЕ пишет в ledger/инвентарь.
Это делает mission_engine.py (порядок начислений заморожен, см. docs/roadmap-detailed.md).
"""
from __future__ import annotations

import random
from typing import Protocol


# Фиксированный алфавит cipher (A-Z + 0-9). Перенесён из mission_engine.py (8.17.14).
CIPHER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


class MinigameHandler(Protocol):
    """Контракт обработчика мини-игры."""

    def generate_session(self, settings: dict) -> dict:
        ...

    def validate_submission(self, session_data: dict | None, sequence: list[str] | None) -> bool:
        ...


class CipherHandler:
    """Cipher (drum-lock): генерация кода + барабанов, проверка sequence == correct_code."""

    def generate_session(self, settings: dict) -> dict:
        """Сгенерировать код + символы барабанов.

        settings: {drumCount: int 2..12, falseChoicesPerDrum: int 0..36,
                   timeLimitSeconds: int 1..3600 | None}.
        Возврат: {"correct_code": list[str], "drums": list[list[str]],
                  "timeLimitSeconds": int | None} (8.17-timer: лимит времени на
                  попытку прокидывается в сессию для таймера на фронте).
        Дефолты и клэмпы сохранены из mission_engine.generate_cipher_session (8.17.6).
        """
        drum_count = settings.get("drumCount", 4)
        false_choices = settings.get("falseChoicesPerDrum", 2)
        try:
            drum_count = int(drum_count)
            false_choices = int(false_choices)
        except (TypeError, ValueError):
            drum_count = 4
            false_choices = 2
        drum_count = max(2, min(drum_count, 12))
        false_choices = max(0, min(false_choices, 36))
        correct_code = [random.choice(CIPHER_ALPHABET) for _ in range(drum_count)]
        drums: list[list[str]] = []
        for correct in correct_code:
            false_pool = [symbol for symbol in CIPHER_ALPHABET if symbol != correct]
            if false_choices <= len(false_pool):
                false_symbols = random.sample(false_pool, false_choices)
            else:
                false_symbols = [random.choice(false_pool) for _ in range(false_choices)]
            symbols = [correct, *false_symbols]
            random.shuffle(symbols)
            drums.append(symbols)
        time_limit = settings.get("timeLimitSeconds")
        if time_limit is not None:
            try:
                time_limit = int(time_limit)
            except (TypeError, ValueError):
                time_limit = None
            if time_limit is not None:
                time_limit = max(1, min(time_limit, 3600))
        return {"correct_code": correct_code, "drums": drums, "timeLimitSeconds": time_limit}

    def validate_submission(self, session_data: dict | None, sequence: list[str] | None) -> bool:
        """Проверить ответ: sequence == session_data["correct_code"].

        session_data: player_mission.progress["cipher_session"] или None.
        Возврат: bool. Без side-effect'ов.
        """
        if not isinstance(session_data, dict):
            return False
        correct = session_data.get("correct_code")
        if not isinstance(correct, list):
            return False
        return (
            isinstance(sequence, list)
            and len(sequence) == len(correct)
            and all(isinstance(s, str) for s in sequence)
            and sequence == correct
        )


# Реестр: game_type -> handler. Новая мини-игра = новый класс + одна строка здесь.
MINIGAME_HANDLERS: dict[str, MinigameHandler] = {
    "cipher": CipherHandler(),
}


def get_handler(game_type: str) -> MinigameHandler | None:
    """Вернуть handler по game_type или None, если игра не зарегистрирована."""
    return MINIGAME_HANDLERS.get(game_type)
