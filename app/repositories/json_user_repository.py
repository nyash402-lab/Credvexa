"""JSON user repository matching the active legacy storage format."""

from __future__ import annotations

import json
from pathlib import Path


class JsonUserRepository:
    def __init__(self, users_file: Path):
        self._users_file = users_file

    def load_all(self) -> list[dict]:
        if not self._users_file.exists():
            return []
        try:
            with self._users_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def save_all(self, users: list[dict]) -> None:
        with self._users_file.open("w", encoding="utf-8") as file:
            json.dump(users, file, indent=2)