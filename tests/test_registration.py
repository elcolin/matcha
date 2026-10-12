import os
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
                "password": "StrongPass123!",
                "confirm": "DifferentPass123!",
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
                "password": "StrongPass123!",
                "confirm": "StrongPass123!",
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
                "password": "StrongPass123!",
                "confirm": "StrongPass123!",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Account created", response.get_data(as_text=True))
        mock_send_email.assert_called_once()


if __name__ == "__main__":
    unittest.main()
