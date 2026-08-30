"""Candidate-specific persistence helpers for the active JSON storage backend."""

from pathlib import Path

from app.repositories.json_application_repository import JsonApplicationRepository


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_applications = JsonApplicationRepository(PROJECT_ROOT / "credvexa_data.json")


def get_saved_approved_amount(mobile: str) -> int | None:
    application = _applications.find_latest_by_mobile(mobile)
    if not application or application.get("approved_amount") in (None, ""):
        return None
    return int(application["approved_amount"])


def save_approved_amount(application_id: str, approved_amount: int) -> bool:
    return _applications.set_approved_amount(application_id, approved_amount) is not None