"""Repository contracts independent from Flask routes and business rules."""

from __future__ import annotations

from typing import Protocol


class ApplicationRepository(Protocol):
    def load_all(self) -> list[dict]: ...

    def save_all(self, applications: list[dict]) -> None: ...


class UserRepository(Protocol):
    def load_all(self) -> list[dict]: ...

    def save_all(self, users: list[dict]) -> None: ...