import os
import re
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.config import Config


def _fake_validate_email(email):
    """Stand-in for email_validator.validate_email that skips the real DNS
    deliverability check (unavailable/flaky in tests) but mirrors the
    normalization (lowercasing) behavior request_email_change relies on."""
    result = MagicMock()
    result.normalized = email.lower()
    return result


class ProfileEmailChangeRequestTests(unittest.TestCase):
    """Covers the HTTP-level part of the deferred email change flow: submitting
    a new email from /profile/edit must never touch users.email immediately,
    must send a confirmation email to the NEW address (see
    app.auth.routes.confirm_email_change for the confirmation step), and must
    never surface an SMTP failure as a 500 or leak the email in logs.
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
                ("old@example.com", "alice", "Doe", "Alice", hash_password("StrongPass123!")),
            )
            execute(
                "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES "
                "((SELECT id FROM users WHERE username = 'alice'), 'everyone', '')",
            )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _login_and_get_token(self):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.client.post(
            "/login",
            data={"username": "alice", "password": "StrongPass123!", "csrf_token": token},
        )
        html = self.client.get("/profile/edit").get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def _submit_email_change(self, new_email, csrf_token):
        return self.client.post(
            "/profile/edit",
            data={
                "first_name": "Alice",
                "last_name": "Doe",
                "email": new_email,
                "csrf_token": csrf_token,
            },
        )

    @patch("app.profile.data.validate_email", side_effect=_fake_validate_email)
    @patch("app.profile.routes.send_email")
    def test_new_email_is_not_applied_immediately_and_sends_confirmation_to_new_address(
        self, mock_send_email, mock_validate
    ):
        token = self._login_and_get_token()

        response = self._submit_email_change("new@example.com", token)

        self.assertEqual(response.status_code, 302)

        from app.db import query_one

        with self.app.app_context():
            row = query_one("SELECT email FROM users WHERE username = 'alice'")
            pending = query_one(
                "SELECT new_email FROM email_changes WHERE user_id = (SELECT id FROM users WHERE username = 'alice')"
            )

        self.assertEqual(row["email"], "old@example.com")
        self.assertIsNotNone(pending)
        self.assertEqual(pending["new_email"], "new@example.com")

        mock_send_email.assert_called_once()
        self.assertEqual(mock_send_email.call_args[0][0], "new@example.com")

    @patch("app.profile.data.validate_email", side_effect=_fake_validate_email)
    @patch("app.profile.routes.send_email")
    def test_same_email_as_active_is_a_silent_no_op(self, mock_send_email, mock_validate):
        token = self._login_and_get_token()

        response = self._submit_email_change("old@example.com", token)

        self.assertEqual(response.status_code, 302)
        mock_send_email.assert_not_called()

        from app.db import query_one

        with self.app.app_context():
            pending = query_one(
                "SELECT 1 FROM email_changes WHERE user_id = (SELECT id FROM users WHERE username = 'alice')"
            )
        self.assertIsNone(pending)

    @patch("app.profile.data.validate_email", side_effect=_fake_validate_email)
    @patch("app.profile.routes.send_email", side_effect=RuntimeError("SMTP misconfigured"))
    def test_smtp_failure_is_swallowed_and_does_not_return_500(self, mock_send_email, mock_validate):
        token = self._login_and_get_token()

        with self.assertLogs("app", level="ERROR") as logs:
            response = self._submit_email_change("new@example.com", token)

        self.assertEqual(response.status_code, 302)
        mock_send_email.assert_called_once()

        # The failure must be logged with the user id only, never the raw email address.
        joined_logs = "\n".join(logs.output)
        self.assertNotIn("new@example.com", joined_logs)

    @patch("app.profile.data.validate_email", side_effect=_fake_validate_email)
    @patch("app.profile.routes.send_email")
    def test_second_request_before_confirmation_supersedes_the_first(self, mock_send_email, mock_validate):
        token = self._login_and_get_token()
        self._submit_email_change("first@example.com", token)

        token = self._login_and_get_token()
        self._submit_email_change("second@example.com", token)

        from app.db import query_all

        with self.app.app_context():
            rows = query_all(
                "SELECT new_email, used_at FROM email_changes "
                "WHERE user_id = (SELECT id FROM users WHERE username = 'alice') ORDER BY id ASC"
            )

        self.assertEqual(len(rows), 2)
        self.assertIsNotNone(rows[0]["used_at"])
        self.assertIsNone(rows[1]["used_at"])
        self.assertEqual(rows[1]["new_email"], "second@example.com")

    @patch("app.profile.data.validate_email", side_effect=_fake_validate_email)
    @patch("app.profile.routes.send_email")
    def test_taken_email_yields_the_same_response_as_an_available_one(
        self, mock_send_email, mock_validate
    ):
        """A taken email must not be distinguishable from an available one via
        the observable response, otherwise an attacker could enumerate
        registered addresses through /profile/edit (see
        fix/password-reset-enumeration for the same pattern applied to the
        password reset flow)."""
        from app.db import execute
        from app.security import hash_password

        with self.app.app_context():
            execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                ("taken@example.com", "bob", "Doe", "Bob", hash_password("StrongPass123!")),
            )

        token = self._login_and_get_token()
        taken_response = self.client.post(
            "/profile/edit",
            data={
                "first_name": "Alice",
                "last_name": "Doe",
                "email": "taken@example.com",
                "csrf_token": token,
            },
            follow_redirects=True,
        )

        token = self._login_and_get_token()
        available_response = self.client.post(
            "/profile/edit",
            data={
                "first_name": "Alice",
                "last_name": "Doe",
                "email": "available@example.com",
                "csrf_token": token,
            },
            follow_redirects=True,
        )

        self.assertEqual(taken_response.status_code, available_response.status_code)

        generic_message = "If this address is valid, a confirmation email has been sent."
        self.assertIn(generic_message, taken_response.get_data(as_text=True))
        self.assertIn(generic_message, available_response.get_data(as_text=True))

        from app.db import query_one

        with self.app.app_context():
            row = query_one("SELECT email FROM users WHERE username = 'alice'")

        self.assertEqual(row["email"], "old@example.com")


if __name__ == "__main__":
    unittest.main()
