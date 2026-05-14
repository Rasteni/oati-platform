"""
Геокодинг адресов через OpenStreetMap Nominatim.

Бесплатный сервис без API-ключа, но с ограничением: 1 запрос в секунду.
Кэш ответов держим в памяти процесса — на одном датасете повторов мало.
"""
import logging
import time
import urllib.parse
import urllib.request
import json

log = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "OATI-Geoanalytics/1.0"

_cache: dict[str, tuple[float, float] | None] = {}
_last_request_time = 0.0
_RATE_LIMIT_SEC = 1.05  # с запасом


def geocode(address: str, city: str = "Москва") -> tuple[float, float] | None:
    """Возвращает (lat, lon) или None если адрес не распознан."""
    if not address or not isinstance(address, str):
        return None
    address = address.strip()
    if not address:
        return None

    # Кэш
    cache_key = f"{city}|{address}".lower()
    if cache_key in _cache:
        return _cache[cache_key]

    # Rate limit
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < _RATE_LIMIT_SEC:
        time.sleep(_RATE_LIMIT_SEC - elapsed)

    query = f"{address}, {city}, Россия" if city else address
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "accept-language": "ru",
    }
    url = f"{NOMINATIM_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        _last_request_time = time.time()
        if data:
            result = (float(data[0]["lat"]), float(data[0]["lon"]))
            _cache[cache_key] = result
            return result
    except Exception as e:
        log.warning("Geocoding failed for '%s': %s", address, e)

    _cache[cache_key] = None
    return None


def geocode_batch(addresses: list[str], city: str = "Москва", on_progress=None) -> dict[str, tuple[float, float] | None]:
    """Массовый геокодинг с прогрессом."""
    result = {}
    total = len(addresses)
    for i, addr in enumerate(addresses):
        result[addr] = geocode(addr, city)
        if on_progress and i % 10 == 0:
            on_progress(i + 1, total)
    return result
