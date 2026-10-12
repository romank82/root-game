"""

Генератор случайной точки в радиусе от центра.

Используется в mission_engine при взятии миссии игроком: GPS игрока — центр,
search_radius_m из GeoZone-шаблона — радиус разброса, результат — координаты
центра зоны (radius_meters), которую игрок ищет через сканер.

Не использует IP, не зависит от VPN: только GPS игрока.

Sprint 8.4.a.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# Приблизительная длина одного градуса широты в метрах.
# Совпадает с константой в team_missions_service._is_inside_zone,
# чтобы расчёты были консистентны во всём проекте.
METERS_PER_DEGREE_LATITUDE = 111_320.0


@dataclass(frozen=True)
class SpawnPoint:
    """Результат генерации точки зоны."""
    latitude: float
    longitude: float
    # Фактическое расстояние от центра (в метрах) — для отладки/тестов.
    distance_from_center_m: float


def generate_spawn_point(
    center_latitude: float,
    center_longitude: float,
    search_radius_m: int | float,
    *,
    rng: random.Random | None = None,
) -> SpawnPoint:
    """

    Возвращает случайную точку в радиусе search_radius_m от центра.
    
    Распределение — равномерное по площади круга (использует sqrt-коррекцию,
    чтобы точки не скапливались в центре).
    
    Параметры:
        center_latitude: широта центра (-90..90)
        center_longitude: долгота центра (-180..180)
        search_radius_m: радиус поиска в метрах (> 0)
        rng: опциональный random.Random для тестов (детерминизм)
    
    Raises:
        ValueError: если координаты вне допустимого диапазона или радиус <= 0.
    """
    if not (-90.0 <= center_latitude <= 90.0):
        raise ValueError(f"center_latitude вне диапазона [-90, 90]: {center_latitude}")
    if not (-180.0 <= center_longitude <= 180.0):
        raise ValueError(f"center_longitude вне диапазона [-180, 180]: {center_longitude}")
    if search_radius_m is None or search_radius_m <= 0:
        raise ValueError(f"search_radius_m должен быть > 0: {search_radius_m}")

    source = rng if rng is not None else random

    # Равномерное по площади: r = R * sqrt(u), u ~ Uniform(0, 1).
    # Без sqrt точки скапливались бы у центра (площадь кольца растёт с r).
    u = source.random()
    r_m = math.sqrt(u) * search_radius_m

    # Случайное направление.
    theta = source.random() * 2.0 * math.pi

    # Смещение в метрах по осям восток-запад / север-юг.
    dx_m = r_m * math.cos(theta)  # восток (+), запад (-)
    dy_m = r_m * math.sin(theta)  # север (+), юг (-)

    # Конвертация в градусы.
    d_lat = dy_m / METERS_PER_DEGREE_LATITUDE
    # Длина градуса долготы уменьшается к полюсам: cos(latitude).
    cos_lat = math.cos(math.radians(center_latitude))
    if abs(cos_lat) < 1e-9:
        # На самом полюсе долгота вырождается — используем минимальный шаг.
        d_lng = 0.0
    else:
        d_lng = dx_m / (METERS_PER_DEGREE_LATITUDE * cos_lat)

    spawn_lat = center_latitude + d_lat
    spawn_lng = center_longitude + d_lng

    # Нормализация долготы (переход через ±180).
    if spawn_lng > 180.0:
        spawn_lng -= 360.0
    elif spawn_lng < -180.0:
        spawn_lng += 360.0

    return SpawnPoint(
        latitude=spawn_lat,
        longitude=spawn_lng,
        distance_from_center_m=r_m,
    )