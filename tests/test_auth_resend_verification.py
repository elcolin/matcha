import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.config import Config

GENERIC_MESSAGE = "If an account exists with this email and is not yet verified, a new verification link has been sent."


class ResendVerificationEmailTests(unittest.TestCase):
    """Issue #9: a user whose verification link was lost/expired must be able
    to request a new one, without the endpoint leaking account existence."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app
        from app.db import execute
        from app.security import hash_password, issue_signed_token

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        with self.app.app_context():
            self.unverified_id = execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 0)",
                ("unverified@example.com", "unverified", "Doe", "Jane", hash_password("StrongPass123!")),
            ).lastrowid
            self.verified_id = execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                ("verified@example.com", "verified", "Roe", "John", hash_password("StrongPass123!")),
            ).lastrowid

            secret = self.app.config["SECRET_KEY"]
            self.old_token = issue_signed_token(secret, "verify_email", self.unverified_id)
            execute(
                "INSERT INTO email_verifications (user_id, token, expires_at) VALUES (?, ?, ?)",
                (self.unverified_id, self.old_token, future),
            )
            self.used_token = issue_signed_token(secret, "verify_email", self.unverified_id)
            self.used_at_original = "2020-01-01T00:00:00+00:00"
            execute(
                "INSERT INTO email_verifications (user_id, token, expires_at, used_at) VALUES (?, ?, ?, ?)",
                (self.unverified_id, self.used_token, future, self.used_at_original),
            )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _get_csrf_token(self):
        html = self.client.get("/resend-verification").get_data(as_text=True)
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "csrf_token hidden field missing from the form")
        return match.group(1)

    def _post(self, email):
        return self.client.post(
            "/resend-verification",
            data={"email": email, "csrf_token": self._get_csrf_token()},
        )

    def _verifications(self, user_id):
        from app.db import query_all

        with self.app.app_context():
            return query_all(
                "SELECT token, used_at FROM email_verifications WHERE user_id = ? ORDER BY id",
                (user_id,),
            )

    def _verification_count(self):
        from app.db import query_one

        with self.app.app_context():
            return query_one("SELECT COUNT(*) AS n FROM email_verifications")["n"]

    @staticmethod
    def _extract_alert(html):
        for marker in ("alert-success", "alert-danger"):
            start = html.find(marker)
            if start == -1:
                continue
            content_start = html.find(">", start) + 1
            content_end = html.find("</div>", content_start)
            return html[content_start:content_end].strip()
        return None

    def test_get_renders_form_with_csrf_field(self):
        response = self.client.get("/resend-verification")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertRegex(html, r'name="csrf_token" value="[^"]+"')
        self.assertIn('name="email"', html)

    @patch("app.auth.routes.send_email")
    def test_unverified_email_sends_new_link(self, mock_send_email):
        response = self._post("unverified@example.com")

        self.assertEqual(response.status_code, 200)
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "unverified@example.com")
        rows = self._verifications(self.unverified_id)
        self.assertEqual(len(rows), 3)
        self.assertIsNone(rows[-1]["used_at"])
        self.assertEqual(self._extract_alert(response.get_data(as_text=True)), GENERIC_MESSAGE)

    @patch("app.auth.routes.send_email")
    def test_previous_unused_tokens_are_invalidated(self, mock_send_email):
        self._post("unverified@example.com")

        rows = {r["token"]: r["used_at"] for r in self._verifications(self.unverified_id)}
        self.assertIsNotNone(rows[self.old_token])
        self.assertEqual(rows[self.used_token], self.used_at_original)

    @patch("app.auth.routes.send_email")
    def test_old_token_rejected_and_new_token_works(self, mock_send_email):
        self._post("unverified@example.com")
        new_token = self._verifications(self.unverified_id)[-1]["token"]

        self.assertEqual(self.client.get(f"/verify-email/{self.old_token}").status_code, 400)

        response = self.client.get(f"/verify-email/{new_token}")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])
        from app.db import query_one

        with self.app.app_context():
            user = query_one("SELECT email_verified FROM users WHERE id = ?", (self.unverified_id,))
        self.assertEqual(user["email_verified"], 1)

    @patch("app.auth.routes.send_email")
    def test_verified_email_does_nothing(self, mock_send_email):
        before = self._verification_count()

        response = self._post("verified@example.com")

        self.assertEqual(response.status_code, 200)
        mock_send_email.assert_not_called()
        self.assertEqual(self._verification_count(), before)
        self.assertEqual(self._extract_alert(response.get_data(as_text=True)), GENERIC_MESSAGE)

    @patch("app.auth.routes.send_email")
    def test_unknown_email_does_nothing(self, mock_send_email):
        before = self._verification_count()

        response = self._post("nobody@example.com")

        self.assertEqual(response.status_code, 200)
        mock_send_email.assert_not_called()
        self.assertEqual(self._verification_count(), before)
        self.assertEqual(self._extract_alert(response.get_data(as_text=True)), GENERIC_MESSAGE)

    @patch("app.auth.routes.send_email")
    def test_responses_are_indistinguishable(self, mock_send_email):
        responses = [self._post(e) for e in ("unverified@example.com", "verified@example.com", "nobody@example.com")]

        self.assertEqual({r.status_code for r in responses}, {200})
        alerts = {self._extract_alert(r.get_data(as_text=True)) for r in responses}
        self.assertEqual(alerts, {GENERIC_MESSAGE})

    @patch("app.auth.routes.send_email")
    def test_empty_email_is_rejected(self, mock_send_email):
        before = self._verification_count()

        response = self._post("   ")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Email is required", response.get_data(as_text=True))
        mock_send_email.assert_not_called()
        self.assertEqual(self._verification_count(), before)

    @patch("app.auth.routes.send_email")
    def test_invalid_email_is_rejected(self, mock_send_email):
        before = self._verification_count()

        response = self._post("not-an-email")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid email address", response.get_data(as_text=True))
        mock_send_email.assert_not_called()
        self.assertEqual(self._verification_count(), before)

    @patch("app.auth.routes.send_email")
    def test_email_is_normalized_like_register(self, mock_send_email):
        self._post("  unverified@EXAMPLE.COM  ")

        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "unverified@example.com")

    @patch("app.auth.routes.send_email", side_effect=RuntimeError("SMTP down"))
    def test_smtp_failure_returns_generic_response(self, mock_send_email):
        response = self._post("unverified@example.com")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertEqual(self._extract_alert(html), GENERIC_MESSAGE)
        self.assertNotIn("unverified@example.com", html)

    @patch("app.auth.routes.send_email")
    def test_post_without_csrf_token_is_rejected(self, mock_send_email):
        self.client.get("/resend-verification")

        response = self.client.post("/resend-verification", data={"email": "unverified@example.com"})

        self.assertEqual(response.status_code, 403)
        mock_send_email.assert_not_called()

    @patch("app.auth.routes.send_email")
    def test_post_with_wrong_csrf_token_is_rejected(self, mock_send_email):
        self.client.get("/resend-verification")

        response = self.client.post(
            "/resend-verification",
            data={"email": "unverified@example.com", "csrf_token": "not-the-right-token"},
        )

        self.assertEqual(response.status_code, 403)
        mock_send_email.assert_not_called()

    def test_login_with_unverified_account_links_to_resend(self):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

        response = self.client.post(
            "/login",
            data={"username": "unverified", "password": "StrongPass123!", "csrf_token": token},
        )

        html = response.get_data(as_text=True)
        self.assertIn("Please verify your email before logging in", html)
        self.assertIn('href="/resend-verification"', html)


if __name__ == "__main__":
    unittest.main()
