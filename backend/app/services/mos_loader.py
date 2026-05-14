"""
Загрузка данных из API открытых данных Москвы (apidata.mos.ru).

Документация: https://apidata.mos.ru/Docs

Особенности API:
- Базовый URL: https://apidata.mos.ru/v1/
- Для большинства запросов нужен api_key (бесплатный, в профиле data.mos.ru)
- Лимит выдачи: 500 записей за запрос, нужна пагинация через $top / $skip
- Геоданные возвращаются в формате GeoJSON через /features
"""
import logging
import json
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

BASE_URL = "https://apidata.mos.ru/v1"

# Известные датасеты с геопривязкой, относящиеся к работе ОАТИ.
# Имена и ID могут меняться — это пресеты для быстрого выбора.
# Реальные ID лучше проверить на data.mos.ru/opendata
KNOWN_DATASETS = {
    "619": {
        "name": "Дворовые территории",
        "description": "Дворовые территории по округам Москвы",
        "status_field": None,  # статуса в исходных данных нет — будет 'unknown'
    },
    "623": {
        "name": "Контейнерные площадки",
        "description": "Площадки сбора ТКО",
        "status_field": None,
    },
    "60562": {
        "name": "Многоквартирные дома",
        "description": "Жилые дома Москвы",
        "status_field": None,
    },
    "1786": {
        "name": "Ордера на производство работ",
        "description": "Действующие ордера ОАТИ",
        "status_field": "Status",
    },
}


def fetch_dataset(dataset_id: str, api_key: str | None = None, limit: int = 500) -> list[dict]:
    """
    Загружает датасет из data.mos.ru. Использует постраничную выгрузку.
    Возвращает список словарей с полями объектов.
    """
    all_rows = []
    skip = 0
    page_size = min(500, limit)

    while True:
        params = {
            "$top": page_size,
            "$skip": skip,
        }
        if api_key:
            params["api_key"] = api_key
        url = f"{BASE_URL}/datasets/{dataset_id}/features?{urllib.parse.urlencode(params)}"
        log.info("Запрос: %s", url.replace(api_key or "X", "***") if api_key else url)

        req = urllib.request.Request(url, headers={"User-Agent": "OATI-Geoanalytics/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        features = data.get("features", [])
        if not features:
            break
        all_rows.extend(features)
        skip += len(features)
        if len(features) < page_size or len(all_rows) >= limit:
            break

    return all_rows


def features_to_objects(features: list[dict], dataset_meta: dict | None = None) -> list[dict]:
    """
    Преобразует GeoJSON-features в формат, понятный нашему импортёру.
    Извлекает координаты и пытается собрать осмысленные поля.
    """
    result = []
    for f in features:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates")
        if not coords:
            continue

        # Точка или центроид полигона
        if geom.get("type") == "Point":
            lon, lat = coords[0], coords[1]
        elif geom.get("type") in ("Polygon", "MultiPolygon"):
            # Берём центроид первого кольца
            ring = coords[0] if geom["type"] == "Polygon" else coords[0][0]
            if not ring:
                continue
            lat = sum(p[1] for p in ring) / len(ring)
            lon = sum(p[0] for p in ring) / len(ring)
        else:
            continue

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            continue

        props = f.get("properties") or {}
        attrs = props.get("Attributes") or props

        # Универсальные эвристики для извлечения полезных полей
        name = (attrs.get("Name") or attrs.get("ObjectName")
                or attrs.get("global_id") or "Объект")
        address = (attrs.get("Address") or attrs.get("FullAddress")
                   or attrs.get("AddressOfStaying"))
        type_val = (attrs.get("Type") or attrs.get("Category")
                    or (dataset_meta or {}).get("name"))

        # Статус — если в датасете есть подходящее поле, маппим
        status_field = (dataset_meta or {}).get("status_field")
        status = None
        if status_field and status_field in attrs:
            status = attrs[status_field]

        result.append({
            "name": str(name)[:500] if name else "Объект",
            "lat": lat,
            "lon": lon,
            "status": status or "норма",  # по умолчанию
            "address": str(address)[:500] if address else None,
            "type": str(type_val)[:255] if type_val else None,
            "note": f"Из данных data.mos.ru, dataset {(dataset_meta or {}).get('name', '')}",
        })

    return result


def load_dataset(dataset_id: str, api_key: str | None = None, limit: int = 500) -> list[dict]:
    """High-level: грузим датасет и приводим к формату импортёра."""
    meta = KNOWN_DATASETS.get(dataset_id, {"name": f"Dataset {dataset_id}"})
    log.info("Загружаю датасет %s (%s)", dataset_id, meta.get("name"))
    features = fetch_dataset(dataset_id, api_key=api_key, limit=limit)
    log.info("Получено %d features", len(features))
    return features_to_objects(features, meta)
