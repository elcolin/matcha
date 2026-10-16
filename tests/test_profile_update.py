import unittest
from unittest.mock import patch

from app.db import execute, query_all, query_one
from app.profile.routes import _update_profile
from app.utils import APIError
from tests.helpers import DBTestCase

PROFILE_ROW_SQL = """
    SELECT p.gender, p.sexual_preference, p.bio, p.city, p.neighborhood,
           p.latitude, p.longitude, p.location_consent_gps, p.age, u.first_name
    FROM profiles p JOIN users u ON u.id = p.user_id
    WHERE p.user_id = ?
"""


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

    @patch("app.profile.routes.geocode_city", return_value=(48.8566, 2.3522))
    def test_valid_fields_are_persisted(self, mock_geocode):
        result = _update_profile(
            self.user_id,
            {
                "gender": "female",
                "sexual_preference": "women",
                "bio": "Hello!",
                "city": "Paris",
                "location_consent_gps": "0",
            },
        )

        mock_geocode.assert_called_once_with("Paris", None)
        self.assertEqual(result["gender"], "female")
        self.assertEqual(result["sexual_preference"], "women")
        self.assertEqual(result["bio"], "Hello!")
        self.assertEqual(result["city"], "Paris")

    @patch("app.profile.routes.geocode_city", return_value=(45.764, 4.8357))
    def test_omitted_fields_are_left_unchanged(self, mock_geocode):
        _update_profile(self.user_id, {"gender": "male", "city": "Lyon", "location_consent_gps": "0"})

        # A second update that only changes the bio must not reset gender/city.
        _update_profile(self.user_id, {"bio": "Updated bio"})

        row = query_one("SELECT gender, city, bio FROM profiles WHERE user_id = ?", (self.user_id,))
        self.assertEqual(row["gender"], "male")
        self.assertEqual(row["city"], "Lyon")
        self.assertEqual(row["bio"], "Updated bio")

    def test_tags_are_normalized_deduplicated_and_persisted(self):
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

    def test_delegates_core_user_field_updates(self):
        _update_profile(self.user_id, {"first_name": "Alicia", "last_name": "Smith"})

        row = query_one("SELECT first_name, last_name FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["first_name"], "Alicia")
        self.assertEqual(row["last_name"], "Smith")

    @patch("app.profile.routes.geocode_city", return_value=(45.764, 4.8357))
    def test_email_field_is_not_applied_immediately(self, mock_geocode):
        """Email changes go through a confirmation step (see
        app.profile.routes.edit_profile_submit / app.profile.data.UserUpdater.request_email_change);
        `_update_profile` itself must never write to users.email."""
        _update_profile(
            self.user_id, {"email": "new@example.com", "city": "Lyon", "location_consent_gps": "0"}
        )

        row = query_one("SELECT email FROM users WHERE id = ?", (self.user_id,))
        self.assertEqual(row["email"], "a@example.com")


class UpdateProfileLocationTests(DBTestCase):
    """Location is validated and resolved (geocoding) before anything is
    written: city, neighborhood and coordinates are saved together or not at
    all, and any location error aborts the whole update."""

    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="a@example.com", username="alice")
        execute(
            """
            UPDATE profiles
            SET gender = 'female', bio = 'Original bio', city = 'Marseille',
                neighborhood = 'Le Panier', latitude = 43.2965, longitude = 5.3698,
                location_consent_gps = 0
            WHERE user_id = ?
            """,
            (self.user_id,),
        )
        execute(
            "INSERT INTO tags (name) VALUES ('sailing')",
        )
        execute(
            "INSERT INTO user_tags (user_id, tag_id) SELECT ?, id FROM tags WHERE name = 'sailing'",
            (self.user_id,),
        )

    def _row(self):
        return dict(query_one(PROFILE_ROW_SQL, (self.user_id,)))

    def _tags(self):
        rows = query_all(
            "SELECT t.name FROM user_tags ut JOIN tags t ON t.id = ut.tag_id WHERE ut.user_id = ?",
            (self.user_id,),
        )
        return [r["name"] for r in rows]

    @patch("app.profile.routes.get_location_from_coords")
    def test_consent_with_missing_or_invalid_coords_is_rejected(self, mock_reverse):
        invalid = [
            {},
            {"latitude": "", "longitude": ""},
            {"latitude": "abc", "longitude": "2.35"},
            {"latitude": "48.85", "longitude": "abc"},
            {"latitude": "nan", "longitude": "2.35"},
            {"latitude": "48.85", "longitude": "inf"},
            {"latitude": "91", "longitude": "2.35"},
            {"latitude": "-90.5", "longitude": "2.35"},
            {"latitude": "48.85", "longitude": "181"},
            {"latitude": "48.85", "longitude": "-181"},
        ]
        before = self._row()
        for coords in invalid:
            with self.subTest(coords=coords):
                payload = {"location_consent_gps": "1", "bio": "New bio", **coords}
                with self.assertRaises(APIError):
                    _update_profile(self.user_id, payload)
                self.assertEqual(self._row(), before)
        mock_reverse.assert_not_called()

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_consent_uses_reverse_geocoded_location(self, mock_reverse):
        mock_reverse.return_value = {"city": "Berlin", "neighbourhood": "Mitte"}

        result = _update_profile(
            self.user_id,
            {"location_consent_gps": "true", "latitude": "52.52", "longitude": "13.405"},
        )

        mock_reverse.assert_called_once_with(52.52, 13.405)
        self.assertEqual(result["city"], "Berlin")
        self.assertEqual(result["neighborhood"], "Mitte")
        self.assertTrue(result["location_consent_gps"])
        row = self._row()
        self.assertEqual((row["latitude"], row["longitude"]), (52.52, 13.405))

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_without_neighbourhood_clears_previous_one(self, mock_reverse):
        mock_reverse.return_value = {"city": "Some Hamlet", "neighbourhood": None}

        _update_profile(
            self.user_id,
            {"location_consent_gps": "1", "latitude": "45.0", "longitude": "5.0"},
        )

        row = self._row()
        self.assertEqual(row["city"], "Some Hamlet")
        self.assertIsNone(row["neighborhood"])

    @patch("app.profile.routes.geocode_city", return_value=(45.764, 4.8357))
    def test_manual_city_stores_geocoded_coords_over_stale_ones(self, mock_geocode):
        _update_profile(
            self.user_id,
            {
                "location_consent_gps": "0",
                "city": "Lyon",
                "neighborhood": "",
                # Stale hidden-field values from a previous GPS fix must be ignored.
                "latitude": "10.0",
                "longitude": "10.0",
            },
        )

        mock_geocode.assert_called_once_with("Lyon", None)
        row = self._row()
        self.assertEqual(row["city"], "Lyon")
        self.assertIsNone(row["neighborhood"])
        self.assertEqual((row["latitude"], row["longitude"]), (45.764, 4.8357))
        self.assertEqual(row["location_consent_gps"], 0)

    @patch("app.profile.routes.geocode_city", return_value=(45.7676, 4.8344))
    def test_manual_neighborhood_is_passed_to_geocoder_and_stored(self, mock_geocode):
        _update_profile(
            self.user_id,
            {"location_consent_gps": "0", "city": " Lyon ", "neighborhood": " Croix-Rousse "},
        )

        mock_geocode.assert_called_once_with("Lyon", "Croix-Rousse")
        row = self._row()
        self.assertEqual(row["city"], "Lyon")
        self.assertEqual(row["neighborhood"], "Croix-Rousse")

    @patch("app.profile.routes.geocode_city")
    def test_manual_mode_requires_a_city(self, mock_geocode):
        before = self._row()
        for city in (None, "", "   "):
            with self.subTest(city=city):
                payload = {"location_consent_gps": "0", "bio": "New bio"}
                if city is not None:
                    payload["city"] = city
                with self.assertRaises(APIError):
                    _update_profile(self.user_id, payload)
                self.assertEqual(self._row(), before)
        mock_geocode.assert_not_called()

    @patch("app.profile.routes.geocode_city")
    def test_empty_consent_value_means_manual_mode(self, mock_geocode):
        mock_geocode.return_value = (45.764, 4.8357)

        _update_profile(self.user_id, {"location_consent_gps": "", "city": "Lyon"})

        mock_geocode.assert_called_once_with("Lyon", None)
        self.assertEqual(self._row()["location_consent_gps"], 0)

    @patch("app.profile.routes.get_location_from_coords")
    @patch("app.profile.routes.geocode_city")
    def test_geocoder_failure_leaves_whole_profile_unchanged(self, mock_geocode, mock_reverse):
        mock_geocode.side_effect = APIError("The location service is unavailable.", 503)
        mock_reverse.side_effect = APIError("The location service is unavailable.", 503)
        before = self._row()
        payloads = [
            {"location_consent_gps": "0", "city": "Lyon"},
            {"location_consent_gps": "1", "latitude": "45.0", "longitude": "5.0"},
        ]
        for location in payloads:
            with self.subTest(location=location):
                with self.assertRaises(APIError):
                    _update_profile(
                        self.user_id,
                        {
                            **location,
                            "bio": "New bio",
                            "gender": "male",
                            "tags": "chess",
                            "first_name": "Changed",
                        },
                    )
                self.assertEqual(self._row(), before)
                self.assertEqual(self._tags(), ["sailing"])

    @patch("app.profile.routes.get_location_from_coords")
    @patch("app.profile.routes.geocode_city")
    def test_without_consent_key_location_is_untouched(self, mock_geocode, mock_reverse):
        _update_profile(
            self.user_id,
            {"bio": "New bio", "city": "Ignored", "latitude": "1.0", "longitude": "1.0"},
        )

        mock_geocode.assert_not_called()
        mock_reverse.assert_not_called()
        row = self._row()
        self.assertEqual(row["bio"], "New bio")
        self.assertEqual(row["city"], "Marseille")
        self.assertEqual(row["neighborhood"], "Le Panier")
        self.assertEqual((row["latitude"], row["longitude"]), (43.2965, 5.3698))

    @patch("app.profile.routes.flash")
    @patch("app.profile.routes.geocode_city", side_effect=APIError("Service down", 503))
    def test_helper_never_flashes(self, mock_geocode, mock_flash):
        with self.assertRaises(APIError):
            _update_profile(self.user_id, {"location_consent_gps": "0", "city": "Lyon"})
        mock_flash.assert_not_called()


if __name__ == "__main__":
    unittest.main()
