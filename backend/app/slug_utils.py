"""Общие slug-хелперы для админ-роутеров (Sprint 8.25.1).

Были дословно одинаковыми copy-paste копиями в admin_seasons.py,
admin_chapters.py, admin_story_nodes.py (и _normalize_slug/_SLUG_PATTERN
дополнительно в admin_segments.py, admin_missions.py, admin_ar_objects.py,
admin_geo_zones.py, admin_reward_pools.py). Здесь — единый источник.

Состав:
- SLUG_PATTERN — контракт slug-идентификаторов;
- _CYRILLIC_TO_LATIN — транслитерация кириллицы для автогенерации;
- _normalize_slug — нормализация (strip/lower) + валидация по паттерну;
- _slugify_title — генерация валидного slug из русскоязычного title;
- unique_slug — авто-суффикс (-2, -3, ...) при коллизиях уникальности
  (используется далее в автогенерации для Segment/Mission).

Модуль зависит только от re и fastapi (HTTPException) — не импортирует
app.models/app.db и admin-роутеров, циклических импортов не образует.
"""
from __future__ import annotations

import re
from typing import Callable, TypeVar

from fastapi import HTTPException, status

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:[a-z0-9-]{0,126}[a-z0-9])?$")

# Транслитерация кириллицы для автогенерации slug из русскоязычного title.
_CYRILLIC_TO_LATIN = {
    ord("а"): "a", ord("б"): "b", ord("в"): "v", ord("г"): "g", ord("д"): "d",
    ord("е"): "e", ord("ё"): "e", ord("ж"): "zh", ord("з"): "z", ord("и"): "i",
    ord("й"): "y", ord("к"): "k", ord("л"): "l", ord("м"): "m", ord("н"): "n",
    ord("о"): "o", ord("п"): "p", ord("р"): "r", ord("с"): "s", ord("т"): "t",
    ord("у"): "u", ord("ф"): "f", ord("х"): "kh", ord("ц"): "ts", ord("ч"): "ch",
    ord("ш"): "sh", ord("щ"): "sch", ord("ъ"): "", ord("ы"): "y", ord("ь"): "",
    ord("э"): "e", ord("ю"): "yu", ord("я"): "ya",
}


def _normalize_slug(value: str) -> str:
    slug = value.strip().lower()

    if not SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "slug должен содержать строчные латинские буквы, цифры и дефисы; "
                "длина — от 3 до 128 символов."
            ),
        )

    return slug


def _slugify_title(title: str) -> str:
    """Генерирует валидный slug из title (транслитерация + дефисы)."""
    candidate = title.lower().translate(_CYRILLIC_TO_LATIN)
    candidate = re.sub(r"[^a-z0-9]+", "-", candidate).strip("-")

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Не удалось сгенерировать slug из title; передайте slug явно.",
        )

    try:
        return _normalize_slug(candidate)
    except HTTPException as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Из title не удалось сгенерировать корректный slug; "
                "укажите slug явно."
            ),
        ) from exc


_ModelT = TypeVar("_ModelT")


def unique_slug(
    base: str,
    is_taken: Callable[[str], bool],
    *,
    max_attempts: int = 1000,
) -> str:
    """Возвращает base или первый свободный base-2, base-3, ...

    Аргумент is_taken проверяет занятость кандидата в текущей
    транзакции (см. паттерн 409-проверок в админ-роутерах).
    Если все варианты заняты (до лимита max_attempts) — 422
    «Не удалось сгенерировать уникальный slug; укажите slug явно.».
    """
    candidate = base
    counter = 2
    while is_taken(candidate):
        candidate = f"{base}-{counter}"
        counter += 1
        if counter > max_attempts:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Не удалось сгенерировать уникальный slug; "
                    "укажите slug явно."
                ),
            )
    return candidate
