"""Утилиты для работы с datetime (нормализация naive/aware).

SQLite (локальный dev) возвращает naive datetime для колонок
DateTime(timezone=True); PostgreSQL (prod) — aware. Прямое сравнение
naive с aware в Python даёт TypeError. ensure_utc приводит любое
значение к aware-UTC.

Не путать с pydantic-валидацией payload'ов: та отвергает naive
вход (HTTP 422). Эта утилита — для значений, прочитанных из БД.
"""
from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(value: datetime | None) -> datetime | None:
    """Привести naive datetime к aware-UTC; aware не трогает."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value
