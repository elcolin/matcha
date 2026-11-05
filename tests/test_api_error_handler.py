"""
Tests for the global APIError handler (app/__init__.py).

A plain HTML form POST must not land on a raw JSON error page: the handler
flashes the message and redirects back (same-origin referrer only). JSON
calls and GET requests keep the JSON error response.
"""

import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.db import execute
from app.security import hash_password
from tests.helpers import complete_profile

PASSWORD = "StrongPass123!"


def _make_verified_user(email, username):
    cur = execute(
        "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (email, username, "Test", "User", hash_password(PASSWORD)),
    )
    execute(
        "INSERT OR IGNORE INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
        (cur.lastrowid,),
    )
    return cur.lastrowid


class APIErrorHandlerTests(unittest.TestCase):
    def setUp(self):
        db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        Config.DATABASE_PATH = self.db_path

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            self.alice = _make_verified_user("alice@example.com", "alice")
            self.bob = _make_verified_user("bob@example.com", "bob")
            complete_profile(self.alice)

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

    def _flashes(self):
        with self.client.session_transaction() as sess:
            return sess.get("_flashes", [])

    def _like_form(self, referrer):
        return self.client.post(
            f"/profile/{self.alice}/like",
            data={"csrf_token": self._csrf()},
            headers={"Referer": referrer},
        )

    def test_form_post_error_flashes_and_redirects_to_referrer(self):
        referrer = f"http://localhost/profile/{self.alice}"
        response = self._like_form(referrer)

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], f"/profile/{self.alice}")
        self.assertIn(("error", "Cannot like yourself"), self._flashes())

    def test_form_post_error_ignores_foreign_referrer(self):
        response = self._like_form("https://evil.example.com/phish")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_form_post_error_without_referrer_redirects_home(self):
        response = self.client.post(f"/profile/{self.alice}/like", data={"csrf_token": self._csrf()})

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], "/")

    def test_json_post_error_still_returns_json(self):
        response = self.client.post(
            f"/profile/{self.alice}/like", json={}, headers={"X-CSRFToken": self._csrf()}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {"error": "Cannot like yourself"})

    def test_form_post_with_bad_csrf_is_rejected_not_redirected(self):
        response = self.client.post(f"/profile/{self.alice}/like", data={"csrf_token": "forged"})

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {"error": "Invalid or missing CSRF token"})

    def test_unauthenticated_form_post_is_rejected_not_redirected(self):
        self.client.get("/logout")
        response = self.client.post(f"/profile/{self.alice}/like", data={"csrf_token": self._csrf()})

        self.assertEqual(response.status_code, 401)

    def test_get_error_still_returns_json(self):
        self.client.get("/logout")
        response = self.client.get("/notifications/unread-count")

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Authentication required"})


if __name__ == "__main__":
    unittest.main()
