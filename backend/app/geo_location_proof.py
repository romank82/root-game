"""Общие гео-примитивы для team и solo (Sprint 8.5-1).

Модуль не хранит и не возвращает сырые координаты: в БД остаётся только
проекция результата проверки (`LocationProof`: provider, status, zone_id,
issued_at, expires_at). См. docs/geo-team-mission-contract.md и
docs/solo-mission-runtime-policy-contract.md.

Импортирует только stdlib, SQLAlchemy и модель LocationProof — без
team_missions_service и mission_engine, чтобы не создавать циклический импорт.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.geo_team_runtime_models import LocationProof

# Dev-режим сам выступает trusted verifier; для prod появится внешний verifier.
# Эти константы — единственное место смены провайдера при переходе на prod.
DEV_LOCATION_PROOF_PROVIDER = "dev_mock"
LOCATION_PROOF_STATUS_VERIFIED = "verified"
LOCATION_PROOF_STATUS_REJECTED = "rejected"
SUPPORTED_ZONE_TYPES = frozenset({"radius"})  # polygon/poi — позже


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_location_proof_id() -> str:
    return f"location-proof-{uuid4().hex}"


def is_inside_zone(zone: Any, latitude: float, longitude: float) -> bool:
    """Dev check: is the point inside a radius zone (equirectangular approximation).

    Single spot to swap an external trusted verifier in prod.
    """
    if zone.zone_type != "radius":
        return False

    if zone.latitude is None or zone.longitude is None or zone.radius_meters is None:
        return False

    meters_per_degree = 111_320.0
    d_lat_m = (zone.latitude - latitude) * meters_per_degree
    d_lon_m = (zone.longitude - longitude) * meters_per_degree
    return (
        d_lat_m * d_lat_m + d_lon_m * d_lon_m
        <= zone.radius_meters * zone.radius_meters
    )


def create_location_proof(
    session: Session,
    *,
    player_id: str,
    zone_id: str,
    verified: bool,
    freshness_seconds: int,
) -> LocationProof:
    """Записать проекцию результата проверки присутствия (без координат).

    `verified` — уже вычисленный результат (`is_inside_zone` в dev-режиме или
    внешний trusted verifier). Срок годности задаётся `freshness_seconds`
    (CMS-политика), он же превращается в `expires_at`.
    """
    now = _utcnow()
    proof = LocationProof(
        id=_new_location_proof_id(),
        player_id=player_id,
        provider=DEV_LOCATION_PROOF_PROVIDER,
        status=(
            LOCATION_PROOF_STATUS_VERIFIED
            if verified
            else LOCATION_PROOF_STATUS_REJECTED
        ),
        zone_id=zone_id,
        verifier_reference=None,
        issued_at=now,
        expires_at=now + timedelta(seconds=freshness_seconds),
    )
    session.add(proof)
    session.flush()
    return proof


def has_fresh_verified_proof(
    session: Session,
    *,
    player_id: str,
    zone_id: str,
) -> bool:
    """Есть ли у игрока свежий verified LocationProof по этой зоне.

    Только SELECT, без записи. Срок годности уже «зашит» в `expires_at` при
    создании proof, поэтому отдельная проверка freshness не нужна.
    """
    latest_proof = session.scalar(
        select(LocationProof)
        .where(
            LocationProof.player_id == player_id,
            LocationProof.status == LOCATION_PROOF_STATUS_VERIFIED,
            LocationProof.zone_id == zone_id,
            LocationProof.expires_at > _utcnow(),
        )
        .order_by(LocationProof.issued_at.desc())
        .limit(1)
    )
    return latest_proof is not None
