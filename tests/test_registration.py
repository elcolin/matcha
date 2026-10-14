import os
import re
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
    def test_register_rejects_email_with_uppercase(self, mock_send_email):
        from app.db import query_one

        for email in ("Alice@example.com", "alice@Example.com", "ALICE@EXAMPLE.COM"):
            with self.subTest(email=email):
                response = self.client.post(
                    "/register",
                    data={
                        "email": email,
                        "username": "alice3",
                        "first_name": "Alice",
                        "last_name": "Tester",
                        "password": "J8#qL2!vX9@p",
                        "confirm": "J8#qL2!vX9@p",
                        "csrf_token": self._get_csrf_token(),
                    },
                )

                self.assertEqual(response.status_code, 200)
                self.assertIn("Email address must be lowercase", response.get_data(as_text=True))

        with self.app.app_context():
            self.assertIsNone(query_one("SELECT id FROM users WHERE username = 'alice3'"))
        mock_send_email.assert_not_called()

    def test_email_input_rejects_uppercase_client_side(self):
        html = self.client.get("/register").get_data(as_text=True)
        self.assertRegex(html, r'<input name="email"[^>]*pattern="\[\^A-Z\]\*"')

    def test_database_refuses_uppercase_email(self):
        import sqlite3

        from app.db import execute

        with self.app.app_context():
            with self.assertRaises(sqlite3.IntegrityError):
                execute(
                    "INSERT INTO users (email, username, last_name, first_name, password_hash) "
                    "VALUES (?, ?, ?, ?, ?)",
                    ("Bob@example.com", "bob", "Bob", "Tester", "hash"),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                execute(
                    "INSERT INTO email_changes (user_id, new_email, token, expires_at) VALUES (?, ?, ?, ?)",
                    (1, "Bob@example.com", "tok", "2099-01-01T00:00:00+00:00"),
                )

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


if __name__ == "__main__":
    unittest.main()
