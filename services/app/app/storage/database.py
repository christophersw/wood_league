"""Database connection and session management using SQLAlchemy.

Provides database engine, session factory, and initialization utilities for the Wood League application.
"""
import threading

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.storage.models import Base


settings = get_settings()


def _normalize_database_url(database_url: str) -> str:
    """Normalize PostgreSQL URLs to use the psycopg driver."""
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def _engine():
    """Create the SQLAlchemy engine using configured database URL or SQLite fallback."""
    if settings.database_url:
        return create_engine(_normalize_database_url(settings.database_url), pool_pre_ping=True)
    return create_engine("sqlite+pysqlite:///wood_league_chess.db", pool_pre_ping=True)


ENGINE = _engine()
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)

_db_initialized = False
_db_lock = threading.Lock()


def init_db() -> None:
    """Create all tables if they don't exist. Safe to call many times — only runs once per process."""
    global _db_initialized
    if _db_initialized:
        return
    with _db_lock:
        if not _db_initialized:
            Base.metadata.create_all(ENGINE)
            _db_initialized = True


def get_session() -> Session:
    """Create and return a new database session."""
    return SessionLocal()
