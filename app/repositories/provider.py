"""Repository selection for a future approved route cutover."""

from __future__ import annotations

import os
from pathlib import Path

from app.database import SessionLocal, get_engine
from app.repositories.json_application_repository import JsonApplicationRepository
from app.repositories.json_user_repository import JsonUserRepository
from app.repositories.sqlalchemy_application_repository import SqlAlchemyApplicationRepository
from app.repositories.sqlalchemy_user_repository import SqlAlchemyUserRepository


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def get_application_repository():
    if _uses_sqlalchemy():
        return SqlAlchemyApplicationRepository(SessionLocal())
    return JsonApplicationRepository(PROJECT_ROOT / "credvexa_data.json")


def get_user_repository():
    if _uses_sqlalchemy():
        return SqlAlchemyUserRepository(SessionLocal())
    return JsonUserRepository(PROJECT_ROOT / "credvexa_users.json")


def _uses_sqlalchemy() -> bool:
    if str(os.getenv("CREDVEXA_STORAGE_BACKEND", "json")).strip().lower() != "sqlalchemy":
        return False
    try:
        get_engine()
    except RuntimeError:
        return False
    return True