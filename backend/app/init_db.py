"""Инициализация SQLite-БД: таблицы, загрузка округов Москвы."""
import json
import logging

from app.database import engine, SessionLocal, Base
from app.models import District
from app.data.moscow_districts import MOSCOW_DISTRICTS

log = logging.getLogger(__name__)


def init_tables() -> None:
    Base.metadata.create_all(bind=engine)
    log.info("Tables created")


def seed_districts() -> None:
    db = SessionLocal()
    try:
        if db.query(District).count() > 0:
            log.info("Districts already loaded, skipping")
            return

        for d in MOSCOW_DISTRICTS:
            district = District(
                code=d["code"],
                name=d["name"],
                full_name=d["full_name"],
                polygon_json=json.dumps(d["polygon"]),
            )
            db.add(district)
        db.commit()
        log.info("Loaded %d districts", len(MOSCOW_DISTRICTS))
    except Exception as e:
        db.rollback()
        log.error("Seed failed: %s", e)
        raise
    finally:
        db.close()


def init_db() -> None:
    init_tables()
    seed_districts()
