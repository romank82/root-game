"""Определение страны по координатам (10.0.5).
Офлайн-резолв через geo-intel-offline, порог уверенности 0.7.
Возвращает ISO-2 или None."""
from geo_intel_offline import resolve

GEO_COUNTRY_MIN_CONFIDENCE = 0.7


def resolve_country_or_none(latitude, longitude):
    """Координаты → ISO-2 страна или None (если уверенность ниже порога
    или ошибка резолва). Никогда не бросает исключение."""
    try:
        result = resolve(latitude, longitude)
    except Exception:
        return None
    if result is None or result.iso2 is None:
        return None
    if result.confidence < GEO_COUNTRY_MIN_CONFIDENCE:
        return None
    return result.iso2