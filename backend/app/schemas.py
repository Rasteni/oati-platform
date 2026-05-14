"""Pydantic-схемы для API."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


# === Статусы ===
StatusKey = Literal["ok", "warn", "violation", "critical", "pending", "unknown"]

STATUS_MAP = {
    "норма": "ok", "ok": "ok", "устранено": "ok",
    "замечание": "warn", "предписание": "warn", "warn": "warn",
    "нарушение": "violation", "violation": "violation",
    "критическое": "critical", "critical": "critical",
    "на проверке": "pending", "pending": "pending",
}

STATUS_LABELS = {
    "ok": "Норма",
    "warn": "Замечание",
    "violation": "Нарушение",
    "critical": "Критическое",
    "pending": "На проверке",
    "unknown": "Неизвестно",
}

STATUS_COLORS = {
    "ok": "#22c55e",
    "warn": "#f59e0b",
    "violation": "#ef4444",
    "critical": "#ec4899",
    "pending": "#3b82f6",
    "unknown": "#9ca3af",
}


def normalize_status(raw: str | None) -> str:
    if not raw:
        return "unknown"
    return STATUS_MAP.get(str(raw).strip().lower(), "unknown")


# === Округа ===
class DistrictOut(BaseModel):
    id: int
    code: str
    name: str
    full_name: str
    objects_count: int = 0

    class Config:
        from_attributes = True


# === Объекты ===
class InspectionOut(BaseModel):
    id: int
    check_date: date
    status: str
    status_label: str
    inspector: str | None
    note: str | None


class ControlObjectOut(BaseModel):
    id: int
    name: str
    type: str | None
    status: str
    status_label: str
    status_color: str
    address: str | None
    inspector: str | None
    note: str | None
    last_check_date: date | None
    lat: float
    lon: float
    district_id: int | None
    district_name: str | None
    inspections_count: int = 0


# === GeoJSON ===
class GeoJSONFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict
    properties: dict


class GeoJSONFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[GeoJSONFeature]


# === Статистика ===
class StatsResponse(BaseModel):
    total: int
    visible: int
    by_status: dict[str, int]
    by_district: list[dict]
    by_type: dict[str, int]


# === Импорт ===
class ImportResult(BaseModel):
    imported: int
    inspections: int = 0
    skipped: int
    geocoded: int = 0
    errors: list[str] = Field(default_factory=list)
    message: str


# === Фильтры ===
class FilterParams(BaseModel):
    statuses: list[str] | None = None
    district_ids: list[int] | None = None
    types: list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None
    bbox: str | None = None  # "minLon,minLat,maxLon,maxLat"
