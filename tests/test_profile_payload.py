import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.db import execute
from app.profile.routes import _pending_email_change, _profile_payload
from tests.helpers import DBTestCase


class ProfilePayloadEmailTests(DBTestCase):
    """Regression coverage for the pre-existing bug where _profile_payload never
    selected u.email, leaving the email field on profile_edit.html always empty."""

    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="active@example.com", username="alice")

    def test_includes_the_active_email(self):
        payload = _profile_payload(self.user_id)

        self.assertEqual(payload["email"], "active@example.com")

    def test_pending_unconfirmed_change_does_not_affect_the_active_email(self):
        execute(
            "INSERT INTO email_changes (user_id, new_email, token, expires_at) VALUES (?, ?, ?, ?)",
            (
                self.user_id,
                "pending@example.com",
                "sometoken",
                (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            ),
        )

        payload = _profile_payload(self.user_id)

        self.assertEqual(payload["email"], "active@example.com")


class PendingEmailChangeLookupTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="active@example.com", username="alice")

    def _insert_change(self, new_email, expires_delta, used_at=None):
        execute(
            "INSERT INTO email_changes (user_id, new_email, token, expires_at, used_at) VALUES (?, ?, ?, ?, ?)",
            (
                self.user_id,
                new_email,
                f"token-{new_email}",
                (datetime.now(timezone.utc) + expires_delta).isoformat(),
                used_at,
            ),
        )

    def test_no_pending_change_returns_none(self):
        self.assertIsNone(_pending_email_change(self.user_id))

    def test_active_pending_change_is_returned(self):
        self._insert_change("new@example.com", timedelta(days=1))

        row = _pending_email_change(self.user_id)

        self.assertIsNotNone(row)
        self.assertEqual(row["new_email"], "new@example.com")

    def test_expired_pending_change_is_ignored(self):
        self._insert_change("expired@example.com", -timedelta(days=1))

        self.assertIsNone(_pending_email_change(self.user_id))

    def test_used_pending_change_is_ignored(self):
        self._insert_change("used@example.com", timedelta(days=1), used_at="2020-01-01T00:00:00+00:00")

        self.assertIsNone(_pending_email_change(self.user_id))


class ProfileDetailJsonDoesNotLeakEmailTests(unittest.TestCase):
    """Non-regression: now that _profile_payload includes `email`, the JSON
    endpoint for viewing ANOTHER user's profile must still never expose it
    (see the profile.pop("email", None) guard in app.profile.routes.detail)."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app
        from app.security import hash_password

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            for username, email in (("alice", "alice@example.com"), ("bob", "bob@example.com")):
                execute(
                    "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                    "VALUES (?, ?, 'Doe', 'Jane', ?, 1)",
                    (email, username, hash_password("StrongPass123!")),
                )
                execute(
                    "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES "
                    "((SELECT id FROM users WHERE username = ?), 'everyone', '')",
                    (username,),
                )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _login_and_get_token(self, username):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.client.post(
            "/login",
            data={"username": username, "password": "StrongPass123!", "csrf_token": token},
        )

    def test_json_detail_of_another_users_profile_never_contains_email(self):
        from app.db import query_one

        with self.app.app_context():
            bob_id = query_one("SELECT id FROM users WHERE username = 'bob'")["id"]

        self._login_and_get_token("alice")

        response = self.client.get(f"/profile/{bob_id}?format=json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("email", response.get_json())


if __name__ == "__main__":
    unittest.main()
