import os
import re
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

    def _get_csrf_token(self):
        response = self.client.get("/password-reset/request")
        html = response.get_data(as_text=True)
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        self.assertIsNotNone(match, "csrf_token hidden field missing from the form")
        return match.group(1)

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_existing_account_triggers_token_and_email(self, mock_issue_token, mock_send_email):
        response = self.client.post(
            "/password-reset/request",
            data={"email": "known@example.com", "csrf_token": self._get_csrf_token()},
        )

        self.assertEqual(response.status_code, 200)
        mock_issue_token.assert_called_once()
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "known@example.com")

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token")
    def test_unknown_account_does_not_trigger_token_or_email(self, mock_issue_token, mock_send_email):
        response = self.client.post(
            "/password-reset/request",
            data={"email": "unknown@example.com", "csrf_token": self._get_csrf_token()},
        )

        self.assertEqual(response.status_code, 200)
        mock_issue_token.assert_not_called()
        mock_send_email.assert_not_called()

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_response_does_not_leak_account_existence(self, mock_issue_token, mock_send_email):
        known_response = self.client.post(
            "/password-reset/request",
            data={"email": "known@example.com", "csrf_token": self._get_csrf_token()},
        )
        unknown_response = self.client.post(
            "/password-reset/request",
            data={"email": "unknown@example.com", "csrf_token": self._get_csrf_token()},
        )

        known_html = known_response.get_data(as_text=True)
        unknown_html = unknown_response.get_data(as_text=True)

        self.assertNotIn("known@example.com", known_html)
        self.assertNotIn("unknown@example.com", unknown_html)

        known_alert = self._extract_alert(known_html)
        unknown_alert = self._extract_alert(unknown_html)

        self.assertIsNotNone(known_alert)
        self.assertEqual(known_alert, unknown_alert)

    def _seed_mixed_case_user(self):
        from app.db import execute
        from app.security import hash_password

        with self.app.app_context():
            execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                ("John@example.com", "johnuser", "Doe", "John", hash_password("StrongPass123!")),
            )

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_mixed_case_stored_email_is_found_with_mixed_case_domain(self, mock_issue_token, mock_send_email):
        """#92: the domain is normalized like register() does; the reset goes to the stored address."""
        self._seed_mixed_case_user()

        response = self.client.post(
            "/password-reset/request",
            data={"email": "John@Example.com", "csrf_token": self._get_csrf_token()},
        )

        self.assertEqual(response.status_code, 200)
        mock_issue_token.assert_called_once()
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "John@example.com")

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_mixed_case_stored_email_is_found_with_surrounding_spaces(self, mock_issue_token, mock_send_email):
        self._seed_mixed_case_user()

        response = self.client.post(
            "/password-reset/request",
            data={"email": " John@EXAMPLE.com ", "csrf_token": self._get_csrf_token()},
        )

        self.assertEqual(response.status_code, 200)
        mock_issue_token.assert_called_once()
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "John@example.com")

    @patch("app.auth.routes.send_email")
    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_invalid_email_format_gets_generic_response_without_side_effects(self, mock_issue_token, mock_send_email):
        unknown_response = self.client.post(
            "/password-reset/request",
            data={"email": "unknown@example.com", "csrf_token": self._get_csrf_token()},
        )
        generic_alert = self._extract_alert(unknown_response.get_data(as_text=True))
        self.assertIsNotNone(generic_alert)

        for invalid in ("not-an-email", "john@@example.com"):
            with self.subTest(email=invalid):
                response = self.client.post(
                    "/password-reset/request",
                    data={"email": invalid, "csrf_token": self._get_csrf_token()},
                )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self._extract_alert(response.get_data(as_text=True)), generic_alert)

        mock_issue_token.assert_not_called()
        mock_send_email.assert_not_called()

    @patch("app.auth.routes.send_email")
    def test_whitespace_only_email_is_required_error(self, mock_send_email):
        response = self.client.post(
            "/password-reset/request",
            data={"email": "   ", "csrf_token": self._get_csrf_token()},
        )

        self.assertIn("Email is required", response.get_data(as_text=True))
        mock_send_email.assert_not_called()

    @patch("app.auth.routes.issue_signed_token", return_value="fake-token")
    def test_registered_mixed_case_email_can_request_reset(self, mock_issue_token):
        """End to end: an address stored by register() must be reachable by the reset request."""
        with patch("app.auth.routes.send_email"):
            register_page = self.client.get("/register").get_data(as_text=True)
            csrf = re.search(r'name="csrf_token" value="([^"]+)"', register_page).group(1)
            response = self.client.post(
                "/register",
                data={
                    "email": "John@Example.com",
                    "username": "johnreg",
                    "last_name": "Doe",
                    "first_name": "John",
                    "password": "J8#qL2!vX9@p",
                    "confirm": "J8#qL2!vX9@p",
                    "csrf_token": csrf,
                },
            )
            self.assertIn("Account created!", response.get_data(as_text=True))

        with patch("app.auth.routes.send_email") as mock_send_email:
            response = self.client.post(
                "/password-reset/request",
                data={"email": " John@EXAMPLE.com ", "csrf_token": self._get_csrf_token()},
            )

        self.assertEqual(response.status_code, 200)
        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "John@example.com")

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
