from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import BASE_DIR, get_settings

DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


def normalize_database_url(url: str) -> str:
    """Normaliza URLs comuns de PostgreSQL para o driver Psycopg 3."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def build_engine(database_url: str | None = None) -> Engine:
    url = normalize_database_url(database_url or get_settings().database_url)
    options: dict[str, object] = {
        "pool_pre_ping": True,
        "future": True,
    }
    if url.startswith("sqlite"):
        options["connect_args"] = {"check_same_thread": False}
    else:
        options.update({"pool_size": 5, "max_overflow": 2, "pool_recycle": 300})
    return create_engine(url, **options)


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
