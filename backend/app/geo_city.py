"""Определение населённого пункта по координатам (join proximity).

Офлайн-резолв через reverse_geocoder (GeoNames cities1000: ~144k городов
1000+ жителей, 246 стран/территорий). Резолвер — nearest neighbor (KDTree),
поэтому название — БЛИЖАЙШИЙ город, а не «текущий» населённый пункт:
близость игроков проверяется расстоянием (см. team_missions_service), а не
равенством названий. City — справочная информация для UI/логов.

Два важных решения:
- ``mode=1`` (single-threaded KDTree): ``mode=2`` по умолчанию в библиотеке
  работает через multiprocessing — в веб-процессе (uvicorn) недопустимо;
- инстанс ``RGeocoder`` создаётся ОДИН раз на процесс: модульная функция
  ``reverse_geocoder.search()`` пересобирает индекс (CSV 7.7 MB + KDTree)
  при каждом вызове, что для HTTP-запроса неприемлемо.

Стиль ``geo_country.py``: никогда не бросает исключение, возвращает None.
"""
from __future__ import annotations

from functools import lru_cache

from geo_intel_offline import calculate_distance_km

# Максимальное расстояние до ближайшего города, при котором считаем, что
# игрок «в населённом пункте». Дальше — None (океан/пустынная местность),
# чтобы не приписывать игроку город за сотни километров.
CITY_LOOKUP_MAX_DISTANCE_KM = 50.0

# Ленивый синглтон RGeocoder (CSV + KDTree грузятся один раз на процесс).
_geocoder = None


def _get_geocoder():
    """RGeocoder(mode=1) или None, если библиотека/данные недоступны."""
    global _geocoder
    if _geocoder is None:
        try:
            from reverse_geocoder import RGeocoder

            _geocoder = RGeocoder(mode=1, verbose=False)
        except Exception:
            return None
    return _geocoder


@lru_cache(maxsize=2048)
def _resolve_city_cached(latitude: float, longitude: float) -> str | None:
    geocoder = _get_geocoder()
    if geocoder is None:
        return None
    try:
        results = geocoder.query([(latitude, longitude)])
    except Exception:
        return None
    if not results:
        return None

    row = results[0]
    try:
        city_latitude = float(row["lat"])
        city_longitude = float(row["lon"])
    except (KeyError, TypeError, ValueError):
        return None

    try:
        distance_km = calculate_distance_km(
            latitude,
            longitude,
            city_latitude,
            city_longitude,
        )
    except Exception:
        return None
    if distance_km > CITY_LOOKUP_MAX_DISTANCE_KM:
        return None

    name = row.get("name")
    if not name:
        return None
    return str(name)


def resolve_city_or_none(latitude, longitude):
    """Координаты → название ближайшего города (1000+ жителей) или None.

    None: библиотека недоступна, ошибка резолва или ближайший город дальше
    CITY_LOOKUP_MAX_DISTANCE_KM. Исключения не пробрасываются.
    """
    try:
        return _resolve_city_cached(latitude, longitude)
    except Exception:
        return None
