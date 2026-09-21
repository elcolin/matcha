import os
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config


class PasswordResetRequestTests(unittest.TestCase):
    """Regression tests for the account-enumeration bug in
    app/auth/routes.py::request_password_reset.

    The route used to `return` before generating the reset token / sending
    the email, and it leaked whether an email was registered by returning a
    different message depending on account existence. Both issues must be
    fixed: the token/email flow must always run for an existing account, and
    the HTTP response must be indistinguishable between an existing and a
    non-existing account.
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

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_existing_account_triggers_token_and_email(self, mock_issue_token, mock_send_email):
        response = self.client.post(
            "/password-reset/request", data={"email": "known@example.com"}
        )

        self.assertEqual(response.status_code, 200)
        mock_issue_token.assert_called_once()
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "known@example.com")

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token")
    def test_unknown_account_does_not_trigger_token_or_email(self, mock_issue_token, mock_send_email):
        response = self.client.post(
            "/password-reset/request", data={"email": "unknown@example.com"}
        )

        self.assertEqual(response.status_code, 200)
        mock_issue_token.assert_not_called()
        mock_send_email.assert_not_called()

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_response_does_not_leak_account_existence(self, mock_issue_token, mock_send_email):
        known_response = self.client.post(
            "/password-reset/request", data={"email": "known@example.com"}
        )
        unknown_response = self.client.post(
            "/password-reset/request", data={"email": "unknown@example.com"}
        )

        known_html = known_response.get_data(as_text=True)
        unknown_html = unknown_response.get_data(as_text=True)

        self.assertNotIn("known@example.com", known_html)
        self.assertNotIn("unknown@example.com", unknown_html)

        known_alert = self._extract_alert(known_html)
        unknown_alert = self._extract_alert(unknown_html)

        self.assertIsNotNone(known_alert)
        self.assertEqual(known_alert, unknown_alert)

    @staticmethod
    def _extract_alert(html):
        for marker in ("alert-success", "alert-danger"):
            start = html.find(marker)
            if start == -1:
                continue
            # Grab the text between the opening ">" following the class and the closing "</div>".
            content_start = html.find(">", start) + 1
            content_end = html.find("</div>", content_start)
            return html[content_start:content_end].strip()
        return None


if __name__ == "__main__":
    unittest.main()
