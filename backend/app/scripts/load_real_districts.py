"""
Загрузка точных границ административных округов Москвы из OpenStreetMap
через Overpass API. SQLite-версия — пишет polygon как JSON в таблицу districts.

Запуск из корня проекта:
    .venv/bin/python -m app.scripts.load_real_districts
или (Windows):
    .venv\\Scripts\\python -m app.scripts.load_real_districts

Требует интернет-доступ к https://overpass-api.de
"""
import json
import logging
import sys
import urllib.request
import urllib.parse
from pathlib import Path

# Чтобы запускалось из любого места
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from app.database import SessionLocal
from app.models import District, ControlObject
from app.services.geo import find_district_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

OVERPASS_QUERY = """
[out:json][timeout:60];
area["name"="Москва"]["admin_level"="4"]->.moscow;
(
  relation["admin_level"="5"](area.moscow);
);
out geom;
"""

CODE_MAP = {
    "Центральный административный округ": "ЦАО",
    "Северный административный округ": "САО",
    "Северо-Восточный административный округ": "СВАО",
    "Восточный административный округ": "ВАО",
    "Юго-Восточный административный округ": "ЮВАО",
    "Южный административный округ": "ЮАО",
    "Юго-Западный административный округ": "ЮЗАО",
    "Западный административный округ": "ЗАО",
    "Северо-Западный административный округ": "СЗАО",
    "Зеленоградский административный округ": "ЗелАО",
    "Троицкий административный округ": "ТАО",
    "Новомосковский административный округ": "НАО",
}


def fetch_overpass() -> dict:
    log.info("Запрос к Overpass API (это займёт ~30-60 секунд)...")
    data = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode()
    req = urllib.request.Request(OVERPASS_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def assemble_ring(segments: list[list[tuple]]) -> tuple[list[tuple] | None, list[list[tuple]]]:
    """Собирает одно замкнутое кольцо из произвольно упорядоченных сегментов."""
    if not segments:
        return None, []
    ring = list(segments[0])
    remaining = list(segments[1:])
    changed = True
    while changed and remaining:
        changed = False
        for i, seg in enumerate(remaining):
            if seg[0] == ring[-1]:
                ring.extend(seg[1:])
                remaining.pop(i); changed = True; break
            if seg[-1] == ring[-1]:
                ring.extend(list(reversed(seg))[1:])
                remaining.pop(i); changed = True; break
            if seg[-1] == ring[0]:
                ring = list(seg) + ring[1:]
                remaining.pop(i); changed = True; break
            if seg[0] == ring[0]:
                ring = list(reversed(seg)) + ring[1:]
                remaining.pop(i); changed = True; break
        if ring[0] == ring[-1]:
            break
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring, remaining


def relation_to_polygon(relation: dict) -> list[list[float]] | None:
    """Собирает самое большое внешнее кольцо как [[lon, lat], ...]."""
    members = relation.get("members", [])
    outer_segs = []
    for m in members:
        if m.get("type") != "way" or m.get("role") != "outer":
            continue
        geometry = m.get("geometry", [])
        if len(geometry) < 2:
            continue
        seg = [(g["lon"], g["lat"]) for g in geometry]
        outer_segs.append(seg)

    rings = []
    while outer_segs:
        ring, outer_segs = assemble_ring(outer_segs)
        if ring and len(ring) >= 4:
            rings.append(ring)

    if not rings:
        return None
    # Берём кольцо с наибольшим количеством точек (обычно — реальная внешняя граница)
    main_ring = max(rings, key=len)
    return [[float(lon), float(lat)] for lon, lat in main_ring]


def load_districts():
    data = fetch_overpass()
    elements = data.get("elements", [])
    log.info("Получено %d relations", len(elements))

    db = SessionLocal()
    try:
        db.query(District).delete()
        db.commit()

        loaded = 0
        for el in elements:
            if el.get("type") != "relation":
                continue
            tags = el.get("tags", {})
            full_name = tags.get("name", "")
            code = CODE_MAP.get(full_name)
            if not code:
                log.warning("Неизвестный округ, пропускаю: %s", full_name)
                continue

            short_name = full_name.replace(" административный округ", "")
            polygon = relation_to_polygon(el)
            if not polygon:
                log.warning("Не удалось собрать геометрию: %s", full_name)
                continue

            district = District(
                code=code, name=short_name, full_name=full_name,
                polygon_json=json.dumps(polygon),
            )
            db.add(district)
            loaded += 1
            log.info("  + %s (%d точек)", full_name, len(polygon))

        db.commit()

        # Пересчёт привязки всех объектов через ray-casting
        log.info("Пересчёт привязки объектов к округам...")
        from app.services.geo import load_districts_cache
        cache = load_districts_cache(db)
        if cache:
            objs = db.query(ControlObject).all()
            updated = 0
            for o in objs:
                new_id = find_district_id(o.lat, o.lon, cache)
                if o.district_id != new_id:
                    o.district_id = new_id
                    updated += 1
            db.commit()
            log.info("Обновлено привязок: %d из %d объектов", updated, len(objs))

        log.info("Готово. Загружено %d округов.", loaded)
    except Exception as e:
        db.rollback()
        log.error("Ошибка: %s", e)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    load_districts()
