import os
import re
import secrets
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config


class RegistrationFlowTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _get_csrf_token(self):
        response = self.client.get("/register")
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match, "csrf_token hidden field missing from /register")
        return match.group(1)

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _create_verified_user(self, username="loggedin"):
        from app.db import execute, query_one

        with self.app.app_context():
            execute(
                """
                INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (f"{username}@example.com", username, "First", "Last", "hash"),
            )
            user_id = query_one("SELECT id FROM users WHERE username = ?", (username,))["id"]
            execute(
                "INSERT INTO profiles (user_id, gender, sexual_preference, age) VALUES (?, 'female', 'everyone', 25)",
                (user_id,),
            )
        return user_id

    def _login_as(self, user_id):
        from app.db import execute

        token = secrets.token_hex(16)
        with self.app.app_context():
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (user_id, token),
            )
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["session_token"] = token

    def _counts(self):
        from app.db import query_one

        with self.app.app_context():
            users = query_one("SELECT COUNT(*) AS n FROM users")["n"]
            profiles = query_one("SELECT COUNT(*) AS n FROM profiles")["n"]
        return users, profiles

    def test_logged_in_get_register_redirects_home(self):
        self._login_as(self._create_verified_user())

        response = self.client.get("/register")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))

    @patch("app.auth.routes.send_email")
    def test_logged_in_post_register_redirects_without_creating_user(self, mock_send_email):
        csrf_token = self._get_csrf_token()  # fetched while still anonymous
        self._login_as(self._create_verified_user())
        before = self._counts()

        response = self.client.post(
            "/register",
            data={
                "email": "another@example.com",
                "username": "another",
                "first_name": "Another",
                "last_name": "User",
                "password": "J8#qL2!vX9@p",
                "confirm": "J8#qL2!vX9@p",
                "csrf_token": csrf_token,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))
        self.assertEqual(self._counts(), before)
        mock_send_email.assert_not_called()

    def test_logged_in_post_register_with_invalid_payload_redirects(self):
        csrf_token = self._get_csrf_token()
        self._login_as(self._create_verified_user())
        before = self._counts()

        response = self.client.post("/register", data={"csrf_token": csrf_token})

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/"))
        self.assertEqual(self._counts(), before)

    def test_anonymous_get_register_renders_form(self):
        response = self.client.get("/register")

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="csrf_token"', response.get_data(as_text=True))

    def test_stale_session_is_treated_as_anonymous_on_register(self):
        user_id = self._create_verified_user()
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["session_token"] = "no-matching-row"

        response = self.client.get("/register")

        self.assertEqual(response.status_code, 200)
        self.assertIn('name="csrf_token"', response.get_data(as_text=True))

    def test_register_rejects_mismatched_passwords(self):
        response = self.client.post(
            "/register",
            data={
                "email": "user@example.com",
                "username": "alice",
                "first_name": "Alice",
                "last_name": "Tester",
                "password": "J8#qL2!vX9@p",
                "confirm": "DifferentPass123!",
                "csrf_token": self._get_csrf_token(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Passwords do not match", response.get_data(as_text=True))

    def test_register_rejects_invalid_email(self):
        response = self.client.post(
            "/register",
            data={
                "email": "not-an-email",
                "username": "alice2",
                "first_name": "Alice",
                "last_name": "Tester",
                "password": "J8#qL2!vX9@p",
                "confirm": "J8#qL2!vX9@p",
                "csrf_token": self._get_csrf_token(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid email", response.get_data(as_text=True))

    @patch("app.auth.routes.send_email")
    def test_register_creates_user_and_verification_record(self, mock_send_email):
        response = self.client.post(
            "/register",
            data={
                "email": "newuser@example.com",
                "username": "newuser",
                "first_name": "New",
                "last_name": "User",
                "password": "J8#qL2!vX9@p",
                "confirm": "J8#qL2!vX9@p",
                "csrf_token": self._get_csrf_token(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Account created", response.get_data(as_text=True))
        mock_send_email.assert_called_once()


    def _register(self, email, username):
        return self.client.post(
            "/register",
            data={
                "email": email,
                "username": username,
                "first_name": "New",
                "last_name": "User",
                "password": "J8#qL2!vX9@p",
                "confirm": "J8#qL2!vX9@p",
                "csrf_token": self._get_csrf_token(),
            },
        )

    @patch("app.auth.routes.send_email")
    def test_register_rejects_case_variant_of_existing_email(self, mock_send_email):
        from app.db import query_all

        self._create_verified_user("taken")  # taken@example.com

        response = self._register("Taken@Example.com", "someoneelse")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Email or username already exists", response.get_data(as_text=True))
        mock_send_email.assert_not_called()
        with self.app.app_context():
            rows = query_all("SELECT id FROM users WHERE username = ?", ("someoneelse",))
        self.assertEqual(rows, [])

    @patch("app.auth.routes.send_email")
    def test_register_stores_email_fully_lowercased(self, mock_send_email):
        from app.db import query_one

        self._register("Newuser@Example.com", "newuser")

        with self.app.app_context():
            row = query_one("SELECT email FROM users WHERE username = ?", ("newuser",))
        self.assertEqual(row["email"], "newuser@example.com")
        self.assertEqual(mock_send_email.call_args[0][0], "newuser@example.com")

if __name__ == "__main__":
    unittest.main()
