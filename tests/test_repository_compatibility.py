from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
import app.models  # noqa: F401
from app.repositories.json_application_repository import JsonApplicationRepository
from app.repositories.json_user_repository import JsonUserRepository
from app.repositories.provider import get_application_repository, get_user_repository
from app.repositories.sqlalchemy_application_repository import SqlAlchemyApplicationRepository
from app.repositories.sqlalchemy_user_repository import SqlAlchemyUserRepository


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APPLICATIONS_FILE = PROJECT_ROOT / "credvexa_data.json"
USERS_FILE = PROJECT_ROOT / "credvexa_users.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RepositoryCompatibilityTests(unittest.TestCase):
    def test_json_repositories_match_existing_files_without_writing(self):
        before = {APPLICATIONS_FILE: digest(APPLICATIONS_FILE), USERS_FILE: digest(USERS_FILE)}
        self.assertEqual(JsonApplicationRepository(APPLICATIONS_FILE).load_all(), json.loads(APPLICATIONS_FILE.read_text(encoding="utf-8")))
        self.assertEqual(JsonUserRepository(USERS_FILE).load_all(), json.loads(USERS_FILE.read_text(encoding="utf-8")))
        self.assertEqual(before, {APPLICATIONS_FILE: digest(APPLICATIONS_FILE), USERS_FILE: digest(USERS_FILE)})

    def test_provider_defaults_to_json(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsInstance(get_application_repository(), JsonApplicationRepository)
            self.assertIsInstance(get_user_repository(), JsonUserRepository)

    def test_sql_repositories_work_against_isolated_database(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            database_path = Path(temporary_directory) / "repositories.db"
            engine = create_engine(f"sqlite:///{database_path.as_posix()}")
            try:
                Base.metadata.create_all(engine)
                session = sessionmaker(bind=engine)()
                try:
                    users = SqlAlchemyUserRepository(session)
                    user = users.add({
                        "legacy_user_id": "USR9999",
                        "full_name": "Repository Test",
                        "email": "repository@example.test",
                        "mobile": "9000000000",
                        "password_hash": "not-a-real-password-hash",
                    })
                    self.assertEqual(users.get_by_email_or_mobile("9000000000").id, user.id)

                    applications = SqlAlchemyApplicationRepository(session)
                    application = applications.add({
                        "user_id": user.id,
                        "application_id": "CRXTEST0001",
                        "full_name": "Repository Test",
                        "mobile": "9000000000",
                        "status": "UNDER_REVIEW",
                        "pan_ciphertext": "test-only-opaque-value",
                        "aadhaar_ciphertext": "test-only-opaque-value",
                    })
                    self.assertEqual(applications.get_by_application_id("CRXTEST0001").id, application.id)
                finally:
                    session.close()
            finally:
                engine.dispose()

    def test_legacy_module_does_not_import_new_repositories(self):
        source = (PROJECT_ROOT / "credvexa.py").read_text(encoding="utf-8")
        self.assertNotIn("app.repositories", source)


if __name__ == "__main__":
    unittest.main()