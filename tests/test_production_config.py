from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from flask import Flask

from app.config import get_database_url, get_settings
from app.database import init_database


class ProductionConfigTests(unittest.TestCase):
    def test_development_defaults_preserve_local_server_behavior(self):
        with patch.dict(os.environ, {"FLASK_ENV": "development"}, clear=True):
            settings = get_settings()
        self.assertTrue(settings.debug)
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertEqual(settings.port, 5000)
        self.assertFalse(settings.session_cookie_secure)
        self.assertNotEqual(settings.secret_key, "credvexa-demo-session-key")

    def test_production_requires_secret_key(self):
        with patch.dict(os.environ, {"FLASK_ENV": "production"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
                get_settings()

    def test_production_settings_enable_secure_cookies(self):
        environment = {
            "FLASK_ENV": "production",
            "SECRET_KEY": "test-secret-key",
            "PORT": "8080",
        }
        with patch.dict(os.environ, environment, clear=True):
            settings = get_settings()
        self.assertFalse(settings.debug)
        self.assertEqual(settings.host, "0.0.0.0")
        self.assertEqual(settings.port, 8080)
        self.assertTrue(settings.session_cookie_secure)

    def test_production_missing_database_is_graceful(self):
        with patch.dict(os.environ, {"FLASK_ENV": "production", "SECRET_KEY": "test-secret-key"}, clear=True):
            app = Flask(__name__)
            init_database(app)
        self.assertFalse(app.config["DATABASE_READY"])
        self.assertIn("JSON storage remains active", app.config["DATABASE_ERROR"])

    def test_render_postgres_url_is_normalized(self):
        with patch.dict(os.environ, {"DATABASE_URL": "postgres://user:pass@host/database"}, clear=True):
            self.assertEqual(get_database_url(), "postgresql+psycopg://user:pass@host/database")


if __name__ == "__main__":
    unittest.main()