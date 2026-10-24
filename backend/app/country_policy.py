"""Хелперы политик по странам (13.2-b): чтение и проверки CountryPolicy.

Семантика (13.1/13.2-a): одна политика на страну, отсутствие записи =
allowed. country_code у игрока может быть NULL (профиль без определения
страны) — трактуется как allowed (пропуск).

- get_country_policy  — запись политики для страны (None, если country
  пустой/нет записи).
- is_blocked          — blocked -> True; NULL/нет записи -> False.
- is_feature_restricted — restricted И feature в restricted_features
  -> True; иначе False.

Применение:
- 13.2-b-1 — is_blocked в auth-гейте входа (get_current_player_id, main.py);
- 13.2-b-2 — is_feature_restricted в transfer/mission/team (отдельный шаг).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CountryPolicy


def get_country_policy(session: Session, country_code: str | None) -> CountryPolicy | None:
    """Политика для страны (None, если country=NULL или записи нет)."""
    if not country_code:
        return None
    return session.scalar(
        select(CountryPolicy).where(
            CountryPolicy.country_code == country_code.upper()
        )
    )


def is_blocked(session: Session, country_code: str | None) -> bool:
    """blocked → True; NULL/нет записи → False (allowed)."""
    policy = get_country_policy(session, country_code)
    return policy is not None and policy.policy == "blocked"


def is_feature_restricted(session: Session, country_code: str | None, feature: str) -> bool:
    """restricted + feature в restricted_features → True; иначе False."""
    policy = get_country_policy(session, country_code)
    if policy is None or policy.policy != "restricted":
        return False
    features = policy.restricted_features or []
    return feature in features