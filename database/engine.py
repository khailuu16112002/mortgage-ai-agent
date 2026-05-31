"""Database engine, session factory, and dependency injection."""
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from .models import Base
from config import get_settings, get_logger

logger = get_logger(__name__)
_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    settings = get_settings()
    url = settings.db.url

    kwargs: dict = {
        "echo": settings.db.echo,
    }

    if url.startswith("sqlite"):
        # SQLite needs special pool for multi-thread use
        kwargs["connect_args"] = {"check_same_thread": False}
        kwargs["poolclass"] = StaticPool
    else:
        kwargs["pool_size"] = settings.db.pool_size
        kwargs["max_overflow"] = 10

    _engine = create_engine(url, **kwargs)

    # Enable WAL mode for SQLite (better concurrency)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    logger.info(f"Database engine created: {url.split('://')[0]}")
    return _engine


def get_session_factory() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        engine = get_engine()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _SessionLocal


def create_tables() -> None:
    """Create all tables. Safe to call multiple times."""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created/verified")


def drop_tables() -> None:
    """Drop all tables. USE WITH CAUTION."""
    engine = get_engine()
    Base.metadata.drop_all(bind=engine)
    logger.warning("All database tables dropped")


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Context manager for database sessions."""
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# FastAPI dependency
def get_db_dependency() -> Generator[Session, None, None]:
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
