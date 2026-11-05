"""
Tests for /logout: POST only, protected by the global CSRF check.

A GET logout would let any third-party page log a user out with a simple
`<img src="/logout">`, so the route only accepts a POST carrying csrf_token.
"""

import os
import re
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.db import execute, query_one
from app.security import hash_password

PASSWORD = "StrongPass123!"


class LogoutTests(unittest.TestCase):
    def setUp(self):
        db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        Config.DATABASE_PATH = self.db_path

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            cur = execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                ("alice@example.com", "alice", "Test", "User", hash_password(PASSWORD)),
            )
            self.alice = cur.lastrowid
            execute(
                "INSERT OR IGNORE INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
                (self.alice,),
            )

        self.client.get("/login")
        self.client.post(
            "/login",
            data={"username": "alice", "password": PASSWORD, "csrf_token": self._csrf()},
        )

    def tearDown(self):
        os.remove(self.db_path)

    def _csrf(self):
        self.client.get("/")  # login clears the session: render a page to get a fresh token
        with self.client.session_transaction() as sess:
            return sess["csrf_token"]

    def _logged_in(self):
        with self.client.session_transaction() as sess:
            return "user_id" in sess

    def _session_rows(self):
        with self.app.app_context():
            row = query_one("SELECT COUNT(*) AS c FROM user_sessions WHERE user_id = ?", (self.alice,))
            return row["c"]

    def test_get_logout_is_not_allowed_and_keeps_session(self):
        response = self.client.get("/logout")

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self._logged_in())

    def test_post_logout_without_csrf_is_rejected_and_keeps_session(self):
        response = self.client.post("/logout")

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self._logged_in())
        self.assertEqual(self._session_rows(), 1)

    def test_form_post_logout_redirects_home_and_ends_session(self):
        response = self.client.post("/logout", data={"csrf_token": self._csrf()})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))
        self.assertFalse(self._logged_in())
        self.assertEqual(self._session_rows(), 0)

    def test_json_logout_returns_json(self):
        response = self.client.post("/logout", json={}, headers={"X-CSRFToken": self._csrf()})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"message": "Logged out"})
        self.assertFalse(self._logged_in())

    def test_navbar_logout_is_a_post_form_with_csrf_token(self):
        html = self.client.get("/").get_data(as_text=True)

        form = re.search(r'<form[^>]*action="/logout"[^>]*>(.*?)</form>', html, re.S)
        self.assertIsNotNone(form, "logout must be a form, not a link")
        self.assertIn('method="post"', form.group(0).lower())
        self.assertIn('name="csrf_token"', form.group(1))
        self.assertNotIn('href="/logout"', html)

    def test_logout_token_is_no_longer_stored_in_session(self):
        self.client.get("/")
        with self.client.session_transaction() as sess:
            self.assertNotIn("logout_token", sess)


if __name__ == "__main__":
    unittest.main()
