import unittest
from unittest.mock import patch

from email_validator import EmailNotValidError

from app.db import query_all, query_one
from app.profile.data import UserUpdater
from app.utils import APIError
from tests.helpers import DBTestCase


class RequestEmailChangeTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="old@example.com", username="olduser")

    def _pending_rows(self):
        return query_all(
            "SELECT * FROM email_changes WHERE user_id = ? ORDER BY id ASC",
            (self.user_id,),
        )

    def test_none_is_a_no_op(self):
        UserUpdater.request_email_change(self.user_id, None, "secret", 86400)

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "old@example.com")
        self.assertEqual(self._pending_rows(), [])

    @patch("app.profile.data.validate_email")
    def test_same_as_active_email_is_a_no_op(self, mock_validate):
        mock_validate.return_value.normalized = "old@example.com"

        UserUpdater.request_email_change(self.user_id, "Old@Example.com", "secret", 86400)

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "old@example.com")
        self.assertEqual(self._pending_rows(), [])

    @patch("app.profile.data.validate_email")
    def test_invalid_email_raises_api_error_and_does_not_change_anything(self, mock_validate):
        mock_validate.side_effect = EmailNotValidError("bad email")

        with self.assertRaises(APIError):
            UserUpdater.request_email_change(self.user_id, "not-an-email", "secret", 86400)

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "old@example.com")
        self.assertEqual(self._pending_rows(), [])

    @patch("app.profile.data.validate_email")
    def test_email_already_used_by_another_account_is_a_silent_no_op(self, mock_validate):
        """Must not raise: the caller shows the same generic message whether
        the email is taken or available, to avoid leaking which emails are
        registered (see CLAUDE.md / fix/password-reset-enumeration)."""
        self.create_user(email="taken@example.com", username="otheruser")
        mock_validate.return_value.normalized = "taken@example.com"

        token = UserUpdater.request_email_change(
            self.user_id, "Taken@Example.com", "secret", 86400
        )

        self.assertIsNone(token)
        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "old@example.com")
        self.assertEqual(self._pending_rows(), [])

    @patch("app.profile.data.validate_email")
    def test_valid_distinct_email_creates_pending_request_without_touching_active_email(self, mock_validate):
        mock_validate.return_value.normalized = "new@example.com"

        token = UserUpdater.request_email_change(self.user_id, "New@Example.com", "secret", 86400)

        mock_validate.assert_called_once_with("New@Example.com")
        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "old@example.com")

        pending = self._pending_rows()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["new_email"], "new@example.com")
        self.assertEqual(pending[0]["token"], token)
        self.assertIsNone(pending[0]["used_at"])

    @patch("app.profile.data.validate_email")
    def test_second_request_invalidates_previous_pending_one(self, mock_validate):
        mock_validate.return_value.normalized = "first@example.com"
        UserUpdater.request_email_change(self.user_id, "First@Example.com", "secret", 86400)

        mock_validate.return_value.normalized = "second@example.com"
        UserUpdater.request_email_change(self.user_id, "Second@Example.com", "secret", 86400)

        pending = self._pending_rows()
        self.assertEqual(len(pending), 2)
        self.assertIsNotNone(pending[0]["used_at"])
        self.assertIsNone(pending[1]["used_at"])

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
