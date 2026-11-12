"""Sprint 8.9: server-side anti-cheat signals (velocity, accuracy anomaly).

Чистые функции без БД и побочных эффектов: считают сигналы подозрительного
поведения игрока (слишком быстрое перемещение между spawn и scan, аномально
«идеальная» accuracy GPS). Подключение к mission_engine / admin_audit_log /
PlayerEvent — отдельный шаг (8.9.b), здесь только математика и форма сигнала.

См. docs/roadmap-detailed.md («Спринт 8.9. Античит»).

Расстояние считается тем же способом, что и в team_missions_service
(join-proximity): haversine через ``geo_intel_offline.calculate_distance_km``.
Координаты в сигналы НЕ попадают — только производные числа (скорость,
расстояние, elapsed) и идентификаторы (см. build_signal_payload).
"""

from __future__ import annotations

from datetime import datetime, timezone

from geo_intel_offline import calculate_distance_km

# Пороги по умолчанию — константы (зеркало каталога geo.anticheat_*).
# CMS-чтение подключается в 8.9.e-4: вызывающий код передаёт значения из
# настроек, эти константы остаются дефолтами/fallback. Границы значений
# гарантирует каталог (system_settings_catalog), здесь они не валидируются.
ANTICHEAT_MAX_SPEED_KMH = 120
ANTICHEAT_MIN_ELAPSED_SECONDS = 5
ANTICHEAT_ACCURACY_MIN_METERS = 3
# Sprint 8.9.e: режим записи сигналов (default "flag"; off|flag|enforce).
# CMS geo.anticheat_mode читается в 8.9.e-4; здесь только дефолт/fallback.
ANTICHEAT_MODE = "flag"


def _elapsed_seconds(generated_at: datetime, scan_at: datetime) -> float:
    """Разница scan_at - generated_at в секундах (tolerant к naive/aware)."""

    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    return (_aware(scan_at) - _aware(generated_at)).total_seconds()


def evaluate_velocity(
    *,
    spawn_latitude: float,
    spawn_longitude: float,
    generated_at: datetime,
    scan_at: datetime | None,
    current_latitude: float,
    current_longitude: float,
    max_speed_kmh: float = ANTICHEAT_MAX_SPEED_KMH,
    min_elapsed_seconds: float = ANTICHEAT_MIN_ELAPSED_SECONDS,
) -> dict | None:
    """Вернуть velocity-сигнал, если скорость выше порога; иначе None.

    Пороги keyword-only с дефолтами из констант. CMS-переопределение
    (geo.anticheat_max_speed_kmh / geo.anticheat_min_elapsed_seconds)
    передаёт вызывающий код (8.9.e-4); границы здесь не валидируются —
    их гарантирует каталог system_settings_catalog.

    Tolerant: нет scan_at или elapsed < min_elapsed_seconds
    (включая отрицательный elapsed при рассинхроне часов) -> None.
    """
    if scan_at is None:
        return None

    elapsed = _elapsed_seconds(generated_at, scan_at)
    if elapsed < min_elapsed_seconds:
        return None

    distance_km = calculate_distance_km(
        spawn_latitude,
        spawn_longitude,
        current_latitude,
        current_longitude,
    )
    speed_kmh = distance_km / (elapsed / 3600.0)
    if speed_kmh <= max_speed_kmh:
        return None

    return {
        "signal": "velocity",
        "speedKmh": round(speed_kmh, 1),
        "distanceKm": round(distance_km, 3),
        "elapsedSeconds": int(elapsed),
        "thresholdKmh": max_speed_kmh,
    }


def evaluate_accuracy(
    *,
    accuracy_meters: float | None,
    min_accuracy_meters: float = ANTICHEAT_ACCURACY_MIN_METERS,
) -> dict | None:
    """Вернуть accuracy-сигнал при аномально «идеальной» точности GPS.

    Порог min_accuracy_meters keyword-only с дефолтом из константы;
    CMS-переопределение (geo.anticheat_accuracy_min_meters) передаёт
    вызывающий код (8.9.e-4). Границы гарантирует каталог.

    accuracy_meters is None (не передан) -> None. Точность не выше
    min_accuracy_meters считается подозрительно идеальной.
    """
    if accuracy_meters is None:
        return None
    if accuracy_meters > min_accuracy_meters:
        return None

    return {
        "signal": "accuracy",
        "accuracyMeters": float(accuracy_meters),
        "thresholdMeters": min_accuracy_meters,
    }


def build_signal_payload(
    *,
    mission_id: str,
    zone_id: str,
    signals: list[dict],
) -> dict:
    """Собрать безопасный payload сигналов: только ids и производные числа.

    Без latitude/longitude и любых сырых координат (контракт 8.5/security):
    сигналы уже содержат только производные значения.
    """
    return {
        "missionId": mission_id,
        "zoneId": zone_id,
        "signals": signals,
    }