"""
Геофункции для SQLite-версии. Заменяют функционал PostGIS:
- point_in_polygon — ray-casting алгоритм для ST_Within
- assign_districts — пересчёт привязки всех объектов к округам
"""
import json
import logging
from typing import Iterable

from sqlalchemy.orm import Session

from app.models import District, ControlObject

log = logging.getLogger(__name__)


def point_in_polygon(lon: float, lat: float, polygon: list[list[float]]) -> bool:
    """Ray-casting. polygon — список [[lon, lat], ...]."""
    inside = False
    n = len(polygon)
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i][0], polygon[i][1]
        xj, yj = polygon[j][0], polygon[j][1]
        if ((yi > lat) != (yj > lat)) and (lon < (xj - xi) * (lat - yi) / (yj - yi + 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def find_district_id(lat: float, lon: float, districts_cache: list[tuple[int, list]]) -> int | None:
    """districts_cache — список (district_id, polygon)."""
    for did, poly in districts_cache:
        if point_in_polygon(lon, lat, poly):
            return did
    return None


def load_districts_cache(db: Session) -> list[tuple[int, list]]:
    """Загружает [{id, polygon}] из БД для быстрых проверок."""
    rows = db.query(District.id, District.polygon_json).all()
    return [(r.id, json.loads(r.polygon_json)) for r in rows]


def assign_districts(db: Session, object_ids: Iterable[int] | None = None) -> int:
    """
    Пересчитывает district_id для объектов.
    object_ids=None — для всех объектов с district_id IS NULL.
    """
    cache = load_districts_cache(db)
    if not cache:
        return 0

    q = db.query(ControlObject)
    if object_ids is not None:
        q = q.filter(ControlObject.id.in_(list(object_ids)))
    else:
        q = q.filter(ControlObject.district_id.is_(None))

    updated = 0
    for obj in q.all():
        did = find_district_id(obj.lat, obj.lon, cache)
        if did is not None:
            obj.district_id = did
            updated += 1
    db.commit()
    return updated


def bbox_contains(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    """bbox = (min_lon, min_lat, max_lon, max_lat)"""
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
