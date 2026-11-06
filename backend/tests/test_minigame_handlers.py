"""Memory mini-game handler — генерация поля и проверка порядка открытий.

Sprint Memory-2a: чистые unit-тесты хендлера (без БД, без FastAPI) — по
образцу test_content_contract.py. Хендлер не имеет side-effect'ов, поэтому
достаточно прямых вызовов MemoryHandler.
"""

from __future__ import annotations

import unittest

from app.minigame_handlers import MINIGAME_HANDLERS, MemoryHandler, get_handler


class MemoryHandlerTests(unittest.TestCase):
    def test_memory_generate(self) -> None:
        """grid_size=4 → pairs длиной 16, каждый id 1..8 ровно 2 раза."""
        handler = MemoryHandler()
        session = handler.generate_session({"grid_size": 4})

        self.assertEqual(session["grid_size"], 4)
        pairs = session["pairs"]
        self.assertIsInstance(pairs, list)
        self.assertEqual(len(pairs), 16)
        self.assertEqual(sorted(set(pairs)), list(range(1, 9)))
        for card_id in range(1, 9):
            self.assertEqual(pairs.count(card_id), 2)
        self.assertIsNone(session["time_limit_seconds"])

        # Лимит времени из настроек доезжает до сессии.
        with_limit = handler.generate_session(
            {"grid_size": 6, "time_limit_seconds": 90}
        )
        self.assertEqual(with_limit["grid_size"], 6)
        self.assertEqual(len(with_limit["pairs"]), 36)
        self.assertEqual(with_limit["time_limit_seconds"], 90)

        # Нечётная сетка округляется вниз, размер клэмпится в 4..8.
        self.assertEqual(handler.generate_session({"grid_size": 5})["grid_size"], 4)
        self.assertEqual(handler.generate_session({"grid_size": 7})["grid_size"], 6)
        self.assertEqual(handler.generate_session({"grid_size": 99})["grid_size"], 8)
        self.assertEqual(handler.generate_session({})["grid_size"], 4)

        # Хендлер зарегистрирован в реестре по game_type.
        self.assertIs(get_handler("memory"), MINIGAME_HANDLERS["memory"])

    def test_memory_validate(self) -> None:
        """Верный порядок открытий → True, неверная пара / мусор → False."""
        # Фиксированная раскладка: каждая карточка-значение встречается 2 раза.
        pairs = [1, 2, 3, 4, 1, 2, 3, 4, 5, 6, 7, 8, 5, 6, 7, 8]
        session_data = {"grid_size": 4, "pairs": pairs, "time_limit_seconds": 60}
        handler = MemoryHandler()

        # Все 16 карточек открыты по одному разу, каждая пара совпадает.
        good = [0, 4, 1, 5, 2, 6, 3, 7, 8, 12, 9, 13, 10, 14, 11, 15]
        self.assertTrue(handler.validate_submission(session_data, good))
        # Player API объявляет sequence как list[str] — цифровые строки тоже ок.
        self.assertTrue(
            handler.validate_submission(session_data, [str(index) for index in good])
        )

        # Неверная пара: pairs[0]=1 != pairs[1]=2 (остальные пары верные).
        bad_pair = [0, 1, 2, 6, 3, 7, 4, 5, 8, 12, 9, 13, 10, 14, 11, 15]
        self.assertFalse(handler.validate_submission(session_data, bad_pair))

        # Не все карточки открыты / повтор индекса / мусор / нет сессии.
        self.assertFalse(handler.validate_submission(session_data, good[:-2]))
        self.assertFalse(handler.validate_submission(session_data, [0] * 16))
        self.assertFalse(handler.validate_submission(session_data, good[:-1] + ["X"]))
        self.assertFalse(handler.validate_submission(session_data, None))
        self.assertFalse(handler.validate_submission(None, good))


if __name__ == "__main__":
    unittest.main()
