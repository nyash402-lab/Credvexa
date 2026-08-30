"""Optional SQLAlchemy foundation kept separate from the JSON-backed runtime."""

from __future__ import annotations

from flask import Flask
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, scoped_session, sessionmaker

from app.config import get_database_url


class Base(DeclarativeBase):
    """Base class for database models managed exclusively by Alembic."""


SessionLocal = scoped_session(sessionmaker(autoflush=False, autocommit=False))
_engine: Engine | None = None


def init_database(app: Flask) -> None:
    """Initialize database connectivity without creating schema or changing route storage."""
    global _engine

    app.config["DATABASE_READY"] = False
    app.config["DATABASE_ERROR"] = None

    try:
        database_url = get_database_url()
        app.config["DATABASE_URL"] = database_url
        connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
        _engine = create_engine(database_url, connect_args=connect_args)
        if database_url.startswith("sqlite"):
            event.listen(_engine, "connect", _enable_sqlite_foreign_keys)
        SessionLocal.configure(bind=_engine)
        app.config["DATABASE_READY"] = True
    except Exception as exc:
        message = f"Database initialization unavailable; JSON storage remains active: {exc}"
        app.config["DATABASE_URL"] = None
        app.config["DATABASE_ERROR"] = message
        app.logger.warning(message)

    @app.teardown_appcontext
    def remove_database_session(_exception=None):
        SessionLocal.remove()


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database is not initialized.")
    return _engine


def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()