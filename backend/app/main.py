"""ОАТИ · Геоаналитика — главный модуль FastAPI."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import get_settings
from app.init_db import init_db
from app.api import objects, districts, import_data, photos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация БД при старте."""
    log.info("Starting %s...", settings.APP_NAME)
    try:
        init_db()
        log.info("DB ready")
    except Exception as e:
        log.error("DB init failed: %s", e)
        raise
    yield
    log.info("Shutting down")


app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="API для геоаналитики объектов контроля ОАТИ",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(objects.router)
app.include_router(districts.router)
app.include_router(import_data.router)
app.include_router(photos.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME}


# Статика фронтенда — ищем в типовых местах (Docker и локальный запуск)
def _find_frontend() -> Path | None:
    here = Path(__file__).resolve().parent
    candidates = [
        here.parent.parent / "frontend",  # локально: backend/app/main.py -> ../../frontend
        Path("/app/frontend"),            # docker: смонтированный volume
        here.parent / "frontend",         # на всякий случай
    ]
    for p in candidates:
        if p.exists() and (p / "index.html").exists():
            return p
    return None


FRONTEND_DIR = _find_frontend()
if FRONTEND_DIR:
    log.info("Frontend dir: %s", FRONTEND_DIR)
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/")
    def root():
        return FileResponse(FRONTEND_DIR / "index.html")
else:
    log.warning("Frontend not found")

    @app.get("/")
    def root():
        return {"message": "Frontend not built. API docs: /docs"}
