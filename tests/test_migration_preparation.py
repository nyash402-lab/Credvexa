from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_json_migration import build_report, prepare


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MigrationPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.applications_path = self.root / "credvexa_data.json"
        self.users_path = self.root / "credvexa_users.json"
        self.applications_path.write_text(json.dumps([{
            "application_id": "CRXTEST01", "full_name": "Test Applicant", "dob": "2000-01-01", "age": 25,
            "mobile": "9000000000", "email": "applicant@example.test", "pan": "ABCDE1234F", "aadhaar": "123456789012",
            "employment_type": "Salaried", "monthly_income": 50000, "requested_amount": 100000,
            "tenure_months": 12, "loan_purpose": "Medical", "city": "Delhi", "state": "Delhi", "pin_code": "110001",
            "status": "UNDER_REVIEW", "emi": 8886.0, "note": "Test", "created_at": "2026-01-01 10:00:00", "updated_at": "2026-01-01 10:00:00",
        }]), encoding="utf-8")
        self.users_path.write_text(json.dumps([{
            "id": "USR0001", "full_name": "Test Applicant", "email": "applicant@example.test",
            "mobile": "9000000000", "password": "plain-text-secret", "created_at": "2026-01-01 10:00:00",
        }]), encoding="utf-8")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_prepare_is_idempotent_and_preserves_source_bytes(self):
        before = {self.applications_path: digest(self.applications_path), self.users_path: digest(self.users_path)}
        backup_directory = self.root / "backups"
        report_path = self.root / "report.json"
        first = prepare(self.root, backup_directory, report_path)
        second = prepare(self.root, backup_directory, report_path)
        self.assertEqual(first, second)
        self.assertEqual(before, {self.applications_path: digest(self.applications_path), self.users_path: digest(self.users_path)})
        self.assertEqual(first["sql_writes"], 0)

    def test_report_redacts_sensitive_values_and_maps_expected_fields(self):
        report = prepare(self.root, self.root / "backups", self.root / "report.json")
        encoded_report = json.dumps(report)
        for sensitive_value in ("ABCDE1234F", "123456789012", "plain-text-secret"):
            self.assertNotIn(sensitive_value, encoded_report)
        self.assertEqual(report["users"]["field_mapping"]["id"], "legacy_user_id")
        self.assertEqual(report["loan_applications"]["field_mapping"]["application_id"], "application_id")
        self.assertEqual(len(report["users"]["manual_review_records"]), 1)
        self.assertEqual(len(report["loan_applications"]["manual_review_records"]), 1)

    def test_malformed_and_duplicate_records_are_reported(self):
        report = build_report(
            [{"application_id": "DUP"}, {"application_id": "DUP"}, "not-a-record"],
            [{"id": "USR", "mobile": "9000000000"}, {"id": "USR", "mobile": "9000000000"}],
            {},
        )
        self.assertGreater(len(report["users"]["rejected_records"]), 0)
        self.assertGreater(len(report["loan_applications"]["rejected_records"]), 0)
        self.assertGreater(len(report["users"]["duplicate_identifiers"]), 0)
        self.assertGreater(len(report["loan_applications"]["duplicate_identifiers"]), 0)

    def test_malformed_json_raises_without_changing_source(self):
        before = digest(self.applications_path)
        self.applications_path.write_text("{broken", encoding="utf-8")
        malformed_digest = digest(self.applications_path)
        with self.assertRaises(ValueError):
            prepare(self.root, self.root / "backups", self.root / "report.json")
        self.assertEqual(malformed_digest, digest(self.applications_path))
        self.assertNotEqual(before, malformed_digest)


if __name__ == "__main__":
    unittest.main()