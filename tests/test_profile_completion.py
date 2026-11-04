import os
import secrets
import tempfile
import unittest

from app.config import Config
from app.db import execute
from app.utils import missing_profile_fields
from tests.helpers import DBTestCase, complete_profile


class MissingProfileFieldsTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="a@example.com", username="alice")

    def test_fresh_profile_misses_every_required_field(self):
        # sexual_preference defaults to 'everyone' (bisexual by default, per the subject).
        self.assertEqual(
            missing_profile_fields(self.user_id),
            ["gender", "bio", "interests", "profile picture", "age", "location"],
        )

    def test_complete_profile_misses_nothing(self):
        complete_profile(self.user_id)

        self.assertEqual(missing_profile_fields(self.user_id), [])

    def test_photo_that_is_not_the_profile_picture_does_not_count(self):
        complete_profile(self.user_id)
        execute("UPDATE photos SET is_profile_photo = 0 WHERE user_id = ?", (self.user_id,))

        self.assertEqual(missing_profile_fields(self.user_id), ["profile picture"])

    def test_missing_sexual_preference_is_reported(self):
        complete_profile(self.user_id)
        execute("UPDATE profiles SET sexual_preference = NULL WHERE user_id = ?", (self.user_id,))

        self.assertEqual(missing_profile_fields(self.user_id), ["sexual preference"])

    def test_blank_bio_counts_as_missing(self):
        complete_profile(self.user_id)
        execute("UPDATE profiles SET bio = '   ' WHERE user_id = ?", (self.user_id,))

        self.assertEqual(missing_profile_fields(self.user_id), ["bio"])

    def test_profile_without_tags_misses_interests(self):
        complete_profile(self.user_id)
        execute("DELETE FROM user_tags WHERE user_id = ?", (self.user_id,))

        self.assertEqual(missing_profile_fields(self.user_id), ["interests"])

    def test_blank_city_counts_as_missing_location(self):
        complete_profile(self.user_id)
        execute("UPDATE profiles SET city = '  ' WHERE user_id = ?", (self.user_id,))

        self.assertEqual(missing_profile_fields(self.user_id), ["location"])


class IncompleteProfileGateTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            cur = execute(
                """
                INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
                VALUES ('v@example.com', 'viewer', 'Viewer', 'User', 'hash', 1)
                """
            )
            self.user_id = cur.lastrowid
            execute("INSERT INTO profiles (user_id) VALUES (?)", (self.user_id,))
            token = secrets.token_hex(16)
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (self.user_id, token),
            )
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["session_token"] = token

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _complete(self):
        with self.app.app_context():
            complete_profile(self.user_id)

    def test_site_pages_redirect_to_profile_edit_while_incomplete(self):
        for path in ("/", "/search", "/match", "/chat/view", "/notifications/view", f"/profile/{self.user_id}"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["Location"].endswith("/profile/edit"))

    def test_redirect_explains_what_is_missing(self):
        response = self.client.get("/search", follow_redirects=True)
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Complete your profile", html)
        self.assertIn("gender, bio, interests, profile picture, age, location", html)

    def test_mutating_requests_are_forbidden_while_incomplete(self):
        from app.security import generate_csrf_token

        token = generate_csrf_token(self.app.config["SECRET_KEY"])
        with self.client.session_transaction() as sess:
            sess["csrf_token"] = token

        response = self.client.post(
            "/profile/999/like", headers={"X-CSRFToken": token}, json={}
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn("Complete your profile", response.get_json()["error"])

    def test_profile_editor_and_background_polls_stay_reachable(self):
        for path in ("/profile/edit", "/notifications/unread-count"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_complete_profile_reaches_the_site(self):
        self._complete()

        self.assertEqual(self.client.get("/search").status_code, 200)
        self.assertEqual(self.client.get(f"/profile/{self.user_id}").status_code, 200)

    def test_anonymous_visitors_are_not_redirected(self):
        with self.client.session_transaction() as sess:
            sess.clear()

        self.assertEqual(self.client.get("/").status_code, 200)


if __name__ == "__main__":
    unittest.main()
