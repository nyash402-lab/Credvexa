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

    def test_brand_link_routes_visitors_home_and_logged_in_users_to_dashboard(self):
        with credvexa.app.test_client() as client:
            visitor_response = client.get("/brand")
            with client.session_transaction() as session:
                session["logged_in"] = True
            logged_in_response = client.get("/brand")

        self.assertTrue(visitor_response.headers["Location"].endswith("/"))
        self.assertTrue(logged_in_response.headers["Location"].endswith("/dashboard"))

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
            with client.session_transaction() as session:
                session["otp_verified"] = True
                session["candidate_mobile"] = "9000000000"
            response = client.post("/api/applications", json={})

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()["offer_amount"], 67000)
        save_approved_amount.assert_called_once_with("CRX1", 67000)

    def test_dashboard_requires_login_and_filters_to_candidate_records(self):
        with credvexa.app.test_client() as client:
            response = client.get("/api/dashboard")
            self.assertEqual(response.status_code, 401)

            with client.session_transaction() as session:
                session["logged_in"] = True
                session["otp_verified"] = True
                session["candidate_mobile"] = "9000000000"

            with patch("credvexa.load_applications", return_value=[
                {"application_id": "CRX1", "mobile": "9000000000", "full_name": "Alpha", "status": "UNDER_REVIEW"},
                {"application_id": "CRX2", "mobile": "9111111111", "full_name": "Beta", "status": "APPROVED"},
            ]):
                response = client.get("/api/dashboard")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()["applications"]), 1)
        self.assertEqual(response.get_json()["applications"][0]["mobile"], "9000000000")

    def test_application_submission_requires_verified_otp_session(self):
        with credvexa.app.test_client() as client:
            response = client.post("/api/applications", json={})

        self.assertEqual(response.status_code, 401)

    def test_verification_fee_requires_verified_otp_session(self):
        with credvexa.app.test_client() as client:
            response = client.post("/api/pay-verification-fee", json={"amount": 199})

        self.assertEqual(response.status_code, 401)

    def test_create_user_account_hashes_password_before_storage(self):
        original_users_file = credvexa.USERS_FILE
        with tempfile.TemporaryDirectory() as temporary_directory:
            credvexa.USERS_FILE = Path(temporary_directory) / "users.json"
            credvexa.USERS_FILE.write_text("[]", encoding="utf-8")

            user = credvexa.create_user_account({
                "full_name": "Hashed User",
                "email": "hashed@example.com",
                "mobile": "9000000001",
                "password": "StrongPass!123",
            })
            stored_user = credvexa.load_users()[0]

            self.assertNotEqual(stored_user["password"], "StrongPass!123")
            self.assertTrue(credvexa.authenticate_user("hashed@example.com", "StrongPass!123"))
            self.assertIsNotNone(user)

        credvexa.USERS_FILE = original_users_file


if __name__ == "__main__":
    unittest.main()