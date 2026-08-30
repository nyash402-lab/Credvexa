"""Controlled JSON-to-SQL migration. Defaults to dry-run; --apply requires --confirm."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.prepare_json_migration import build_report, create_verified_backup, file_metadata, load_records, redact_reference
except ModuleNotFoundError:
    from prepare_json_migration import build_report, create_verified_backup, file_metadata, load_records, redact_reference


REQUIRED_ENVIRONMENT_NAMES = (
    "FIELD_ENCRYPTION_KEY", "FIELD_DIGEST_KEY", "DATABASE_URL", "SECRET_KEY",
    "MSG91_AUTH_TOKEN", "MSG91_API_BASE", "MSG91_SENDER_ID", "MSG91_COUNTRY_CODE",
    "MSG91_OTP_LENGTH", "MSG91_OTP_EXPIRY_MINUTES",
)
EXPECTED_REVISION = "20260829_01"


def build_dry_run_report(source_directory: Path, backup_directory: Path) -> tuple[list[dict], list[dict], dict[str, Any]]:
    applications_path = source_directory / "credvexa_data.json"
    users_path = source_directory / "credvexa_users.json"
    backups = {
        applications_path.name: create_verified_backup(applications_path, backup_directory),
        users_path.name: create_verified_backup(users_path, backup_directory),
    }
    users = load_records(users_path)
    applications = load_records(applications_path)
    report = build_report(applications, users, {applications_path.name: file_metadata(applications_path), users_path.name: file_metadata(users_path)})
    report.update({
        "mode": "secure_migration_dry_run",
        "sql_writes": 0,
        "backup_verification": backups,
        "security_readiness": _security_readiness(),
    })
    return users, applications, report


def migrate(source_directory: Path, backup_directory: Path, apply: bool) -> dict[str, Any]:
    users, applications, report = build_dry_run_report(source_directory, backup_directory)
    if not apply:
        return report

    _validate_apply_preflight(report, source_directory)

    from flask import Flask
    from app.database import SessionLocal, get_engine, init_database
    from app.models.loan_application import LoanApplication
    from app.models.user import User
    from app.security.crypto import encrypt_sensitive_value, sensitive_digest
    from app.security.passwords import hash_legacy_password

    migration_app = Flask("secure_migration")
    init_database(migration_app)
    if not migration_app.config["DATABASE_READY"]:
        raise RuntimeError("Target database initialization failed; no SQL writes were attempted.")
    get_engine()
    database_session = SessionLocal()
    created_users = created_applications = skipped_users = skipped_applications = 0
    try:
        user_ids: dict[str, int] = {}
        for record in users:
            if not isinstance(record, dict):
                continue
            legacy_user_id = str(record.get("id", "")).strip()
            if not legacy_user_id:
                continue
            user = database_session.query(User).filter_by(legacy_user_id=legacy_user_id).one_or_none()
            if user is None:
                user = User(
                    legacy_user_id=legacy_user_id,
                    full_name=str(record["full_name"]).strip(),
                    email=str(record["email"]).strip().lower(),
                    mobile=str(record["mobile"]).strip(),
                    password_hash=hash_legacy_password(str(record["password"])),
                    created_at=_parse_timestamp(record.get("created_at")),
                )
                database_session.add(user)
                database_session.flush()
                created_users += 1
            else:
                skipped_users += 1
            user_ids[str(record.get("mobile", "")).strip()] = user.id

        for record in applications:
            if not isinstance(record, dict):
                continue
            application_id = str(record.get("application_id", "")).strip()
            if not application_id:
                continue
            existing = database_session.query(LoanApplication).filter_by(application_id=application_id).one_or_none()
            if existing is not None:
                skipped_applications += 1
                continue
            application = LoanApplication(
                user_id=user_ids.get(str(record.get("mobile", "")).strip()),
                application_id=application_id,
                full_name=str(record["full_name"]).strip(), dob=_string_or_none(record.get("dob")),
                age=_int_or_none(record.get("age")), mobile=str(record["mobile"]).strip(),
                email=_string_or_none(record.get("email")),
                pan_ciphertext=encrypt_sensitive_value(str(record.get("pan", ""))),
                pan_digest=sensitive_digest(str(record.get("pan", ""))),
                aadhaar_ciphertext=encrypt_sensitive_value(str(record.get("aadhaar", ""))),
                aadhaar_digest=sensitive_digest(str(record.get("aadhaar", ""))),
                employment_type=_string_or_none(record.get("employment_type")),
                monthly_income=_float_or_none(record.get("monthly_income")),
                requested_amount=_float_or_none(record.get("requested_amount")),
                tenure_months=_int_or_none(record.get("tenure_months")), loan_purpose=_string_or_none(record.get("loan_purpose")),
                city=_string_or_none(record.get("city")), state=_string_or_none(record.get("state")),
                pin_code=_string_or_none(record.get("pin_code")), status=str(record["status"]).strip(),
                emi=_float_or_none(record.get("emi")), note=_string_or_none(record.get("note")),
                rejection_reason=_string_or_none(record.get("rejection_reason")),
                rejected_at=_parse_timestamp(record.get("rejected_at")),
                created_at=_parse_timestamp(record.get("created_at")), updated_at=_parse_timestamp(record.get("updated_at")),
            )
            database_session.add(application)
            created_applications += 1
        database_session.commit()
    except Exception:
        database_session.rollback()
        raise
    finally:
        database_session.close()
    report.update({
        "mode": "secure_migration_applied", "sql_writes": created_users + created_applications,
        "migration": {"created_users": created_users, "skipped_users": skipped_users, "created_applications": created_applications, "skipped_applications": skipped_applications},
    })
    return report


def _security_readiness() -> dict[str, bool]:
    from os import getenv
    return {"field_encryption_key": bool(getenv("FIELD_ENCRYPTION_KEY")), "field_digest_key": bool(getenv("FIELD_DIGEST_KEY"))}


def _validate_apply_preflight(report: dict[str, Any], source_directory: Path) -> None:
    from os import getenv
    from sqlalchemy import create_engine, text
    from app.config import get_database_url, get_settings

    missing = [name for name in REQUIRED_ENVIRONMENT_NAMES if not str(getenv(name, "")).strip()]
    if missing:
        raise RuntimeError(f"Migration prerequisites are missing: {', '.join(missing)}.")
    settings = get_settings()
    database_url = get_database_url()
    if settings.environment != "production" or database_url.startswith("sqlite"):
        raise RuntimeError("Secure migration requires FLASK_ENV=production and a non-SQLite DATABASE_URL.")
    if report["users"]["rejected_records"] or report["loan_applications"]["rejected_records"]:
        raise RuntimeError("Migration source has rejected records; review the redacted dry-run report before applying.")
    if report["users"]["duplicate_identifiers"] or report["loan_applications"]["duplicate_identifiers"]:
        raise RuntimeError("Migration source has duplicate identifiers; review the redacted dry-run report before applying.")
    _verify_prior_backups(source_directory)
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
        if revision != EXPECTED_REVISION:
            raise RuntimeError("Target database is not at the expected Alembic revision.")
    finally:
        engine.dispose()


def _verify_prior_backups(source_directory: Path) -> None:
    for phase in ("phase5-baseline", "phase6-baseline"):
        for name in ("credvexa_data.json", "credvexa_users.json"):
            source = source_directory / name
            backup = source_directory / "backups" / phase / name
            if not backup.exists() or file_metadata(source)["sha256"] != file_metadata(backup)["sha256"]:
                raise RuntimeError(f"Verified {phase} backup does not match {name}.")


def _summarize_records(records: list[dict], identifier: str) -> dict[str, Any]:
    references = [redact_reference(record.get(identifier, "missing")) for record in records if isinstance(record, dict)]
    return {"source_records": len(records), "candidate_records": len(references), "redacted_references": references}


def _parse_timestamp(value: object) -> datetime | None:
    if not value:
        return None
    return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S")


def _string_or_none(value: object) -> str | None:
    value = str(value or "").strip()
    return value or None


def _int_or_none(value: object) -> int | None:
    return int(value) if value not in (None, "") else None


def _float_or_none(value: object) -> float | None:
    return float(value) if value not in (None, "") else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--backup-dir", type=Path, default=PROJECT_ROOT / "backups" / "phase6-baseline")
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "migration-reports" / "phase6-secure-dry-run.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    arguments = parser.parse_args()
    if arguments.apply and not arguments.confirm:
        raise SystemExit("Refusing migration: --apply requires --confirm.")
    report = migrate(arguments.source_dir, arguments.backup_dir, arguments.apply)
    arguments.report.parent.mkdir(parents=True, exist_ok=True)
    arguments.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"mode": report["mode"], "sql_writes": report["sql_writes"], "report": str(arguments.report)}))


if __name__ == "__main__":
    main()