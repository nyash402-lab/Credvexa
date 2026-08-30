"""Storage abstractions for the incremental repository migration."""

from app.repositories.provider import get_application_repository, get_user_repository

__all__ = ["get_application_repository", "get_user_repository"]