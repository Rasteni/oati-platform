"""API эндпоинты для объектов контроля (SQLite-версия)."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, and_, text
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import ControlObject, District, Inspection
from app.schemas import (
    GeoJSONFeatureCollection, StatsResponse,
    STATUS_LABELS, STATUS_COLORS,
)

router = APIRouter(prefix="/api/objects", tags=["objects"])


def _build_conditions(
    statuses: list[str] | None,
    district_ids: list[int] | None,
    types: list[str] | None,
    date_from: date | None,
    date_to: date | None,
    bbox: str | None,
):
    """Собираем WHERE для запросов."""
    conditions = []
    if statuses:
        conditions.append(ControlObject.status.in_(statuses))
    if district_ids:
        conditions.append(ControlObject.district_id.in_(district_ids))
    if types:
        conditions.append(ControlObject.type.in_(types))
    if date_from:
        conditions.append(ControlObject.last_check_date >= date_from)
    if date_to:
        conditions.append(ControlObject.last_check_date <= date_to)
    if bbox:
        try:
            min_lon, min_lat, max_lon, max_lat = map(float, bbox.split(","))
            conditions.append(ControlObject.lon >= min_lon)
            conditions.append(ControlObject.lon <= max_lon)
            conditions.append(ControlObject.lat >= min_lat)
            conditions.append(ControlObject.lat <= max_lat)
        except (ValueError, TypeError):
            raise HTTPException(400, "Неверный формат bbox")
    return conditions


@router.get("/geojson", response_model=GeoJSONFeatureCollection)
def get_geojson(
    db: Annotated[Session, Depends(get_db)],
    statuses: list[str] | None = Query(None),
    district_ids: list[int] | None = Query(None),
    types: list[str] | None = Query(None),
    date_from: date | None = None,
    date_to: date | None = None,
    bbox: str | None = None,
    limit: int = Query(50000, le=100000),
):
    """Объекты в GeoJSON для отрисовки."""
    conditions = _build_conditions(statuses, district_ids, types, date_from, date_to, bbox)
    stmt = (
        select(
            ControlObject.id, ControlObject.name, ControlObject.type,
            ControlObject.status, ControlObject.address,
            ControlObject.inspector, ControlObject.note,
            ControlObject.last_check_date, ControlObject.lat, ControlObject.lon,
            ControlObject.district_id,
            District.name.label("district_name"),
        )
        .outerjoin(District, ControlObject.district_id == District.id)
        .where(and_(*conditions) if conditions else True)
        .limit(limit)
    )
    rows = db.execute(stmt).all()
    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r.lon, r.lat]},
            "properties": {
                "id": r.id, "name": r.name, "type": r.type,
                "status": r.status,
                "status_label": STATUS_LABELS.get(r.status, r.status),
                "status_color": STATUS_COLORS.get(r.status, "#888"),
                "address": r.address, "inspector": r.inspector, "note": r.note,
                "last_check_date": r.last_check_date.isoformat() if r.last_check_date else None,
                "district_id": r.district_id, "district_name": r.district_name,
            },
        })
    return {"type": "FeatureCollection", "features": features}


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    db: Annotated[Session, Depends(get_db)],
    statuses: list[str] | None = Query(None),
    district_ids: list[int] | None = Query(None),
    types: list[str] | None = Query(None),
    date_from: date | None = None,
    date_to: date | None = None,
    bbox: str | None = None,
):
    total = db.scalar(select(func.count(ControlObject.id))) or 0
    conditions = _build_conditions(statuses, district_ids, types, date_from, date_to, bbox)
    where = and_(*conditions) if conditions else True
    visible = db.scalar(select(func.count(ControlObject.id)).where(where)) or 0

    status_rows = db.execute(
        select(ControlObject.status, func.count(ControlObject.id))
        .group_by(ControlObject.status)
    ).all()
    by_status = {s: c for s, c in status_rows}

    district_rows = db.execute(
        select(
            District.id, District.code, District.name,
            func.count(ControlObject.id).label("cnt")
        )
        .outerjoin(ControlObject, and_(ControlObject.district_id == District.id, where))
        .group_by(District.id, District.code, District.name)
        .order_by(District.code)
    ).all()
    by_district = [
        {"id": r.id, "code": r.code, "name": r.name, "count": r.cnt}
        for r in district_rows
    ]

    type_rows = db.execute(
        select(ControlObject.type, func.count(ControlObject.id))
        .where(ControlObject.type.isnot(None))
        .group_by(ControlObject.type)
        .order_by(func.count(ControlObject.id).desc())
        .limit(20)
    ).all()
    by_type = {t: c for t, c in type_rows if t}

    return {
        "total": total, "visible": visible,
        "by_status": by_status, "by_district": by_district, "by_type": by_type,
    }


@router.get("/cluster")
def get_clusters(
    db: Annotated[Session, Depends(get_db)],
    eps: float = Query(0.003),
    min_points: int = Query(3, ge=1),
    statuses: list[str] | None = Query(None),
    district_ids: list[int] | None = Query(None),
    types: list[str] | None = Query(None),
    date_from: date | None = None,
    date_to: date | None = None,
    bbox: str | None = None,
):
    """
    Простая grid-кластеризация (замена ST_ClusterDBSCAN).
    Разбиваем точки по сетке с шагом eps градусов; каждая ячейка с min_points+
    становится кластером.
    """
    conditions = _build_conditions(statuses, district_ids, types, date_from, date_to, bbox)
    stmt = (
        select(ControlObject.lat, ControlObject.lon, ControlObject.status)
        .where(and_(*conditions) if conditions else True)
    )
    rows = db.execute(stmt).all()

    # Группируем по ячейке
    cells: dict[tuple[int, int], dict] = {}
    for r in rows:
        cx, cy = int(r.lon / eps), int(r.lat / eps)
        key = (cx, cy)
        if key not in cells:
            cells[key] = {"lat_sum": 0.0, "lon_sum": 0.0, "count": 0, "statuses": []}
        cells[key]["lat_sum"] += r.lat
        cells[key]["lon_sum"] += r.lon
        cells[key]["count"] += 1
        cells[key]["statuses"].append(r.status)

    clusters = []
    for key, c in cells.items():
        if c["count"] < min_points:
            continue
        # Преобладающий статус
        from collections import Counter
        top_status = Counter(c["statuses"]).most_common(1)[0][0]
        clusters.append({
            "id": f"{key[0]}_{key[1]}",
            "count": c["count"],
            "lat": c["lat_sum"] / c["count"],
            "lon": c["lon_sum"] / c["count"],
            "top_status": top_status,
            "color": STATUS_COLORS.get(top_status, "#888"),
        })
    clusters.sort(key=lambda x: -x["count"])
    return {"clusters": clusters[:1000]}


@router.get("/choropleth")
def get_choropleth(
    db: Annotated[Session, Depends(get_db)],
    metric: str = Query("density", regex="^(density|violations|critical_ratio)$"),
    statuses: list[str] | None = Query(None),
    types: list[str] | None = Query(None),
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Агрегация по округам."""
    if metric == "density":
        conditions = _build_conditions(statuses, None, types, date_from, date_to, None)
        where = and_(*conditions) if conditions else True
        rows = db.execute(
            select(
                District.id, District.code, District.name,
                func.count(ControlObject.id).label("value"),
            )
            .outerjoin(ControlObject, and_(ControlObject.district_id == District.id, where))
            .group_by(District.id, District.code, District.name)
            .order_by(District.code)
        ).all()
        return {"metric": metric, "data": [
            {"district_id": r.id, "code": r.code, "name": r.name, "value": int(r.value)}
            for r in rows
        ]}

    elif metric == "violations":
        sql = text("""
            SELECT d.id, d.code, d.name,
                   COUNT(CASE WHEN o.status IN ('violation','critical') THEN 1 END) AS value
            FROM districts d
            LEFT JOIN control_objects o ON o.district_id = d.id
            GROUP BY d.id, d.code, d.name
            ORDER BY d.code
        """)
        rows = db.execute(sql).all()
        return {"metric": metric, "data": [
            {"district_id": r.id, "code": r.code, "name": r.name, "value": int(r.value)}
            for r in rows
        ]}

    else:  # critical_ratio
        sql = text("""
            SELECT d.id, d.code, d.name,
                   COUNT(o.id) AS total,
                   COUNT(CASE WHEN o.status IN ('violation','critical') THEN 1 END) AS bad
            FROM districts d
            LEFT JOIN control_objects o ON o.district_id = d.id
            GROUP BY d.id, d.code, d.name
            ORDER BY d.code
        """)
        rows = db.execute(sql).all()
        return {"metric": metric, "data": [
            {
                "district_id": r.id, "code": r.code, "name": r.name,
                "value": (r.bad / r.total) if r.total > 0 else 0.0,
                "total": int(r.total), "bad": int(r.bad),
            }
            for r in rows
        ]}


@router.get("/timeseries")
def get_timeseries(
    db: Annotated[Session, Depends(get_db)],
    bucket: str = Query("month", regex="^(day|week|month)$"),
    statuses: list[str] | None = Query(None),
    district_ids: list[int] | None = Query(None),
):
    """Тайм-серия проверок по периоду."""
    where_parts = ["i.check_date IS NOT NULL"]
    params: dict = {}
    if statuses:
        # SQLite не любит ANY — используем IN через подстановку
        placeholders = ",".join(f":s{i}" for i in range(len(statuses)))
        where_parts.append(f"i.status IN ({placeholders})")
        for i, s in enumerate(statuses):
            params[f"s{i}"] = s
    if district_ids:
        placeholders = ",".join(f":d{i}" for i in range(len(district_ids)))
        where_parts.append(f"o.district_id IN ({placeholders})")
        for i, d in enumerate(district_ids):
            params[f"d{i}"] = d

    where_sql = "WHERE " + " AND ".join(where_parts)

    # SQLite: date_trunc нет, используем strftime
    if bucket == "month":
        period_expr = "date(i.check_date, 'start of month')"
    elif bucket == "week":
        period_expr = "date(i.check_date, 'weekday 0', '-6 days')"  # понедельник
    else:
        period_expr = "i.check_date"

    sql = text(f"""
        SELECT {period_expr} AS period, i.status, COUNT(*) AS cnt
        FROM inspections i
        JOIN control_objects o ON o.id = i.object_id
        {where_sql}
        GROUP BY period, i.status
        ORDER BY period
    """)
    rows = db.execute(sql, params).all()

    by_period: dict[str, dict] = {}
    for r in rows:
        key = str(r.period)
        if key not in by_period:
            by_period[key] = {"period": key, "total": 0}
        by_period[key][r.status] = int(r.cnt)
        by_period[key]["total"] += int(r.cnt)

    return {"bucket": bucket, "data": list(by_period.values())}


@router.get("/forecast")
def get_forecast(
    db: Annotated[Session, Depends(get_db)],
    horizon_months: int = Query(6, ge=1, le=24),
    district_ids: list[int] | None = Query(None),
    metric: str = Query("violations", regex="^(all|violations|critical)$"),
):
    """Прогноз на N месяцев: линейный тренд + сезонность."""
    import numpy as np
    from datetime import date as _date

    where_parts = ["i.check_date IS NOT NULL"]
    params: dict = {}
    if district_ids:
        placeholders = ",".join(f":d{i}" for i in range(len(district_ids)))
        where_parts.append(f"o.district_id IN ({placeholders})")
        for i, d in enumerate(district_ids):
            params[f"d{i}"] = d
    if metric == "violations":
        where_parts.append("i.status IN ('violation','critical')")
    elif metric == "critical":
        where_parts.append("i.status = 'critical'")
    where_sql = "WHERE " + " AND ".join(where_parts)

    sql = text(f"""
        SELECT date(i.check_date, 'start of month') AS period, COUNT(*) AS cnt
        FROM inspections i
        JOIN control_objects o ON o.id = i.object_id
        {where_sql}
        GROUP BY period
        ORDER BY period
    """)
    rows = db.execute(sql, params).all()
    if len(rows) < 3:
        return {
            "historical": [{"period": str(r.period), "value": int(r.cnt)} for r in rows],
            "forecast": [],
            "warning": "Недостаточно данных для прогноза (нужно минимум 3 месяца истории)",
        }

    periods = [_date.fromisoformat(str(r.period)) for r in rows]
    values = np.array([float(r.cnt) for r in rows])
    n = len(values)
    x = np.arange(n, dtype=float)

    slope, intercept = np.polyfit(x, values, 1)
    trend = slope * x + intercept
    residuals = values - trend

    seasonality = {m: 0.0 for m in range(1, 13)}
    if n >= 12:
        from collections import defaultdict
        by_month = defaultdict(list)
        for p, r in zip(periods, residuals):
            by_month[p.month].append(r)
        seasonality = {m: float(np.mean(vals)) for m, vals in by_month.items()}

    forecast = []
    last_period = periods[-1]
    std = float(np.std(residuals)) if len(residuals) > 1 else 0.0
    for i in range(1, horizon_months + 1):
        y, mo = last_period.year, last_period.month + i
        while mo > 12:
            mo -= 12
            y += 1
        x_future = n + i - 1
        trend_val = slope * x_future + intercept
        seasonal_val = seasonality.get(mo, 0.0)
        predicted = max(0.0, trend_val + seasonal_val)
        forecast.append({
            "period": _date(y, mo, 1).isoformat(),
            "value": round(predicted, 1),
            "lower": round(max(0.0, predicted - 1.96 * std), 1),
            "upper": round(predicted + 1.96 * std, 1),
        })

    return {
        "metric": metric, "horizon_months": horizon_months,
        "historical": [{"period": p.isoformat(), "value": int(v)} for p, v in zip(periods, values)],
        "forecast": forecast,
        "trend_slope": round(float(slope), 2),
        "trend_direction": "рост" if slope > 0.1 else ("снижение" if slope < -0.1 else "стабильно"),
    }


@router.get("/export")
def export_excel(
    db: Annotated[Session, Depends(get_db)],
    statuses: list[str] | None = Query(None),
    district_ids: list[int] | None = Query(None),
    types: list[str] | None = Query(None),
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Экспорт выборки в Excel."""
    import io
    import pandas as pd
    from fastapi.responses import StreamingResponse
    from datetime import datetime as dt

    conditions = _build_conditions(statuses, district_ids, types, date_from, date_to, None)
    stmt = (
        select(
            ControlObject.id, ControlObject.name, ControlObject.type,
            ControlObject.status, ControlObject.address,
            ControlObject.inspector, ControlObject.note,
            ControlObject.last_check_date,
            District.name.label("district_name"),
            ControlObject.lat, ControlObject.lon,
        )
        .outerjoin(District, ControlObject.district_id == District.id)
        .where(and_(*conditions) if conditions else True)
    )
    rows = db.execute(stmt).all()
    df = pd.DataFrame([dict(r._mapping) for r in rows])
    if not df.empty:
        df["status"] = df["status"].map(STATUS_LABELS).fillna(df["status"])
        df = df.rename(columns={
            "id": "ID", "name": "Название", "type": "Тип", "status": "Статус",
            "address": "Адрес", "inspector": "Инспектор", "note": "Примечание",
            "last_check_date": "Последняя проверка",
            "district_name": "Округ", "lat": "Широта", "lon": "Долгота",
        })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Объекты", index=False)
    buf.seek(0)
    fname = f"oati_export_{dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@router.get("/inspectors")
def get_inspector_stats(
    db: Annotated[Session, Depends(get_db)],
):
    """
    Аналитика по инспекторам:
    - сколько проверок провёл
    - сколько уникальных объектов
    - доля нарушений в его проверках
    - средний интервал между проверками (в днях)
    - последняя проверка
    """
    # Базовая агрегация
    sql = text("""
        SELECT
            i.inspector,
            COUNT(*) AS total_checks,
            COUNT(DISTINCT i.object_id) AS unique_objects,
            COUNT(CASE WHEN i.status IN ('violation', 'critical') THEN 1 END) AS violations,
            MAX(i.check_date) AS last_check,
            MIN(i.check_date) AS first_check
        FROM inspections i
        WHERE i.inspector IS NOT NULL AND i.inspector != ''
        GROUP BY i.inspector
        ORDER BY total_checks DESC
    """)
    rows = db.execute(sql).all()

    result = []
    for r in rows:
        # Средний интервал между проверками
        if r.total_checks > 1 and r.first_check and r.last_check:
            first = r.first_check if hasattr(r.first_check, 'toordinal') else date.fromisoformat(str(r.first_check))
            last = r.last_check if hasattr(r.last_check, 'toordinal') else date.fromisoformat(str(r.last_check))
            span_days = (last - first).days
            avg_interval = round(span_days / max(1, r.total_checks - 1), 1) if span_days else 0
        else:
            avg_interval = None

        violation_rate = (r.violations / r.total_checks * 100) if r.total_checks else 0
        result.append({
            "inspector": r.inspector,
            "total_checks": int(r.total_checks),
            "unique_objects": int(r.unique_objects),
            "violations": int(r.violations),
            "violation_rate": round(violation_rate, 1),
            "avg_interval_days": avg_interval,
            "last_check": str(r.last_check) if r.last_check else None,
        })
    return {"inspectors": result}


@router.get("/{object_id}")
def get_object_detail(
    object_id: int,
    db: Annotated[Session, Depends(get_db)],
):
    stmt = (
        select(ControlObject)
        .options(selectinload(ControlObject.inspections), selectinload(ControlObject.district))
        .where(ControlObject.id == object_id)
    )
    obj = db.scalar(stmt)
    if not obj:
        raise HTTPException(404, "Объект не найден")
    return {
        "id": obj.id, "name": obj.name, "type": obj.type,
        "status": obj.status,
        "status_label": STATUS_LABELS.get(obj.status, obj.status),
        "status_color": STATUS_COLORS.get(obj.status, "#888"),
        "address": obj.address, "inspector": obj.inspector, "note": obj.note,
        "last_check_date": obj.last_check_date.isoformat() if obj.last_check_date else None,
        "lon": obj.lon, "lat": obj.lat,
        "district_id": obj.district_id,
        "district_name": obj.district.name if obj.district else None,
        "inspections": [
            {
                "id": i.id, "check_date": i.check_date.isoformat(),
                "status": i.status,
                "status_label": STATUS_LABELS.get(i.status, i.status),
                "inspector": i.inspector, "note": i.note,
            }
            for i in obj.inspections
        ],
    }


@router.delete("/")
def delete_all(db: Annotated[Session, Depends(get_db)]):
    n = db.query(ControlObject).delete()
    db.commit()
    return {"deleted": n}
