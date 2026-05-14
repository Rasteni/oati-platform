"""Модели данных (SQLite-версия)."""
from datetime import datetime, date

from sqlalchemy import (
    String, Integer, Float, Date, DateTime, ForeignKey, Text, Index, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class District(Base):
    """Округ Москвы. Полигон хранится как JSON-строка списка [[lon, lat], ...]."""
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    full_name: Mapped[str] = mapped_column(String(255))
    polygon_json: Mapped[str] = mapped_column(Text)


class ControlObject(Base):
    """Объект контроля ОАТИ."""
    __tablename__ = "control_objects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(500))
    type: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), index=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    inspector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_check_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    lat: Mapped[float] = mapped_column(Float, index=True)
    lon: Mapped[float] = mapped_column(Float, index=True)

    district_id: Mapped[int | None] = mapped_column(
        ForeignKey("districts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    district: Mapped["District | None"] = relationship("District")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    inspections: Mapped[list["Inspection"]] = relationship(
        "Inspection", back_populates="object", cascade="all, delete-orphan",
        order_by="Inspection.check_date.desc()",
    )


class Inspection(Base):
    """История проверок объекта."""
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_id: Mapped[int] = mapped_column(
        ForeignKey("control_objects.id", ondelete="CASCADE"), index=True
    )
    check_date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(50))
    inspector: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    object: Mapped["ControlObject"] = relationship(
        "ControlObject", back_populates="inspections"
    )


class Photo(Base):
    """Фотографии к объекту контроля. Файлы хранятся в uploads/, БД — только метаданные."""
    __tablename__ = "photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    object_id: Mapped[int] = mapped_column(
        ForeignKey("control_objects.id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))   # имя файла на диске
    original_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
