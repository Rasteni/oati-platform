"""Импорт объектов из CSV/XLSX (SQLite-версия)."""
import io
import logging
from datetime import date, datetime
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from app.models import ControlObject, Inspection
from app.schemas import normalize_status
from app.services.geo import load_districts_cache, find_district_id

log = logging.getLogger(__name__)

COL_ALIASES: dict[str, list[str]] = {
    "lat":       ["lat", "latitude", "широта", "шир", "y"],
    "lon":       ["lon", "lng", "long", "longitude", "долгота", "долг", "x"],
    "name":      ["name", "название", "объект", "наименование", "title", "имя"],
    "status":    ["status", "статус", "состояние"],
    "date":      ["date", "дата", "last_check", "проверка", "последняя_проверка", "last_inspection"],
    "type":      ["type", "тип", "категория", "category", "вид"],
    "address":   ["address", "адрес"],
    "inspector": ["inspector", "инспектор", "ответственный", "responsible"],
    "note":      ["note", "примечание", "комментарий", "description", "описание"],
    "object_id": ["object_id", "id_объекта", "external_id", "идентификатор", "uid"],
}


def _norm(s: Any) -> str:
    return str(s or "").strip().lower().replace(" ", "_")


def _find_col(df_cols: list[str], aliases: list[str]) -> str | None:
    normalized = {_norm(c): c for c in df_cols}
    for a in aliases:
        if a in normalized:
            return normalized[a]
    return None


def _parse_date(v: Any) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 25000 < v < 60000:
        try:
            return (datetime(1899, 12, 30) + pd.Timedelta(days=v)).date()
        except Exception:
            return None
    s = str(v).strip()
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y.%m.%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s, dayfirst=True).date()
    except Exception:
        return None


def _parse_float(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
        return None
    try:
        return float(str(v).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _cell(row, col):
    if col is None:
        return None
    v = row[col]
    if isinstance(v, float) and pd.isna(v):
        return None
    return v


def parse_file(content: bytes, filename: str) -> pd.DataFrame:
    ext = filename.lower().rsplit(".", 1)[-1]
    bio = io.BytesIO(content)
    if ext == "csv":
        for enc in ("utf-8-sig", "utf-8", "cp1251"):
            try:
                bio.seek(0)
                return pd.read_csv(bio, encoding=enc, sep=None, engine="python")
            except (UnicodeDecodeError, pd.errors.ParserError):
                continue
        raise ValueError("Не удалось прочитать CSV")
    elif ext in ("xlsx", "xls"):
        return pd.read_excel(bio)
    else:
        raise ValueError(f"Неподдерживаемый формат: {ext}")


def import_dataframe(db: Session, df: pd.DataFrame) -> dict:
    cols = list(df.columns)
    mapped = {key: _find_col(cols, aliases) for key, aliases in COL_ALIASES.items()}

    if not mapped["lat"] or not mapped["lon"]:
        raise ValueError("Не найдены колонки координат (lat/lon или широта/долгота)")

    has_external_id = mapped["object_id"] is not None
    groups: dict[Any, dict] = {}
    skipped = 0
    geocoded = 0

    # Если геокодинг включён, импортируем модуль лениво (медленно из-за rate-limit)
    from app.services.geocoder import geocode

    for idx, row in df.iterrows():
        lat = _parse_float(_cell(row, mapped["lat"]))
        lon = _parse_float(_cell(row, mapped["lon"]))
        addr_val = _cell(row, mapped["address"])

        # Если нет координат, но есть адрес — пробуем геокодировать
        if (lat is None or lon is None) and addr_val:
            coords = geocode(str(addr_val))
            if coords:
                lat, lon = coords
                geocoded += 1

        if lat is None or lon is None or not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            skipped += 1
            continue

        ext_id = _cell(row, mapped["object_id"]) if has_external_id else None
        key = ext_id if ext_id is not None else f"_row_{idx}"

        status = normalize_status(_cell(row, mapped["status"]))
        d = _parse_date(_cell(row, mapped["date"]))
        inspector = _cell(row, mapped["inspector"])
        note = _cell(row, mapped["note"])
        name_val = _cell(row, mapped["name"])
        type_val = _cell(row, mapped["type"])

        if key not in groups:
            groups[key] = {
                "object": {
                    "name": str(name_val).strip() if name_val else f"Объект {idx+1}",
                    "type": str(type_val).strip() if type_val else None,
                    "address": str(addr_val).strip() if addr_val else None,
                    "lat": lat, "lon": lon,
                    "last_check_date": d, "last_status": status,
                    "last_inspector": str(inspector).strip() if inspector else None,
                    "last_note": str(note).strip() if note else None,
                },
                "inspections": [],
            }
        if d:
            groups[key]["inspections"].append({
                "check_date": d, "status": status,
                "inspector": str(inspector).strip() if inspector else None,
                "note": str(note).strip() if note else None,
            })
            g = groups[key]["object"]
            if not g["last_check_date"] or d > g["last_check_date"]:
                g["last_check_date"] = d
                g["last_status"] = status
                g["last_inspector"] = str(inspector).strip() if inspector else None
                g["last_note"] = str(note).strip() if note else None

    # Загружаем кэш округов для привязки
    districts_cache = load_districts_cache(db)

    imported_objects = 0
    imported_inspections = 0
    new_obj_ids = []
    for g in groups.values():
        o = g["object"]
        district_id = find_district_id(o["lat"], o["lon"], districts_cache)
        obj = ControlObject(
            name=o["name"], type=o["type"],
            status=o["last_status"], address=o["address"],
            inspector=o["last_inspector"], note=o["last_note"],
            last_check_date=o["last_check_date"],
            lat=o["lat"], lon=o["lon"],
            district_id=district_id,
        )
        db.add(obj)
        db.flush()
        imported_objects += 1
        new_obj_ids.append(obj.id)

        for insp in g["inspections"]:
            db.add(Inspection(
                object_id=obj.id, check_date=insp["check_date"],
                status=insp["status"], inspector=insp["inspector"], note=insp["note"],
            ))
            imported_inspections += 1

        if imported_objects % 200 == 0:
            db.commit()

    db.commit()

    log.info("Imported %d objects + %d inspections, geocoded %d",
             imported_objects, imported_inspections, geocoded)
    return {
        "imported": imported_objects,
        "inspections": imported_inspections,
        "skipped": skipped,
        "geocoded": geocoded,
        "errors": [],
    }
