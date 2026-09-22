import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.config import Config


class ChangeUsersEmailTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app_context = self.app.app_context()
        self.app_context.push()

        from app.db import execute

        self.user_a_id = self._create_user(execute, "alice@example.com", "alice")
        self.user_b_id = self._create_user(execute, "bob@example.com", "bob")

    def tearDown(self):
        self.app_context.pop()
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _create_user(self, execute, email, username):
        cur = execute(
            "INSERT INTO users (email, username, last_name, first_name, password_hash) "
            "VALUES (?, ?, 'Doe', 'John', 'hash')",
            (email, username),
        )
        return cur.lastrowid

    def test_change_users_email_rejects_duplicate(self):
        from app.profile.data import UserUpdater
        from app.utils import APIError

        with patch(
            "app.profile.data.validate_email",
            return_value=SimpleNamespace(normalized="alice@example.com"),
        ):
            with self.assertRaises(APIError):
                UserUpdater.change_users_email(self.user_b_id, "alice@example.com")

    def test_change_users_email_updates_when_unique(self):
        from app.profile.data import UserUpdater
        from app.db import query_one

        with patch(
            "app.profile.data.validate_email",
            return_value=SimpleNamespace(normalized="bob-new@example.com"),
        ):
            UserUpdater.change_users_email(self.user_b_id, "bob-new@example.com")

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_b_id,))
        self.assertEqual(row["email"], "bob-new@example.com")


if __name__ == "__main__":
    unittest.main()
