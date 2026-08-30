"""Create verified JSON backups and a redacted, SQL-free migration dry-run report."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


USER_REQUIRED_FIELDS = ("id", "full_name", "email", "mobile", "password", "created_at")
APPLICATION_REQUIRED_FIELDS = (
    "application_id", "full_name", "mobile", "email", "monthly_income", "requested_amount",
    "tenure_months", "loan_purpose", "city", "state", "pin_code", "status", "emi",
    "created_at", "updated_at",
)
USER_FIELD_MAP = {
    "id": "legacy_user_id",
    "full_name": "full_name",
    "email": "email",
    "mobile": "mobile",
    "created_at": "created_at",
}
APPLICATION_FIELD_MAP = {
    "application_id": "application_id", "full_name": "full_name", "dob": "dob", "age": "age",
    "mobile": "mobile", "email": "email", "employment_type": "employment_type",
    "monthly_income": "monthly_income", "requested_amount": "requested_amount",
    "tenure_months": "tenure_months", "loan_purpose": "loan_purpose", "city": "city",
    "state": "state", "pin_code": "pin_code", "status": "status", "emi": "emi",
    "note": "note", "created_at": "created_at", "updated_at": "updated_at",
}
SENSITIVE_FIELDS = {"password", "pan", "aadhaar", "otp", "otp_digest"}


def file_metadata(path: Path) -> dict[str, Any]:
    content = path.read_bytes()
    return {"name": path.name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def redact_reference(value: object) -> str:
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"record:{digest[:12]}"


def load_records(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, list):
        raise ValueError(f"{path.name} must contain a JSON array.")
    return payload


def _missing_fields(record: dict[str, Any], required_fields: tuple[str, ...]) -> list[str]:
    return [field for field in required_fields if str(record.get(field, "")).strip() in {"", "None"}]


def _duplicates(records: list[dict[str, Any]], field: str, label: str) -> list[dict[str, str]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if not isinstance(record, dict):
            continue
        value = str(record.get(field, "")).strip()
        if value:
            grouped[value].append(record)
    return [
        {"identifier": label, "record": redact_reference(value), "occurrences": str(len(items))}
        for value, items in grouped.items()
        if len(items) > 1
    ]


def analyze_users(records: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    accepted = 0
    for position, record in enumerate(records, start=1):
        reference = redact_reference(record.get("id", f"user-{position}")) if isinstance(record, dict) else f"record:{position}"
        if not isinstance(record, dict):
            issues.append({"record": reference, "issues": [{"code": "invalid_record_type"}]})
            continue
        missing = _missing_fields(record, USER_REQUIRED_FIELDS)
        if missing:
            issues.append({"record": reference, "issues": [{"field": field, "code": "missing_required"} for field in missing]})
            continue
        accepted += 1
        manual_review.append({
            "record": reference,
            "issues": [{"field": "password", "target": "password_hash", "code": "plaintext_password_requires_secure_reset_or_hashing"}],
        })
    duplicates = _duplicates(records, "id", "legacy_user_id") + _duplicates(records, "email", "email") + _duplicates(records, "mobile", "mobile")
    return {
        "source_records": len(records), "structurally_mappable_records": accepted,
        "rejected_records": issues, "manual_review_records": manual_review,
        "duplicate_identifiers": duplicates, "field_mapping": USER_FIELD_MAP,
    }


def analyze_applications(records: list[dict[str, Any]], users: list[dict[str, Any]]) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    manual_review: list[dict[str, Any]] = []
    accepted = 0
    user_mobiles = Counter(str(item.get("mobile", "")).strip() for item in users if isinstance(item, dict))
    for position, record in enumerate(records, start=1):
        reference = redact_reference(record.get("application_id", f"application-{position}")) if isinstance(record, dict) else f"record:{position}"
        if not isinstance(record, dict):
            issues.append({"record": reference, "issues": [{"code": "invalid_record_type"}]})
            continue
        missing = _missing_fields(record, APPLICATION_REQUIRED_FIELDS)
        record_issues = [{"field": field, "code": "missing_required"} for field in missing]
        for field in ("monthly_income", "requested_amount", "emi"):
            try:
                float(record.get(field, 0))
            except (TypeError, ValueError):
                record_issues.append({"field": field, "code": "invalid_number"})
        try:
            int(record.get("tenure_months", 0))
        except (TypeError, ValueError):
            record_issues.append({"field": "tenure_months", "code": "invalid_integer"})
        if record_issues:
            issues.append({"record": reference, "issues": record_issues})
            continue
        accepted += 1
        review_issues = [
            {"field": "pan", "target": "pan_ciphertext/pan_digest", "code": "requires_field_encryption"},
            {"field": "aadhaar", "target": "aadhaar_ciphertext/aadhaar_digest", "code": "requires_field_encryption"},
        ]
        mobile_count = user_mobiles[str(record.get("mobile", "")).strip()]
        if mobile_count == 0:
            review_issues.append({"field": "user_id", "code": "no_matching_user_mobile"})
        elif mobile_count > 1:
            review_issues.append({"field": "user_id", "code": "ambiguous_matching_user_mobile"})
        manual_review.append({"record": reference, "issues": review_issues})
    duplicates = _duplicates(records, "application_id", "application_id")
    return {
        "source_records": len(records), "structurally_mappable_records": accepted,
        "rejected_records": issues, "manual_review_records": manual_review,
        "duplicate_identifiers": duplicates, "field_mapping": APPLICATION_FIELD_MAP,
    }


def build_report(applications: list[dict[str, Any]], users: list[dict[str, Any]], source_metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "mode": "dry_run_read_only",
        "sql_writes": 0,
        "source_files": source_metadata,
        "users": analyze_users(users),
        "loan_applications": analyze_applications(applications, users),
        "otp_challenges": {"source_records": 0, "reason": "no JSON source exists"},
        "application_events": {"source_records": 0, "reason": "no JSON source exists"},
        "sensitive_fields_redacted": sorted(SENSITIVE_FIELDS),
    }


def create_verified_backup(source: Path, backup_directory: Path) -> dict[str, Any]:
    before = file_metadata(source)
    backup_directory.mkdir(parents=True, exist_ok=True)
    backup = backup_directory / source.name
    if backup.exists():
        if file_metadata(backup)["sha256"] != before["sha256"]:
            raise ValueError(f"Backup checksum mismatch for {source.name}; refusing to overwrite it.")
    else:
        shutil.copy2(source, backup)
    after = file_metadata(source)
    if before != after or file_metadata(backup)["sha256"] != before["sha256"]:
        raise RuntimeError(f"Backup verification failed for {source.name}.")
    return {"source": before, "backup": {"name": backup.name, "sha256": before["sha256"]}, "verified": True}


def prepare(source_directory: Path, backup_directory: Path, report_path: Path) -> dict[str, Any]:
    applications_path = source_directory / "credvexa_data.json"
    users_path = source_directory / "credvexa_users.json"
    backups = {
        "credvexa_data.json": create_verified_backup(applications_path, backup_directory),
        "credvexa_users.json": create_verified_backup(users_path, backup_directory),
    }
    applications = load_records(applications_path)
    users = load_records(users_path)
    metadata = {name: result["source"] for name, result in backups.items()}
    report = build_report(applications, users, metadata)
    report["backup_verification"] = backups
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    report = prepare(arguments.source_dir, arguments.backup_dir, arguments.report)
    print(json.dumps({
        "mode": report["mode"], "sql_writes": report["sql_writes"],
        "users": report["users"]["source_records"],
        "loan_applications": report["loan_applications"]["source_records"],
        "report": str(arguments.report),
    }))


if __name__ == "__main__":
    main()