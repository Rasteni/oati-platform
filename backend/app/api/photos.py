"""API фотографий объектов."""
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ControlObject, Photo

router = APIRouter(prefix="/api/photos", tags=["photos"])

# Папка для фото
UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/{object_id}")
async def upload_photo(
    object_id: int,
    db: Annotated[Session, Depends(get_db)],
    file: UploadFile = File(...),
):
    """Загрузка фото к объекту."""
    obj = db.query(ControlObject).filter_by(id=object_id).first()
    if not obj:
        raise HTTPException(404, "Объект не найден")

    if file.content_type not in ALLOWED_MIME:
        raise HTTPException(400, f"Допустимы только изображения (JPG, PNG, WEBP, GIF). Получен: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(413, f"Файл больше {MAX_SIZE // (1024*1024)} МБ")

    ext = (file.filename or "img").rsplit(".", 1)[-1].lower()[:5]
    new_name = f"obj{object_id}_{uuid.uuid4().hex[:12]}.{ext}"
    path = UPLOADS_DIR / new_name
    path.write_bytes(content)

    photo = Photo(
        object_id=object_id,
        filename=new_name,
        original_name=file.filename,
        mime_type=file.content_type,
        size_bytes=len(content),
    )
    db.add(photo)
    db.commit()
    db.refresh(photo)

    return {
        "id": photo.id,
        "url": f"/api/photos/file/{photo.filename}",
        "original_name": photo.original_name,
        "size_bytes": photo.size_bytes,
    }


@router.get("/object/{object_id}")
def list_photos(object_id: int, db: Annotated[Session, Depends(get_db)]):
    """Список фото объекта."""
    photos = db.query(Photo).filter_by(object_id=object_id).order_by(Photo.uploaded_at.desc()).all()
    return [
        {
            "id": p.id,
            "url": f"/api/photos/file/{p.filename}",
            "original_name": p.original_name,
            "size_bytes": p.size_bytes,
            "uploaded_at": p.uploaded_at.isoformat() if p.uploaded_at else None,
        }
        for p in photos
    ]


@router.get("/file/{filename}")
def get_photo_file(filename: str):
    """Отдача файла фото."""
    # Защита от path traversal
    if "/" in filename or ".." in filename:
        raise HTTPException(400, "Invalid filename")
    path = UPLOADS_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Файл не найден")
    return FileResponse(str(path))


@router.delete("/{photo_id}")
def delete_photo(photo_id: int, db: Annotated[Session, Depends(get_db)]):
    """Удалить фото."""
    photo = db.query(Photo).filter_by(id=photo_id).first()
    if not photo:
        raise HTTPException(404, "Фото не найдено")
    path = UPLOADS_DIR / photo.filename
    if path.exists():
        try:
            path.unlink()
        except Exception:
            pass
    db.delete(photo)
    db.commit()
    return {"deleted": photo_id}
