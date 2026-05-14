"""Конфигурация приложения (SQLite-версия)."""
import os
from functools import lru_cache
from pathlib import Path


class Settings:
    # БД в файле рядом с проектом
    DB_PATH: str = os.getenv("DB_PATH", str(Path(__file__).resolve().parent.parent.parent / "oati.db"))
    DATABASE_URL: str = f"sqlite:///{DB_PATH}"
    CORS_ORIGINS: list[str] = ["*"]
    APP_NAME: str = "ОАТИ · Геоаналитика"
    MAX_UPLOAD_MB: int = 50


@lru_cache
def get_settings() -> Settings:
    return Settings()
