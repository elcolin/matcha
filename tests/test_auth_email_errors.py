import os
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config


class EmailFailureDoesNotLeakTests(unittest.TestCase):
    """Regression tests for issue #61: a failing send_email() call must never
    surface as a distinguishable HTTP status/exception between an existing
    and a non-existing account. Both request_password_reset and the signup
    flow (send_verification_email) call send_email synchronously; a raised
    exception there must be caught and logged, not propagated.
    """

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app
        from app.db import execute
        from app.security import hash_password

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                ("known@example.com", "knownuser", "Doe", "Jane", hash_password("StrongPass123!")),
            )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    @patch("app.auth.routes.send_email", side_effect=RuntimeError("SMTP misconfigured"))
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_password_reset_smtp_failure_still_returns_generic_success(self, mock_issue_token, mock_send_email):
        response = self.client.post(
            "/password-reset/request", data={"email": "known@example.com"}
        )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn(
            "If an account exists with this email, a reset link has been sent.",
            html,
        )

    @patch("app.auth.routes.send_email", side_effect=RuntimeError("SMTP misconfigured"))
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_password_reset_smtp_failure_matches_unknown_account_status(self, mock_issue_token, mock_send_email):
        known_response = self.client.post(
            "/password-reset/request", data={"email": "known@example.com"}
        )
        unknown_response = self.client.post(
            "/password-reset/request", data={"email": "unknown@example.com"}
        )

        self.assertEqual(known_response.status_code, unknown_response.status_code)
        self.assertEqual(known_response.status_code, 200)

    @patch("app.auth.routes.send_email", side_effect=RuntimeError("SMTP misconfigured"))
    def test_register_smtp_failure_still_creates_account_and_returns_success(self, mock_send_email):
        response = self.client.post(
            "/register",
            data={
                "email": "newuser@example.com",
                "username": "newuser",
                "last_name": "Doe",
                "first_name": "John",
                "password": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Account created!", html)

        from app.db import query_one

        with self.app.app_context():
            user = query_one("SELECT id, email_verified FROM users WHERE username = ?", ("newuser",))
        self.assertIsNotNone(user)
        self.assertEqual(user["email_verified"], 0)


if __name__ == "__main__":
    unittest.main()
