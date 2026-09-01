from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import credvexa


class OtpModeTests(unittest.TestCase):
    mobile = "9000000000"

    def setUp(self):
        self.original_demo_mode = credvexa.settings.otp_demo_mode
        credvexa.OTP_STORAGE.clear()

    def tearDown(self):
        credvexa.OTP_STORAGE.clear()
        object.__setattr__(credvexa.settings, "otp_demo_mode", self.original_demo_mode)

    def test_demo_mode_returns_and_accepts_local_demo_otp(self):
        object.__setattr__(credvexa.settings, "otp_demo_mode", True)

        with credvexa.app.test_client() as client:
            send_response = client.post("/api/send-otp", json={"mobile": self.mobile})
            body = send_response.get_json()

            self.assertEqual(send_response.status_code, 200)
            self.assertTrue(body["demo"])
            self.assertRegex(body["demo_otp"], r"^\d{6}$")
            self.assertNotIn("otp", body)

            with patch("credvexa.get_reapply_block", return_value={"blocked": False, "days_remaining": 0, "reason": ""}), \
                    patch("credvexa.get_preapproved_offer_for_candidate", return_value={"offer_amount": 50000, "max_tenure_months": 60, "rate": 11.5}), \
                    patch("credvexa.get_saved_approved_amount", return_value=None):
                verify_response = client.post("/api/verify-otp", json={"mobile": self.mobile, "otp": body["demo_otp"]})

        self.assertEqual(verify_response.status_code, 200)

    def test_production_mode_never_returns_otp_and_uses_msg91_send(self):
        object.__setattr__(credvexa.settings, "otp_demo_mode", False)

        with credvexa.app.test_client() as client, patch("credvexa.send_msg91_otp") as send_msg91:
            response = client.post("/api/send-otp", json={"mobile": self.mobile})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"message": "OTP sent successfully."})
        send_msg91.assert_called_once_with(self.mobile)
        self.assertNotIn(self.mobile, credvexa.OTP_STORAGE)

    def test_production_mode_rejects_msg91_send_failure_without_disclosing_otp(self):
        object.__setattr__(credvexa.settings, "otp_demo_mode", False)

        with credvexa.app.test_client() as client, patch("credvexa.send_msg91_otp", side_effect=RuntimeError("provider unavailable")):
            response = client.post("/api/send-otp", json={"mobile": self.mobile})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "Unable to send OTP right now. Please try again later."})

    def test_production_mode_requires_msg91_verification(self):
        object.__setattr__(credvexa.settings, "otp_demo_mode", False)

        with credvexa.app.test_client() as client, patch("credvexa.verify_msg91_otp", side_effect=RuntimeError("provider unavailable")):
            response = client.post("/api/verify-otp", json={"mobile": self.mobile, "otp": "123456"})

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(), {"error": "Unable to verify OTP right now. Please try again later."})

    def test_production_page_does_not_render_demo_otp_ui(self):
        object.__setattr__(credvexa.settings, "otp_demo_mode", False)

        with credvexa.app.test_client() as client:
            response = client.get("/verify-login")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Demo OTP", response.data)
        self.assertNotIn(b"Demo flow", response.data)


if __name__ == "__main__":
    unittest.main()