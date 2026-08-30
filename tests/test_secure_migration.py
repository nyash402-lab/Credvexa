from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from app.security.crypto import decrypt_sensitive_value, encrypt_sensitive_value, sensitive_digest
from app.security.passwords import hash_legacy_password, verify_password_hash
from scripts.migrate_json_to_sql import build_dry_run_report, migrate


class SecureMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self._write("credvexa_users.json", [{"id": "USR1", "full_name": "Test", "email": "test@example.test", "mobile": "9000000000", "password": "secret", "created_at": "2026-01-01 00:00:00"}])
        self._write("credvexa_data.json", [{"application_id": "CRX1", "full_name": "Test", "mobile": "9000000000", "email": "test@example.test", "pan": "ABCDE1234F", "aadhaar": "123456789012", "monthly_income": 1, "requested_amount": 1, "tenure_months": 1, "loan_purpose": "Test", "city": "Test", "state": "Test", "pin_code": "000000", "status": "UNDER_REVIEW", "emi": 1, "created_at": "2026-01-01 00:00:00", "updated_at": "2026-01-01 00:00:00"}])

    def tearDown(self):
        self.directory.cleanup()

    def _write(self, name: str, content: list[dict]) -> None:
        (self.root / name).write_text(json.dumps(content), encoding="utf-8")

    def test_crypto_and_password_transforms_are_secure(self):
        key = Fernet.generate_key().decode("ascii")
        ciphertext = encrypt_sensitive_value("ABCDE1234F", key)
        self.assertNotIn("ABCDE1234F", ciphertext)
        self.assertEqual(decrypt_sensitive_value(ciphertext, key), "ABCDE1234F")
        self.assertEqual(sensitive_digest("abcde1234f", "key"), sensitive_digest("ABCDE1234F", "key"))
        password_hash = hash_legacy_password("secret")
        self.assertNotIn("secret", password_hash)
        self.assertTrue(verify_password_hash("secret", password_hash))

    def test_dry_run_is_idempotent_and_does_not_require_secrets(self):
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.glob("*.json")}
        with patch.dict(os.environ, {}, clear=True):
            first = migrate(self.root, self.root / "backups", apply=False)
            second = migrate(self.root, self.root / "backups", apply=False)
        self.assertEqual(first, second)
        self.assertEqual(first["sql_writes"], 0)
        self.assertFalse(first["security_readiness"]["field_encryption_key"])
        self.assertEqual(before, {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.root.glob("credvexa_*.json")})

    def test_dry_run_report_has_no_sensitive_values(self):
        with patch.dict(os.environ, {}, clear=True):
            _, _, report = build_dry_run_report(self.root, self.root / "backups")
        rendered = json.dumps(report)
        self.assertNotIn("ABCDE1234F", rendered)
        self.assertNotIn("123456789012", rendered)
        self.assertNotIn("secret", rendered)


if __name__ == "__main__":
    unittest.main()