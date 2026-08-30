"""Environment-driven runtime configuration for Credvexa."""

from __future__ import annotations

import os
import secrets
import warnings
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class AppSettings:
    environment: str
    secret_key: str
    debug: bool
    host: str
    port: int
    session_cookie_secure: bool


def get_settings() -> AppSettings:
    environment = str(os.getenv("FLASK_ENV", "development")).strip().lower()
    if environment not in {"development", "production"}:
        raise RuntimeError("FLASK_ENV must be either 'development' or 'production'.")

    secret_key = str(os.getenv("SECRET_KEY", "")).strip()
    if not secret_key:
        if environment == "production":
            raise RuntimeError("SECRET_KEY must be configured when FLASK_ENV is production.")
        secret_key = secrets.token_urlsafe(48)
        warnings.warn("SECRET_KEY is not set; using a temporary development-only key.", stacklevel=2)

    return AppSettings(
        environment=environment,
        secret_key=secret_key,
        debug=environment == "development",
        host=str(os.getenv("HOST", "0.0.0.0" if environment == "production" else "127.0.0.1")).strip(),
        port=_get_port(),
        session_cookie_secure=environment == "production",
    )


def get_database_url() -> str:
    database_url = str(os.getenv("DATABASE_URL", "")).strip()
    if database_url:
        if database_url.startswith("postgres://"):
            return f"postgresql+psycopg://{database_url.removeprefix('postgres://')}"
        return database_url
    if str(os.getenv("FLASK_ENV", "development")).strip().lower() == "production":
        raise RuntimeError("DATABASE_URL must be configured when FLASK_ENV is production.")
    return f"sqlite:///{(PROJECT_ROOT / 'credvexa_dev.db').as_posix()}"


def _get_port() -> int:
    port = str(os.getenv("PORT", "5000")).strip()
    try:
        return int(port)
    except ValueError as exc:
        raise RuntimeError("PORT must be an integer.") from exc