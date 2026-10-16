import os
import re
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.config import Config
from app.utils import APIError

PROFILE_ROW_SQL = """
    SELECT p.bio, p.city, p.neighborhood, p.latitude, p.longitude,
           p.location_consent_gps, u.first_name
    FROM profiles p JOIN users u ON u.id = p.user_id
    WHERE u.username = 'alice'
"""


def _fake_validate_email(email, **kwargs):
    result = MagicMock()
    result.normalized = email.lower()
    return result


class _ProfileEditTestCase(unittest.TestCase):
    """Real app + temp database with a logged-in-able user 'alice'."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app
        from app.db import execute
        from app.security import hash_password

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES (?, ?, ?, ?, ?, 1)",
                ("old@example.com", "alice", "Doe", "Alice", hash_password("StrongPass123!")),
            )
            execute(
                "INSERT INTO profiles (user_id, sexual_preference, bio, city, neighborhood, "
                "latitude, longitude, location_consent_gps) VALUES "
                "((SELECT id FROM users WHERE username = 'alice'), 'everyone', 'Old bio', "
                "'Marseille', 'Le Panier', 43.2965, 5.3698, 0)",
            )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _login_and_get_token(self):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.client.post(
            "/login",
            data={"username": "alice", "password": "StrongPass123!", "csrf_token": token},
        )
        html = self.client.get("/profile/edit").get_data(as_text=True)
        # Drop any flash left over from login so assertions only see ours.
        with self.client.session_transaction() as sess:
            sess.pop("_flashes", None)
        return re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)

    def _flashes(self):
        with self.client.session_transaction() as sess:
            return list(sess.get("_flashes", []))

    def _row(self):
        from app.db import query_one

        with self.app.app_context():
            return dict(query_one(PROFILE_ROW_SQL))

    def _post(self, token, **fields):
        data = {"first_name": "Changed", "last_name": "Doe", "bio": "New bio", "csrf_token": token}
        data.update(fields)
        return self.client.post("/profile/edit", data=data)


class ProfileEditLocationTests(_ProfileEditTestCase):
    """HTTP-level behavior of POST /profile/edit when the location part fails:
    redirect back with exactly one error flash, nothing saved, never a 500."""

    @patch("app.profile.routes.geocode_city", side_effect=APIError("Service down.", 503))
    def test_geocoder_failure_redirects_with_single_error_and_saves_nothing(self, _geocode):
        token = self._login_and_get_token()
        before = self._row()

        response = self._post(token, city="Lyon", neighborhood="")

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith("/profile/edit"))
        self.assertEqual(self._flashes(), [("error", "Service down.")])
        self.assertEqual(self._row(), before)

    @patch("app.profile.routes.get_location_from_coords")
    def test_invalid_gps_coords_redirect_with_single_error(self, mock_reverse):
        token = self._login_and_get_token()
        before = self._row()

        response = self._post(token, location_consent_gps="1", latitude="999", longitude="2")

        self.assertEqual(response.status_code, 302)
        flashes = self._flashes()
        self.assertEqual(len(flashes), 1)
        self.assertEqual(flashes[0][0], "error")
        self.assertEqual(self._row(), before)
        mock_reverse.assert_not_called()

    @patch("app.profile.routes.geocode_city", return_value=(45.764, 4.8357))
    def test_manual_city_saves_with_single_success_flash(self, mock_geocode):
        token = self._login_and_get_token()

        response = self._post(token, city="Lyon", neighborhood="")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._flashes(), [("success", "Profile updated.")])
        mock_geocode.assert_called_once_with("Lyon", None)
        row = self._row()
        self.assertEqual(row["city"], "Lyon")
        self.assertEqual((row["latitude"], row["longitude"]), (45.764, 4.8357))
        self.assertEqual(row["bio"], "New bio")

    @patch("app.profile.routes.geocode_city")
    @patch("app.profile.data.validate_email", side_effect=_fake_validate_email)
    @patch("app.profile.routes.send_email")
    def test_post_without_location_fields_still_requests_email_change(
        self, mock_send_email, _validate, mock_geocode
    ):
        token = self._login_and_get_token()
        before = self._row()

        response = self.client.post(
            "/profile/edit",
            data={
                "first_name": "Alice",
                "last_name": "Doe",
                "email": "new@example.com",
                "csrf_token": token,
            },
        )

        self.assertEqual(response.status_code, 302)
        mock_geocode.assert_not_called()
        mock_send_email.assert_called_once()
        self.assertNotIn("error", [category for category, _ in self._flashes()])
        row = self._row()
        self.assertEqual(row["city"], before["city"])
        self.assertEqual(row["location_consent_gps"], before["location_consent_gps"])


class ProfileEditUnchangedLocationTests(_ProfileEditTestCase):
    """Resubmitting an unchanged location reuses the stored resolution instead
    of calling the geocoder again (stored: Marseille / Le Panier, manual)."""

    # Static statements only: no SQL is ever built from strings, even in tests.
    _WHERE_ALICE = "WHERE user_id = (SELECT id FROM users WHERE username = 'alice')"
    _SET_STORED_SQL = {
        "city": "UPDATE profiles SET city = ? " + _WHERE_ALICE,
        "neighborhood": "UPDATE profiles SET neighborhood = ? " + _WHERE_ALICE,
        "latitude": "UPDATE profiles SET latitude = ? " + _WHERE_ALICE,
        "longitude": "UPDATE profiles SET longitude = ? " + _WHERE_ALICE,
        "location_consent_gps": "UPDATE profiles SET location_consent_gps = ? " + _WHERE_ALICE,
    }

    def _set_stored(self, **columns):
        from app.db import execute

        with self.app.app_context():
            for name, value in columns.items():
                execute(self._SET_STORED_SQL[name], (value,))

    def _assert_saved(self, response):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self._flashes(), [("success", "Profile updated.")])

    def _location(self, row):
        keys = ("city", "neighborhood", "latitude", "longitude", "location_consent_gps")
        return {key: row[key] for key in keys}

    # --- manual mode -----------------------------------------------------

    @patch("app.profile.routes.geocode_city")
    def test_manual_bio_only_change_skips_geocoder(self, mock_geocode):
        token = self._login_and_get_token()
        before = self._row()

        response = self._post(token, city="Marseille", neighborhood="Le Panier")

        self._assert_saved(response)
        mock_geocode.assert_not_called()
        after = self._row()
        self.assertEqual(after["bio"], "New bio")
        self.assertEqual(self._location(after), self._location(before))

    @patch("app.profile.routes.geocode_city", side_effect=APIError("Service down.", 503))
    def test_manual_unchanged_location_saves_even_if_geocoder_is_down(self, mock_geocode):
        token = self._login_and_get_token()

        response = self._post(token, city="Marseille", neighborhood="Le Panier")

        self._assert_saved(response)
        mock_geocode.assert_not_called()
        self.assertEqual(self._row()["bio"], "New bio")

    @patch("app.profile.routes.geocode_city")
    def test_manual_comparison_ignores_case_and_surrounding_spaces(self, mock_geocode):
        token = self._login_and_get_token()
        before = self._row()

        response = self._post(token, city="  marseille ", neighborhood=" le panier")

        self._assert_saved(response)
        mock_geocode.assert_not_called()
        row = self._row()
        # The user's own spelling is saved (trimmed); the coordinates are reused.
        self.assertEqual((row["city"], row["neighborhood"]), ("marseille", "le panier"))
        self.assertEqual(
            (row["latitude"], row["longitude"]), (before["latitude"], before["longitude"])
        )

    @patch("app.profile.routes.geocode_city")
    def test_manual_empty_neighborhood_matches_stored_null(self, mock_geocode):
        self._set_stored(neighborhood=None)
        token = self._login_and_get_token()

        response = self._post(token, city="Marseille", neighborhood="   ")

        self._assert_saved(response)
        mock_geocode.assert_not_called()
        self.assertIsNone(self._row()["neighborhood"])

    @patch("app.profile.routes.geocode_city", return_value=(43.3, 5.4))
    def test_manual_same_city_without_stored_coords_is_geocoded(self, mock_geocode):
        self._set_stored(latitude=None, longitude=None)
        token = self._login_and_get_token()

        response = self._post(token, city="Marseille", neighborhood="Le Panier")

        self._assert_saved(response)
        mock_geocode.assert_called_once_with("Marseille", "Le Panier")
        row = self._row()
        self.assertEqual((row["latitude"], row["longitude"]), (43.3, 5.4))

    @patch("app.profile.routes.geocode_city", return_value=(45.764, 4.8357))
    def test_manual_changed_city_is_geocoded(self, mock_geocode):
        token = self._login_and_get_token()

        response = self._post(token, city="Lyon", neighborhood="Le Panier")

        self._assert_saved(response)
        mock_geocode.assert_called_once_with("Lyon", "Le Panier")
        row = self._row()
        self.assertEqual(row["city"], "Lyon")
        self.assertEqual((row["latitude"], row["longitude"]), (45.764, 4.8357))

    @patch("app.profile.routes.geocode_city", return_value=(43.29, 5.37))
    def test_manual_changed_neighborhood_is_geocoded(self, mock_geocode):
        token = self._login_and_get_token()

        response = self._post(token, city="Marseille", neighborhood="")

        self._assert_saved(response)
        mock_geocode.assert_called_once_with("Marseille", None)
        self.assertIsNone(self._row()["neighborhood"])

    @patch("app.profile.routes.geocode_city", return_value=(43.29, 5.37))
    def test_switch_from_gps_to_manual_with_same_city_is_geocoded(self, mock_geocode):
        self._set_stored(location_consent_gps=1)
        token = self._login_and_get_token()

        response = self._post(token, city="Marseille", neighborhood="Le Panier")

        self._assert_saved(response)
        mock_geocode.assert_called_once_with("Marseille", "Le Panier")
        row = self._row()
        self.assertEqual(row["location_consent_gps"], 0)
        self.assertEqual((row["latitude"], row["longitude"]), (43.29, 5.37))

    # --- GPS mode --------------------------------------------------------

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_unchanged_coords_skip_reverse_geocoding(self, mock_reverse):
        self._set_stored(location_consent_gps=1)
        token = self._login_and_get_token()
        before = self._row()

        response = self._post(
            token, location_consent_gps="1", latitude="43.2965004", longitude="5.3698"
        )

        self._assert_saved(response)
        mock_reverse.assert_not_called()
        after = self._row()
        self.assertEqual(after["bio"], "New bio")
        self.assertEqual(self._location(after), self._location(before))

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_unchanged_coords_save_even_if_reverse_would_fail(self, mock_reverse):
        mock_reverse.side_effect = APIError("Service down.", 503)
        self._set_stored(location_consent_gps=1)
        token = self._login_and_get_token()

        response = self._post(token, location_consent_gps="1", latitude="43.2965", longitude="5.3698")

        self._assert_saved(response)
        mock_reverse.assert_not_called()

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_moved_coords_are_reverse_geocoded(self, mock_reverse):
        mock_reverse.return_value = {"city": "Aubagne", "neighbourhood": None}
        self._set_stored(location_consent_gps=1)
        token = self._login_and_get_token()

        response = self._post(token, location_consent_gps="1", latitude="43.2965", longitude="5.3700")

        self._assert_saved(response)
        mock_reverse.assert_called_once_with(43.2965, 5.37)
        row = self._row()
        self.assertEqual(row["city"], "Aubagne")
        self.assertEqual(row["longitude"], 5.37)

    @patch("app.profile.routes.get_location_from_coords")
    def test_switch_from_manual_to_gps_with_same_coords_is_reverse_geocoded(self, mock_reverse):
        mock_reverse.return_value = {"city": "Marseille", "neighbourhood": "Le Panier"}
        token = self._login_and_get_token()

        response = self._post(token, location_consent_gps="1", latitude="43.2965", longitude="5.3698")

        self._assert_saved(response)
        mock_reverse.assert_called_once_with(43.2965, 5.3698)
        self.assertEqual(self._row()["location_consent_gps"], 1)

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_same_coords_without_stored_city_is_reverse_geocoded(self, mock_reverse):
        mock_reverse.return_value = {"city": "Marseille", "neighbourhood": None}
        self._set_stored(location_consent_gps=1, city=None)
        token = self._login_and_get_token()

        response = self._post(token, location_consent_gps="1", latitude="43.2965", longitude="5.3698")

        self._assert_saved(response)
        mock_reverse.assert_called_once_with(43.2965, 5.3698)
        self.assertEqual(self._row()["city"], "Marseille")

    @patch("app.profile.routes.get_location_from_coords")
    def test_gps_invalid_coords_are_still_rejected_when_stored_is_gps(self, mock_reverse):
        self._set_stored(location_consent_gps=1)
        token = self._login_and_get_token()
        before = self._row()

        response = self._post(token, location_consent_gps="1", latitude="", longitude="")

        self.assertEqual(response.status_code, 302)
        self.assertEqual([c for c, _ in self._flashes()], ["error"])
        self.assertEqual(self._row(), before)
        mock_reverse.assert_not_called()


class ProfileEditTemplateTests(_ProfileEditTestCase):
    """GET /profile/edit renders the accessible location error container and
    only requires the city among manual location fields."""

    def test_edit_page_has_location_alert_and_optional_neighborhood(self):
        self._login_and_get_token()
        html = self.client.get("/profile/edit").get_data(as_text=True)

        alert = re.search(r"<[^>]*id=\"location-error\"[^>]*>", html)
        self.assertIsNotNone(alert)
        self.assertIn('role="alert"', alert.group(0))
        neighborhood = re.search(r"<input[^>]*id=\"neighborhood\"[^>]*>", html).group(0)
        self.assertNotIn("required", neighborhood)

    def _hidden_coord_values(self):
        self._login_and_get_token()
        html = self.client.get("/profile/edit").get_data(as_text=True)
        values = []
        for name in ("latitude", "longitude"):
            tag = re.search(rf"<input[^>]*id=\"{name}\"[^>]*>", html).group(0)
            values.append(re.search(r'value="([^"]*)"', tag).group(1))
        return values

    def test_zero_coordinates_are_rendered_not_blanked(self):
        from app.db import execute

        with self.app.app_context():
            execute("UPDATE profiles SET latitude = 0.0, longitude = 0.0")

        self.assertEqual(self._hidden_coord_values(), ["0.0", "0.0"])

    def test_missing_coordinates_render_empty_values(self):
        from app.db import execute

        with self.app.app_context():
            execute("UPDATE profiles SET latitude = NULL, longitude = NULL")

        self.assertEqual(self._hidden_coord_values(), ["", ""])

    def test_script_requests_position_on_load_when_consented_without_coords(self):
        self._login_and_get_token()
        html = self.client.get("/profile/edit").get_data(as_text=True)

        self.assertRegex(
            html,
            r"if \(consentBox\.checked && \(latInput\.value === '' \|\| "
            r"lonInput\.value === ''\)\) \{\s*requestPosition\(\);",
        )

    def test_unused_manual_location_fields_id_is_removed(self):
        self._login_and_get_token()
        html = self.client.get("/profile/edit").get_data(as_text=True)

        self.assertNotIn('id="manual-location-fields"', html)


if __name__ == "__main__":
    unittest.main()
