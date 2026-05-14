"""API округов Москвы (SQLite-версия)."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import District, ControlObject

router = APIRouter(prefix="/api/districts", tags=["districts"])


@router.get("/")
def list_districts(db: Annotated[Session, Depends(get_db)]):
    rows = db.execute(
        select(
            District.id, District.code, District.name, District.full_name,
            func.count(ControlObject.id).label("cnt"),
        )
        .outerjoin(ControlObject, ControlObject.district_id == District.id)
        .group_by(District.id)
        .order_by(District.code)
    ).all()
    return [
        {"id": r.id, "code": r.code, "name": r.name,
         "full_name": r.full_name, "objects_count": r.cnt}
        for r in rows
    ]


@router.get("/geojson")
def districts_geojson(db: Annotated[Session, Depends(get_db)]):
    rows = db.execute(
        select(
            District.id, District.code, District.name, District.full_name,
            District.polygon_json,
            func.count(ControlObject.id).label("cnt"),
        )
        .outerjoin(ControlObject, ControlObject.district_id == District.id)
        .group_by(District.id)
    ).all()
    features = []
    for r in rows:
        polygon = json.loads(r.polygon_json)
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [polygon]},
            "properties": {
                "id": r.id, "code": r.code, "name": r.name,
                "full_name": r.full_name, "count": r.cnt,
            },
        })
    return {"type": "FeatureCollection", "features": features}
