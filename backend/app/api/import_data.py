"""API импорта данных (SQLite-версия)."""
import random
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import ControlObject, Inspection
from app.schemas import ImportResult, normalize_status
from app.services.importer import parse_file, import_dataframe
from app.services.geo import load_districts_cache, find_district_id

router = APIRouter(prefix="/api/import", tags=["import"])
settings = get_settings()


@router.post("/file", response_model=ImportResult)
async def import_file(
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
    replace: bool = False,
):
    content = await file.read()
    if len(content) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"Файл больше {settings.MAX_UPLOAD_MB} МБ")
    try:
        df = parse_file(content, file.filename)
    except Exception as e:
        raise HTTPException(400, f"Ошибка парсинга: {e}")
    if replace:
        db.query(ControlObject).delete()
        db.commit()
    try:
        result = import_dataframe(db, df)
    except ValueError as e:
        raise HTTPException(400, str(e))
    geocoded_part = f" · геокодировано {result.get('geocoded', 0)}" if result.get('geocoded') else ""
    return {
        **result,
        "message": f"Импортировано {result['imported']} объектов · "
                   f"{result['inspections']} проверок · пропущено {result['skipped']}{geocoded_part}",
    }


@router.post("/demo", response_model=ImportResult)
def generate_demo(
    db: Annotated[Session, Depends(get_db)],
    count: int = 500,
    replace: bool = False,
):
    if replace:
        db.query(ControlObject).delete()
        db.commit()

    types = [
        "Контейнерная площадка", "Дворовая территория", "Объект торговли",
        "Стройплощадка", "Газон", "Парковка", "МАФ", "Уличная мебель",
    ]
    statuses_pool = (
        ["норма"] * 5 + ["замечание"] * 3 +
        ["нарушение"] * 2 + ["критическое"] * 1 + ["на проверке"] * 1
    )
    inspectors = ["Иванов А.Н.", "Петров С.В.", "Сидорова О.М.",
                  "Кузнецов Д.Е.", "Морозова Е.А.", "Волков И.П."]
    streets = ["Тверская", "Арбат", "Лубянка", "Якиманка", "Пресня",
               "Кутузовский пр.", "Ленинский пр.", "Профсоюзная"]
    notes_pool = [None, "Без замечаний", "Повреждение покрытия",
                  "Несанкционированный навал", "Требуется уборка",
                  "Демонтаж в работе", "Плановая проверка"]

    center_lat, center_lon = 55.7558, 37.6173
    districts_cache = load_districts_cache(db)
    total_inspections = 0

    for i in range(count):
        lat = center_lat + (random.random() - 0.5) * 0.45
        lon = center_lon + (random.random() - 0.5) * 0.65
        district_id = find_district_id(lat, lon, districts_cache)

        num_checks = random.randint(1, 4)
        check_dates = sorted([
            date.today() - timedelta(days=random.randint(0, 365))
            for _ in range(num_checks)
        ])
        check_records = []
        for cd in check_dates:
            check_records.append({
                "check_date": cd,
                "status": normalize_status(random.choice(statuses_pool)),
                "inspector": random.choice(inspectors),
                "note": random.choice(notes_pool),
            })

        last = check_records[-1]
        obj = ControlObject(
            name=f"Объект ОАТИ #{1000 + i}",
            type=random.choice(types),
            status=last["status"],
            address=f"ул. {random.choice(streets)}, д.{random.randint(1, 199)}",
            inspector=last["inspector"], note=last["note"],
            last_check_date=last["check_date"],
            lat=lat, lon=lon, district_id=district_id,
        )
        db.add(obj)
        db.flush()
        for rec in check_records:
            db.add(Inspection(
                object_id=obj.id,
                check_date=rec["check_date"], status=rec["status"],
                inspector=rec["inspector"], note=rec["note"],
            ))
            total_inspections += 1

        if (i + 1) % 200 == 0:
            db.commit()
    db.commit()

    return {
        "imported": count, "inspections": total_inspections,
        "skipped": 0, "errors": [],
        "message": f"Сгенерировано {count} демо-объектов с {total_inspections} проверками",
    }


@router.get("/template")
def csv_template():
    from fastapi.responses import Response
    csv = (
        "name,lat,lon,status,date,type,address,inspector,note\n"
        "Контейнерная площадка №14,55.7558,37.6173,норма,2025-09-15,Санитарное состояние,ул. Тверская д.1,Иванов А.Н.,Без замечаний\n"
        "Дворовая территория,55.7700,37.6500,замечание,2025-08-20,Благоустройство,ул. Большая Никитская д.5,Петров С.В.,Повреждение покрытия\n"
        "Объект торговли,55.7400,37.6000,нарушение,2025-07-10,Несанкционированная торговля,Манежная пл.,Сидорова О.М.,Требуется демонтаж\n"
    )
    return Response(
        content="\ufeff" + csv,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="oati_template.csv"'},
    )


@router.get("/mos-datasets")
def list_mos_datasets():
    """Список известных датасетов с data.mos.ru, доступных для загрузки."""
    from app.services.mos_loader import KNOWN_DATASETS
    return [
        {"id": did, **meta}
        for did, meta in KNOWN_DATASETS.items()
    ]


@router.post("/mos", response_model=ImportResult)
def import_from_mos(
    db: Annotated[Session, Depends(get_db)],
    dataset_id: str,
    api_key: str | None = None,
    limit: int = 500,
    replace: bool = False,
):
    """
    Загрузить датасет с data.mos.ru.

    dataset_id — числовой ID датасета (например 619 для дворовых территорий).
    api_key — опционально, для большинства датасетов работает и без ключа,
              но с лимитами по частоте. Бесплатный ключ в профиле data.mos.ru.
    """
    from app.services.mos_loader import load_dataset
    from app.services.geo import load_districts_cache, find_district_id

    try:
        rows = load_dataset(dataset_id, api_key=api_key, limit=limit)
    except Exception as e:
        raise HTTPException(502, f"Ошибка загрузки с data.mos.ru: {e}")

    if not rows:
        return {
            "imported": 0, "inspections": 0, "skipped": 0, "geocoded": 0,
            "errors": [], "message": "Датасет пуст или не содержит геоданных",
        }

    if replace:
        db.query(ControlObject).delete()
        db.commit()

    cache = load_districts_cache(db)
    imported = 0
    for r in rows:
        district_id = find_district_id(r["lat"], r["lon"], cache)
        obj = ControlObject(
            name=r["name"], lat=r["lat"], lon=r["lon"],
            status=normalize_status(r.get("status")),
            address=r.get("address"), type=r.get("type"),
            note=r.get("note"),
            district_id=district_id,
        )
        db.add(obj)
        imported += 1
        if imported % 200 == 0:
            db.commit()
    db.commit()

    return {
        "imported": imported, "inspections": 0,
        "skipped": 0, "geocoded": 0, "errors": [],
        "message": f"Импортировано {imported} объектов из data.mos.ru (датасет {dataset_id})",
    }
