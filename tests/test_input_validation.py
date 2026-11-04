"""Server-side guards for values the HTML forms only constrain client-side
(min/max/maxlength/required): a crafted request must not get past them."""
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from app.config import Config, UserConfig
from app.db import query_all, query_one
from app.profile.routes import _update_profile
from app.security import validate_password_strength
from app.utils import APIError
from app.validation import clean_text, parse_age, parse_tags, validate_username
from tests.helpers import DBTestCase


class ParseAgeTests(unittest.TestCase):
    def test_blank_means_not_submitted(self):
        self.assertIsNone(parse_age(None))
        self.assertIsNone(parse_age("  "))

    def test_accepts_bounds(self):
        self.assertEqual(parse_age("18"), 18)
        self.assertEqual(parse_age(" 120 "), 120)

    def test_rejects_out_of_range_or_non_integer(self):
        for value in ("17", "121", "-5", "abc", "25.5", "1e2", "999999999999999999999"):
            with self.subTest(value=value), self.assertRaises(APIError):
                parse_age(value)


class CleanTextTests(unittest.TestCase):
    def test_strips_and_keeps_none(self):
        self.assertEqual(clean_text("  hi  ", "Bio", 10), "hi")
        self.assertIsNone(clean_text(None, "Bio", 10))

    def test_rejects_too_long(self):
        with self.assertRaises(APIError) as ctx:
            clean_text("x" * 11, "Bio", 10)
        self.assertIn("Bio", ctx.exception.message)

    def test_required_rejects_blank(self):
        with self.assertRaises(APIError):
            clean_text("   ", "Message", 10, required=True)

    def test_rejects_non_string(self):
        with self.assertRaises(APIError):
            clean_text(["a"], "Bio", 10)


class ParseTagsTests(unittest.TestCase):
    def test_normalizes_and_deduplicates(self):
        self.assertEqual(parse_tags("Music, music , early-bird,,"), ["early-bird", "music"])

    def test_rejects_too_many_tags(self):
        tags = ",".join(f"tag{i}" for i in range(UserConfig.TAGS_MAX_COUNT + 1))
        with self.assertRaises(APIError):
            parse_tags(tags)

    def test_rejects_too_long_or_invalid_tag(self):
        for raw in ("x" * (UserConfig.TAG_MAX_LENGTH + 1), "<script>", "a;b"):
            with self.subTest(raw=raw), self.assertRaises(APIError):
                parse_tags(raw)


class ValidateUsernameTests(unittest.TestCase):
    def test_accepts_regular_usernames(self):
        for name in ("alice", "bot_alice", "j.doe-42"):
            with self.subTest(name=name):
                self.assertEqual(validate_username(f" {name} "), name)

    def test_rejects_bad_usernames(self):
        for name in ("ab", "x" * 31, "with space", "<b>", "élise", 123):
            with self.subTest(name=name), self.assertRaises(APIError):
                validate_username(name)


class PasswordLengthTests(unittest.TestCase):
    def test_rejects_overlong_password_before_strength_analysis(self):
        password = "Aa1!" + "x9Q#" * 40
        with patch("app.security.zxcvbn") as mock_zxcvbn:
            ok, reason = validate_password_strength(password)
        self.assertFalse(ok)
        self.assertIn("at most", reason)
        mock_zxcvbn.assert_not_called()


class UpdateProfileGuardsTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="a@example.com", username="alice", first_name="Alice")

    def _assert_rejected(self, data):
        with self.assertRaises(APIError):
            _update_profile(self.user_id, data)

    def test_out_of_range_age_is_rejected_and_not_stored(self):
        self._assert_rejected({"age": "5"})
        self._assert_rejected({"age": "abc"})
        self.assertIsNone(query_one("SELECT age FROM profiles WHERE user_id = ?", (self.user_id,))["age"])

    def test_valid_age_is_stored_as_integer(self):
        _update_profile(self.user_id, {"age": "30"})
        self.assertEqual(query_one("SELECT age FROM profiles WHERE user_id = ?", (self.user_id,))["age"], 30)

    def test_overlong_bio_is_rejected(self):
        self._assert_rejected({"bio": "x" * (UserConfig.BIO_MAX_LENGTH + 1)})
        self.assertEqual(query_one("SELECT bio FROM profiles WHERE user_id = ?", (self.user_id,))["bio"], "")

    def test_overlong_name_is_rejected(self):
        self._assert_rejected({"first_name": "x" * (UserConfig.NAME_MAX_LENGTH + 1)})

    def test_whitespace_only_name_keeps_the_current_one(self):
        _update_profile(self.user_id, {"first_name": "   "})
        self.assertEqual(query_one("SELECT first_name FROM users WHERE id = ?", (self.user_id,))["first_name"], "Alice")

    def test_invalid_tags_are_rejected_and_existing_tags_kept(self):
        _update_profile(self.user_id, {"tags": "music"})
        self._assert_rejected({"tags": "x" * (UserConfig.TAG_MAX_LENGTH + 1)})
        tags = query_all(
            "SELECT t.name FROM user_tags ut JOIN tags t ON t.id = ut.tag_id WHERE ut.user_id = ?",
            (self.user_id,),
        )
        self.assertEqual([t["name"] for t in tags], ["music"])

    def test_invalid_field_aborts_before_any_write(self):
        self._assert_rejected({"gender": "male", "age": "500"})
        self.assertIsNone(query_one("SELECT gender FROM profiles WHERE user_id = ?", (self.user_id,))["gender"])

    @patch("app.profile.routes.geocode_city")
    def test_overlong_manual_city_is_rejected_without_geocoding(self, mock_geocode):
        self._assert_rejected(
            {"city": "x" * (UserConfig.PLACE_MAX_LENGTH + 1), "location_consent_gps": "0"}
        )
        mock_geocode.assert_not_called()


class RegisterGuardsTests(unittest.TestCase):
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

    def _register(self, **overrides):
        html = self.client.get("/register").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        data = {
            "email": "new@example.com",
            "username": "newbie",
            "first_name": "New",
            "last_name": "User",
            "password": "Zx9!qWv#3LpT",
            "confirm": "Zx9!qWv#3LpT",
            "csrf_token": token,
        }
        data.update(overrides)
        return self.client.post("/register", data=data)

    def _user_count(self):
        with self.app.app_context():
            return query_one("SELECT COUNT(*) AS c FROM users")["c"]

    @patch("app.auth.routes.send_email")
    def test_invalid_username_is_rejected(self, _mock_send):
        response = self._register(username="bad name<>")
        self.assertIn("Username", response.get_data(as_text=True))
        self.assertEqual(self._user_count(), 0)

    @patch("app.auth.routes.send_email")
    def test_overlong_name_is_rejected(self, _mock_send):
        response = self._register(last_name="x" * (UserConfig.NAME_MAX_LENGTH + 1))
        self.assertIn("Last name", response.get_data(as_text=True))
        self.assertEqual(self._user_count(), 0)

    @patch("app.auth.routes.send_email")
    def test_json_payload_with_non_string_fields_does_not_crash(self, _mock_send):
        self.client.get("/register")
        with self.client.session_transaction() as sess:
            token = sess["csrf_token"]
        response = self.client.post(
            "/register",
            json={
                "email": "new@example.com", "username": 42, "first_name": ["x"],
                "last_name": "User", "password": "Zx9!qWv#3LpT", "confirm": "Zx9!qWv#3LpT",
            },
            headers={"X-CSRFToken": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._user_count(), 0)

    @patch("app.auth.routes.send_email")
    def test_valid_registration_still_works(self, _mock_send):
        self._register()
        self.assertEqual(self._user_count(), 1)


if __name__ == "__main__":
    unittest.main()
