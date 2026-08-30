"""JSON loan application repository matching the active legacy storage format."""

from __future__ import annotations

import json
from pathlib import Path


class JsonApplicationRepository:
    def __init__(self, data_file: Path):
        self._data_file = data_file

    def load_all(self) -> list[dict]:
        if not self._data_file.exists():
            return []
        try:
            with self._data_file.open("r", encoding="utf-8") as file:
                data = json.load(file)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def save_all(self, applications: list[dict]) -> None:
        with self._data_file.open("w", encoding="utf-8") as file:
            json.dump(applications, file, indent=2)

    def find_latest_by_mobile(self, mobile: str) -> dict | None:
        normalized_mobile = str(mobile).strip()
        for application in reversed(self.load_all()):
            if str(application.get("mobile", "")).strip() == normalized_mobile:
                return application
        return None

    def set_approved_amount(self, application_id: str, approved_amount: int) -> dict | None:
        applications = self.load_all()
        for application in applications:
            if application.get("application_id") == application_id:
                application["approved_amount"] = int(approved_amount)
                self.save_all(applications)
                return application
        return None