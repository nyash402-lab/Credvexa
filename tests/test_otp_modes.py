from __future__ import annotations

import unittest
from unittest.mock import patch

import credvexa


class LiveOtpWidgetTests(unittest.TestCase):
    mobile = "9000000000"

    def test_verify_login_renders_live_msg91_widget_flow(self):
        with credvexa.app.test_client() as client, \
                patch("credvexa.MSG91_OTP_WIDGET_ID", "widget-id-for-test"), \
                patch("credvexa.MSG91_OTP_WIDGET_TOKEN_AUTH", "token-auth-for-test"):
            response = client.get("/verify-login")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"https://verify.msg91.com/otp-provider.js", response.data)
        self.assertIn(b"initSendOTP(configuration)", response.data)
        self.assertIn(b"exposeMethods: true", response.data)
        self.assertIn(b"window.sendOtp", response.data)
        self.assertIn(b"window.verifyOtp", response.data)
        self.assertIn(b"window.retryOtp", response.data)
        self.assertIn(b"/api/verify-msg91-widget-token", response.data)
        self.assertNotIn(b"demo_otp", response.data)
        self.assertNotIn(b"/api/send-otp", response.data)
        self.assertNotIn(b"/api/verify-otp", response.data)

    def test_widget_token_verification_rejects_missing_token(self):
        with credvexa.app.test_client() as client:
            response = client.post("/api/verify-msg91-widget-token", json={"mobile": self.mobile})

        self.assertEqual(response.status_code, 400)

    def test_widget_token_verification_rejects_invalid_token(self):
        with credvexa.app.test_client() as client, \
                patch("credvexa.verify_msg91_widget_access_token", side_effect=ValueError("invalid")):
            response = client.post("/api/verify-msg91-widget-token", json={"mobile": self.mobile, "accessToken": "test-token"})

        self.assertEqual(response.status_code, 401)

    def test_widget_token_verification_rejects_mobile_mismatch(self):
        with credvexa.app.test_client() as client, \
                patch("credvexa.verify_msg91_widget_access_token", return_value={"type": "success", "data": {"mobile": "9111111111"}}):
            response = client.post("/api/verify-msg91-widget-token", json={"mobile": self.mobile, "accessToken": "test-token"})

        self.assertEqual(response.status_code, 401)

    def test_widget_token_verification_authorizes_application_flow(self):
        with credvexa.app.test_client() as client, \
                patch("credvexa.verify_msg91_widget_access_token", return_value={"type": "success", "data": {"mobile": self.mobile}}), \
                patch("credvexa.get_reapply_block", return_value={"blocked": False, "days_remaining": 0, "reason": ""}), \
                patch("credvexa.get_preapproved_offer_for_candidate", return_value={"offer_amount": 50000}), \
                patch("credvexa.get_saved_approved_amount", return_value=None):
            response = client.post("/api/verify-msg91-widget-token", json={"mobile": self.mobile, "accessToken": "test-token"})
            apply_response = client.get("/apply")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["next_url"], "/apply")
        self.assertEqual(apply_response.status_code, 200)

    def test_apply_requires_server_verified_otp_session(self):
        with credvexa.app.test_client() as client:
            response = client.get("/apply")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/verify-login"))


if __name__ == "__main__":
    unittest.main()