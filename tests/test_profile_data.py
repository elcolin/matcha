import unittest
from unittest.mock import patch

from email_validator import EmailNotValidError

from app.db import query_one
from app.profile.data import UserUpdater
from app.utils import APIError
from tests.helpers import DBTestCase


class ChangeUsersEmailTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="old@example.com", username="olduser")

    def test_none_is_a_no_op(self):
        UserUpdater.change_users_email(self.user_id, None)

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "old@example.com")

    @patch("app.profile.data.validate_email")
    def test_valid_email_is_normalized_and_saved(self, mock_validate):
        mock_validate.return_value.normalized = "new@example.com"

        UserUpdater.change_users_email(self.user_id, "New@Example.com")

        mock_validate.assert_called_once_with("New@Example.com")
        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "new@example.com")

    @patch("app.profile.data.validate_email")
    def test_invalid_email_raises_api_error_and_does_not_change_row(self, mock_validate):
        mock_validate.side_effect = EmailNotValidError("bad email")

        with self.assertRaises(APIError):
            UserUpdater.change_users_email(self.user_id, "not-an-email")

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "old@example.com")


class ChangeUsersNameTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(
            email="a@example.com", username="alice", first_name="Alice", last_name="Doe"
        )

    def test_none_first_name_is_a_no_op(self):
        UserUpdater.change_users_first_name(self.user_id, None)

        row = query_one("SELECT first_name FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["first_name"], "Alice")

    def test_updates_first_name(self):
        UserUpdater.change_users_first_name(self.user_id, "Alicia")

        row = query_one("SELECT first_name FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["first_name"], "Alicia")

    def test_none_last_name_is_a_no_op(self):
        UserUpdater.change_users_lastname(self.user_id, None)

        row = query_one("SELECT last_name FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["last_name"], "Doe")

    def test_updates_last_name(self):
        UserUpdater.change_users_lastname(self.user_id, "Smith")

        row = query_one("SELECT last_name FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["last_name"], "Smith")


if __name__ == "__main__":
    unittest.main()
