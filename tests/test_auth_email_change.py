import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.config import Config


class ConfirmEmailChangeTests(unittest.TestCase):
    """Covers GET /email-change/confirm/<token> (app.auth.routes.confirm_email_change):
    clicking the confirmation link sent to the NEW address is the only thing that
    actually applies a profile email change (see app.profile.data.UserUpdater.
    request_email_change, which only inserts a pending row).
    """

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
        self.issue_signed_token = issue_signed_token

        with self.app.app_context():
            cur = execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, 'Doe', 'Jane', ?, 1)",
                ("old@example.com", "alice", hash_password("StrongPass123!")),
            )
            self.user_id = cur.lastrowid
            execute(
                "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
                (self.user_id,),
            )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _insert_pending_change(self, new_email, *, expires_delta=timedelta(hours=1), used_at=None, token=None):
        from app.db import execute

        with self.app.app_context():
            token = token or self.issue_signed_token(
                self.app.config["SECRET_KEY"], "change_email", self.user_id
            )
            execute(
                "INSERT INTO email_changes (user_id, new_email, token, expires_at, used_at) VALUES (?, ?, ?, ?, ?)",
                (
                    self.user_id,
                    new_email,
                    token,
                    (datetime.now(timezone.utc) + expires_delta).isoformat(),
                    used_at,
                ),
            )
        return token

    def _user_row(self):
        from app.db import query_one

        with self.app.app_context():
            return query_one(
                "SELECT email, email_verified FROM users WHERE id = ?", (self.user_id,)
            )

    def test_valid_token_updates_email_marks_verified_and_consumes_the_token(self):
        token = self._insert_pending_change("new@example.com")

        response = self.client.get(f"/email-change/confirm/{token}")

        self.assertEqual(response.status_code, 200)
        row = self._user_row()
        self.assertEqual(row["email"], "new@example.com")
        self.assertEqual(row["email_verified"], 1)

        from app.db import query_one

        with self.app.app_context():
            change_row = query_one("SELECT used_at FROM email_changes WHERE token = ?", (token,))
        self.assertIsNotNone(change_row["used_at"])

    def test_get_without_csrf_token_succeeds(self):
        """GET is exempt from the global CSRF check (app.utils.CSRF_SAFE_METHODS);
        the confirmation link must work with no prior session at all."""
        token = self._insert_pending_change("new@example.com")

        response = self.client.get(f"/email-change/confirm/{token}")

        self.assertEqual(response.status_code, 200)

    def test_email_is_unchanged_until_the_link_is_clicked(self):
        self._insert_pending_change("new@example.com")

        row = self._user_row()
        self.assertEqual(row["email"], "old@example.com")

    def test_expired_token_leaves_email_unchanged(self):
        token = self._insert_pending_change("new@example.com", expires_delta=timedelta(hours=-1))

        response = self.client.get(f"/email-change/confirm/{token}")

        self.assertEqual(response.status_code, 400)
        row = self._user_row()
        self.assertEqual(row["email"], "old@example.com")

    def test_already_used_token_leaves_email_unchanged(self):
        token = self._insert_pending_change(
            "new@example.com", used_at=datetime.now(timezone.utc).isoformat()
        )

        response = self.client.get(f"/email-change/confirm/{token}")

        self.assertEqual(response.status_code, 400)
        row = self._user_row()
        self.assertEqual(row["email"], "old@example.com")

    def test_forged_token_is_rejected(self):
        response = self.client.get("/email-change/confirm/not-a-real-token")

        self.assertEqual(response.status_code, 400)
        row = self._user_row()
        self.assertEqual(row["email"], "old@example.com")

    def test_token_with_wrong_purpose_is_rejected(self):
        wrong_purpose_token = self.issue_signed_token(
            self.app.config["SECRET_KEY"], "verify_email", self.user_id
        )
        from app.db import execute

        with self.app.app_context():
            execute(
                "INSERT INTO email_changes (user_id, new_email, token, expires_at) VALUES (?, ?, ?, ?)",
                (
                    self.user_id,
                    "new@example.com",
                    wrong_purpose_token,
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                ),
            )

        response = self.client.get(f"/email-change/confirm/{wrong_purpose_token}")

        self.assertEqual(response.status_code, 400)
        row = self._user_row()
        self.assertEqual(row["email"], "old@example.com")

    def test_email_taken_by_another_account_in_the_meantime_is_handled_cleanly(self):
        from app.db import execute
        from app.security import hash_password

        token = self._insert_pending_change("new@example.com")

        with self.app.app_context():
            # Another account grabs the same email address before this link is clicked.
            execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, 'Doe', 'Bob', ?, 1)",
                ("new@example.com", "bob", hash_password("StrongPass123!")),
            )

        response = self.client.get(f"/email-change/confirm/{token}")

        self.assertEqual(response.status_code, 400)

        row = self._user_row()
        self.assertEqual(row["email"], "old@example.com")

        from app.db import query_one

        with self.app.app_context():
            change_row = query_one("SELECT used_at FROM email_changes WHERE token = ?", (token,))
        # The token must be consumed even on conflict, so it cannot be replayed.
        self.assertIsNotNone(change_row["used_at"])


if __name__ == "__main__":
    unittest.main()
