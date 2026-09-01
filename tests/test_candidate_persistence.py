from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import credvexa

from app.repositories.json_application_repository import JsonApplicationRepository


class CandidatePersistenceTests(unittest.TestCase):
    def test_json_repository_persists_and_retrieves_approved_amount(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            data_file = Path(temporary_directory) / "applications.json"
            data_file.write_text(json.dumps([{"application_id": "CRX1", "mobile": "9000000000"}]), encoding="utf-8")
            repository = JsonApplicationRepository(data_file)

            repository.set_approved_amount("CRX1", 67000)

            self.assertEqual(repository.find_latest_by_mobile("9000000000")["approved_amount"], 67000)

    def test_existing_login_restores_saved_approved_amount(self):
        candidate = {"full_name": "Test User", "email": "test@example.test", "mobile": "9000000000"}
        with credvexa.app.test_client() as client, \
                patch("credvexa.authenticate_user", return_value=candidate), \
                patch("credvexa.get_saved_approved_amount", return_value=67000):
            response = client.post("/api/login", json={"mobile": "9000000000", "password": "password"})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["user"]["mobile"], "9000000000")
            with client.session_transaction() as session:
                self.assertEqual(session["pre_offer_amount"], 67000)

    def test_verified_widget_flow_restores_saved_approved_amount(self):
        with credvexa.app.test_client() as client, \
                patch("credvexa.verify_msg91_widget_access_token", return_value={"type": "success", "data": {"mobile": "9000000000"}}), \
                patch("credvexa.get_reapply_block", return_value={"blocked": False, "days_remaining": 0, "reason": ""}), \
                patch("credvexa.get_preapproved_offer_for_candidate", return_value={"offer_amount": 50000, "max_tenure_months": 60, "rate": 11.5}), \
                patch("credvexa.get_saved_approved_amount", return_value=67000):
            response = client.post("/api/verify-msg91-widget-token", json={"mobile": "9000000000", "accessToken": "test-token"})

        self.assertEqual(response.status_code, 200)
        with client.session_transaction() as session:
            self.assertEqual(session["pre_offer_amount"], 67000)

    def test_existing_submission_saves_generated_approved_amount(self):
        application = {"application_id": "CRX1", "age": 25, "status": "UNDER_REVIEW", "emi": 1000, "note": "Test"}
        with credvexa.app.test_client() as client, \
                patch("credvexa.create_application", return_value=application), \
                patch("credvexa.generate_age_based_offer", return_value=67000), \
                patch("credvexa.save_approved_amount", return_value=True) as save_approved_amount:
            response = client.post("/api/applications", json={})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["offer_amount"], 67000)
        save_approved_amount.assert_called_once_with("CRX1", 67000)


if __name__ == "__main__":
    unittest.main()