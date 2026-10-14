import unittest
from unittest.mock import patch

from app.db import query_all, query_one
from app.profile.routes import _update_profile
from app.utils import APIError
from tests.helpers import DBTestCase


class UpdateProfileValidationTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="a@example.com", username="alice")

    def test_invalid_gender_raises_and_does_not_touch_row(self):
        with self.assertRaises(APIError):
            _update_profile(self.user_id, {"gender": "not-a-gender"})

        row = query_one("SELECT gender FROM profiles WHERE user_id = ?", (self.user_id,))
        self.assertIsNone(row["gender"])

    def test_invalid_sexual_preference_raises(self):
        with self.assertRaises(APIError):
            _update_profile(self.user_id, {"sexual_preference": "not-a-preference"})

    @patch("app.profile.routes.check_if_city_valid")
    def test_valid_fields_are_persisted(self, mock_check_city):
        result = _update_profile(
            self.user_id,
            {"gender": "female", "sexual_preference": "women", "bio": "Hello!", "city": "Paris"},
        )

        mock_check_city.assert_called_once_with("Paris")
        self.assertEqual(result["gender"], "female")
        self.assertEqual(result["sexual_preference"], "women")
        self.assertEqual(result["bio"], "Hello!")
        self.assertEqual(result["city"], "Paris")

    @patch("app.profile.routes.check_if_city_valid")
    def test_omitted_fields_are_left_unchanged(self, mock_check_city):
        _update_profile(self.user_id, {"gender": "male", "city": "Lyon"})

        # A second update that only changes the bio must not reset gender/city.
        _update_profile(self.user_id, {"bio": "Updated bio", "city": "Lyon"})

        row = query_one("SELECT gender, city, bio FROM profiles WHERE user_id = ?", (self.user_id,))
        self.assertEqual(row["gender"], "male")
        self.assertEqual(row["city"], "Lyon")
        self.assertEqual(row["bio"], "Updated bio")

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_consent_uses_reverse_geocoded_location(self, mock_get_location):
        mock_get_location.return_value = {"city": "Berlin", "neighbourhood": "Mitte"}

        result = _update_profile(
            self.user_id,
            {"location_consent_gps": "true", "latitude": "52.52", "longitude": "13.405"},
        )

        mock_get_location.assert_called_once_with("52.52", "13.405")
        self.assertEqual(result["city"], "Berlin")
        self.assertEqual(result["neighborhood"], "Mitte")
        self.assertTrue(result["location_consent_gps"])

    @patch("app.profile.routes.check_if_city_valid")
    def test_tags_are_normalized_deduplicated_and_persisted(self, mock_check_city):
        result = _update_profile(
            self.user_id,
            {"tags": "Coffee, travel , coffee,  , Music"},
        )

        self.assertEqual(result["tags"], ["coffee", "music", "travel"])

        rows = query_all(
            """
            SELECT t.name FROM user_tags ut JOIN tags t ON t.id = ut.tag_id
            WHERE ut.user_id = ? ORDER BY t.name
            """,
            (self.user_id,),
        )
        self.assertEqual([r["name"] for r in rows], ["coffee", "music", "travel"])

    @patch("app.profile.routes.check_if_city_valid")
    def test_delegates_core_user_field_updates(self, mock_check_city):
        _update_profile(self.user_id, {"first_name": "Alicia", "last_name": "Smith"})

        row = query_one("SELECT first_name, last_name FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["first_name"], "Alicia")
        self.assertEqual(row["last_name"], "Smith")

    @patch("app.profile.routes.check_if_city_valid")
    def test_email_field_is_not_applied_immediately(self, mock_check_city):
        """Email changes go through a confirmation step (see
        app.profile.routes.edit_profile_submit / app.profile.data.UserUpdater.request_email_change);
        `_update_profile` itself must never write to users.email."""
        _update_profile(self.user_id, {"email": "new@example.com", "city": "Lyon"})

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "a@example.com")


if __name__ == "__main__":
    unittest.main()
