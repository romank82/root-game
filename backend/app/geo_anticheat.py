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

# Пороги — пока константы; перенос в CMS в отдельном шаге.
ANTICHEAT_MAX_SPEED_KMH = 120  # TODO(8.9.e): CMS geo.anticheat_max_speed_kmh
ANTICHEAT_MIN_ELAPSED_SECONDS = 5  # TODO(8.9.e): CMS geo.anticheat_min_elapsed_seconds
ANTICHEAT_ACCURACY_MIN_METERS = 3  # TODO(8.9.e): CMS geo.anticheat_accuracy_min_meters
# Sprint 8.9.b: режим записи сигналов. off — не писать, flag — писать
# PlayerEvent/audit/progress без блокировки, enforce — отдельный шаг (8.9.e).
ANTICHEAT_MODE = "flag"  # TODO(8.9.e): CMS geo.anticheat_mode (off|flag|enforce)


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
) -> dict | None:
    """Вернуть velocity-сигнал, если скорость выше порога; иначе None.

    Tolerant: нет scan_at или elapsed < ANTICHEAT_MIN_ELAPSED_SECONDS
    (включая отрицательный elapsed при рассинхроне часов) -> None.
    """
    if scan_at is None:
        return None

    elapsed = _elapsed_seconds(generated_at, scan_at)
    if elapsed < ANTICHEAT_MIN_ELAPSED_SECONDS:
        return None

    distance_km = calculate_distance_km(
        spawn_latitude,
        spawn_longitude,
        current_latitude,
        current_longitude,
    )
    speed_kmh = distance_km / (elapsed / 3600.0)
    if speed_kmh <= ANTICHEAT_MAX_SPEED_KMH:
        return None

    return {
        "signal": "velocity",
        "speedKmh": round(speed_kmh, 1),
        "distanceKm": round(distance_km, 3),
        "elapsedSeconds": int(elapsed),
        "thresholdKmh": ANTICHEAT_MAX_SPEED_KMH,
    }


def evaluate_accuracy(*, accuracy_meters: float | None) -> dict | None:
    """Вернуть accuracy-сигнал при аномально «идеальной» точности GPS.

    accuracy_meters is None (не передан) -> None. Точность не выше
    ANTICHEAT_ACCURACY_MIN_METERS считается подозрительно идеальной.
    """
    if accuracy_meters is None:
        return None
    if accuracy_meters > ANTICHEAT_ACCURACY_MIN_METERS:
        return None

    return {
        "signal": "accuracy",
        "accuracyMeters": float(accuracy_meters),
        "thresholdMeters": ANTICHEAT_ACCURACY_MIN_METERS,
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