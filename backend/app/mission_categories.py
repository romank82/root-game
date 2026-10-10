"""Реестр категорий участия в миссии (mission_category).

Категория определяет ФЛОУ прохождения (кто участвует, как начисляется
награда). Формат решения — отдельное поле mission_type.

Легко расширяется: добавить запись в MISSION_CATEGORIES + 1 миграцию
для backfill при необходимости.
"""

MISSION_CATEGORY_SOLO = "solo"
MISSION_CATEGORY_TEAM = "team"
MISSION_CATEGORY_RACE = "race"          # задел на будущее
MISSION_CATEGORY_COOP = "co-op"         # задел на будущее

MISSION_CATEGORIES = {
    MISSION_CATEGORY_SOLO: {
        "title": "Solo (один игрок)",
        "description": "Игрок проходит миссию один. Entry policy через runtime policy.",
        "requires_team": False,
        "first_to_complete_wins": False,
    },
    MISSION_CATEGORY_TEAM: {
        "title": "Team (команда)",
        "description": "Команда активирует миссию в геозоне, каждый проходит индивидуально.",
        "requires_team": True,
        "first_to_complete_wins": False,
    },
    MISSION_CATEGORY_RACE: {
        "title": "Race (гонка, первый победил)",
        "description": "Несколько игроков берут одну миссию. Побеждает первый выполнивший.",
        "requires_team": False,
        "first_to_complete_wins": True,
    },
    MISSION_CATEGORY_COOP: {
        "title": "Co-op (кооператив)",
        "description": "Несколько игроков, победа общая при завершении всеми.",
        "requires_team": True,
        "first_to_complete_wins": False,
    },
}


def get_category(code: str) -> dict | None:
    return MISSION_CATEGORIES.get(code)


def is_valid_category(code: str) -> bool:
    return code in MISSION_CATEGORIES