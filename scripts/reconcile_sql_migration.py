"""Read-only reconciliation of a controlled SQL migration against JSON source data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts.prepare_json_migration import load_records
except ModuleNotFoundError:
    from prepare_json_migration import load_records


def reconcile(source_directory: Path) -> dict:
    users = load_records(source_directory / "credvexa_users.json")
    applications = load_records(source_directory / "credvexa_data.json")
    from flask import Flask
    from app.database import SessionLocal, get_engine, init_database
    from app.models.loan_application import LoanApplication
    from app.models.user import User
    from app.security.crypto import decrypt_sensitive_value, sensitive_digest
    from app.security.passwords import is_argon2id_hash, verify_password_hash

    migration_app = Flask("migration_reconciliation")
    init_database(migration_app)
    get_engine()
    database_session = SessionLocal()
    try:
        sql_users = {item.legacy_user_id: item for item in database_session.query(User).all() if item.legacy_user_id}
        sql_applications = {item.application_id: item for item in database_session.query(LoanApplication).all()}
    finally:
        database_session.close()
    json_users = {str(record.get("id", "")).strip(): record for record in users if isinstance(record, dict)}
    json_applications = {str(record.get("application_id", "")).strip(): record for record in applications if isinstance(record, dict)}
    user_hash_failures = [record_id for record_id, record in json_users.items() if record_id in sql_users and not (is_argon2id_hash(sql_users[record_id].password_hash) and verify_password_hash(str(record["password"]), sql_users[record_id].password_hash))]
    application_security_failures = []
    for record_id, record in json_applications.items():
        application = sql_applications.get(record_id)
        if application is None:
            continue
        try:
            valid = (
                decrypt_sensitive_value(application.pan_ciphertext) == str(record.get("pan", ""))
                and decrypt_sensitive_value(application.aadhaar_ciphertext) == str(record.get("aadhaar", ""))
                and application.pan_digest == sensitive_digest(str(record.get("pan", "")))
                and application.aadhaar_digest == sensitive_digest(str(record.get("aadhaar", "")))
            )
        except (RuntimeError, ValueError):
            valid = False
        if not valid:
            application_security_failures.append(record_id)
    relationship_issues = [record_id for record_id, record in json_applications.items() if record_id in sql_applications and sql_applications[record_id].user_id is None and any(str(user.get("mobile", "")).strip() == str(record.get("mobile", "")).strip() for user in json_users.values())]
    return {
        "mode": "read_only_reconciliation", "sql_writes": 0,
        "users": {"json_count": len(json_users), "sql_count": len(sql_users), "missing_in_sql": len(set(json_users) - set(sql_users)), "invalid_password_hashes": len(user_hash_failures)},
        "loan_applications": {"json_count": len(json_applications), "sql_count": len(sql_applications), "missing_in_sql": len(set(json_applications) - set(sql_applications)), "encryption_or_digest_failures": len(application_security_failures), "relationship_issues": len(relationship_issues)},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=PROJECT_ROOT)
    arguments = parser.parse_args()
    print(json.dumps(reconcile(arguments.source_dir), sort_keys=True))


if __name__ == "__main__":
    main()