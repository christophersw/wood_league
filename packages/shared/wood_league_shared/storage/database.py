"""
Title: database.py — SQLAlchemy engine and session factory
Description:
    Builds the SQLAlchemy engine from the DATABASE_URL environment variable.
    Falls back to a local SQLite file for development when DATABASE_URL is unset.
    Exports ENGINE, get_session(), and init_db() for use by all services.

Changelog:
    2026-05-07: Extracted from stockfish_pipeline and dispatchers into shared library
"""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from wood_league_shared.storage.models import Base


def _normalize_database_url(database_url: str) -> str:
    """Normalize any postgres:// variant to the psycopg3 driver scheme.

    Parameters:
        database_url (str): The raw database URL string to normalize.

    Returns:
        str: The normalized URL using the postgresql+psycopg:// scheme.
    """
    if database_url.startswith("postgresql+psycopg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def _build_engine():
    """Build a SQLAlchemy engine from DATABASE_URL or fall back to SQLite.

    Returns:
        Engine: A SQLAlchemy engine instance, either PostgreSQL or SQLite.

    Side effects:
        Reads the DATABASE_URL environment variable.
    """
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return create_engine(_normalize_database_url(url), pool_pre_ping=True)
    return create_engine("sqlite+pysqlite:///wood_league_chess.db", pool_pre_ping=True)


ENGINE = _build_engine()
SessionLocal = sessionmaker(bind=ENGINE, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create all tables defined in the shared models if they do not exist."""
    Base.metadata.create_all(ENGINE)


@contextmanager
def get_session() -> Session:
    """Yield a SQLAlchemy session and close it when done.

    Yields:
        Session: An open SQLAlchemy ORM session.

    Side effects:
        Closes the session in the finally block regardless of exceptions.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
