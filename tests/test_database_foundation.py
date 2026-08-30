from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILES = [PROJECT_ROOT / "credvexa_data.json", PROJECT_ROOT / "credvexa_users.json"]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DatabaseFoundationTests(unittest.TestCase):
    def test_migration_creates_only_foundation_tables(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "foundation.db"
            environment = os.environ.copy()
            environment["DATABASE_URL"] = f"sqlite:///{database_path.as_posix()}"
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=PROJECT_ROOT,
                env=environment,
                check=True,
                capture_output=True,
                text=True,
            )
            engine = create_engine(environment["DATABASE_URL"])
            try:
                inspector = inspect(engine)
                self.assertEqual(
                    set(inspector.get_table_names()),
                    {"alembic_version", "application_events", "loan_applications", "otp_challenges", "users"},
                )
                self.assertTrue(inspector.get_foreign_keys("application_events"))
                self.assertTrue(inspector.get_foreign_keys("loan_applications"))
                self.assertTrue(inspector.get_foreign_keys("otp_challenges"))
            finally:
                engine.dispose()

    def test_importing_app_does_not_change_json_storage(self):
        before = {path: file_digest(path) for path in DATA_FILES}
        environment = os.environ.copy()
        environment["DATABASE_URL"] = "sqlite:///:memory:"
        subprocess.run(
            [sys.executable, "-c", "import credvexa; assert credvexa.app.config['DATABASE_READY']"],
            cwd=PROJECT_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        after = {path: file_digest(path) for path in DATA_FILES}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()