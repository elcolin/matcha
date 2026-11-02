import os
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.db import execute
from app.match.routes import candidate_profiles
from app.profile.routes import _pending_email_change, _profile_payload
from tests.helpers import DBTestCase


class ProfilePayloadEmailTests(DBTestCase):
    """Regression coverage for the pre-existing bug where _profile_payload never
    selected u.email, leaving the email field on profile_edit.html always empty.

    `email` must only be populated when explicitly requested via
    `include_email=True` (owner call sites, e.g. GET /profile/edit): the
    default must never leak a third party's email (see the `/match` and
    `/profile/<id>` leak this guards against)."""

    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="active@example.com", username="alice")

    def test_excludes_email_by_default(self):
        payload = _profile_payload(self.user_id)

        self.assertNotIn("email", payload)

    def test_includes_the_active_email_when_explicitly_requested(self):
        payload = _profile_payload(self.user_id, include_email=True)

        self.assertEqual(payload["email"], "active@example.com")

    def test_pending_unconfirmed_change_does_not_affect_the_active_email(self):
        execute(
            "INSERT INTO email_changes (user_id, new_email, token, expires_at) VALUES (?, ?, ?, ?)",
            (
                self.user_id,
                "pending@example.com",
                "sometoken",
                (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
            ),
        )

        payload = _profile_payload(self.user_id, include_email=True)

        self.assertEqual(payload["email"], "active@example.com")


class ProfilePayloadCoordinatesTests(DBTestCase):
    """Issue #82: exact latitude/longitude must only be exposed to the owner."""

    def setUp(self):
        super().setUp()
        self.alice_id = self.create_user(email="alice@example.com", username="alice")
        self.bob_id = self.create_user(email="bob@example.com", username="bob")
        execute("UPDATE profiles SET latitude = 52.52, longitude = 13.405, city = 'Berlin' WHERE user_id = ?",
                (self.alice_id,))
        execute("UPDATE profiles SET latitude = 48.8566, longitude = 2.3522, city = 'Paris' WHERE user_id = ?",
                (self.bob_id,))

    def test_excludes_coordinates_by_default(self):
        payload = _profile_payload(self.bob_id)

        self.assertNotIn("latitude", payload)
        self.assertNotIn("longitude", payload)

    def test_includes_coordinates_when_explicitly_requested(self):
        payload = _profile_payload(self.bob_id, include_coordinates=True)

        self.assertEqual(payload["latitude"], 48.8566)
        self.assertEqual(payload["longitude"], 2.3522)

    def test_candidate_profiles_never_expose_coordinates_but_keep_distance(self):
        candidates = candidate_profiles(self.alice_id)

        self.assertEqual([c["id"] for c in candidates], [self.bob_id])
        bob = candidates[0]
        self.assertNotIn("latitude", bob)
        self.assertNotIn("longitude", bob)
        self.assertIsNotNone(bob["distance_km"])
        self.assertGreater(bob["distance_km"], 800)
        for key in ("same_city", "same_neighborhood", "shared_tags_count"):
            self.assertIn(key, bob)


class PendingEmailChangeLookupTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="active@example.com", username="alice")

    def _insert_change(self, new_email, expires_delta, used_at=None):
        execute(
            "INSERT INTO email_changes (user_id, new_email, token, expires_at, used_at) VALUES (?, ?, ?, ?, ?)",
            (
                self.user_id,
                new_email,
                f"token-{new_email}",
                (datetime.now(timezone.utc) + expires_delta).isoformat(),
                used_at,
            ),
        )

    def test_no_pending_change_returns_none(self):
        self.assertIsNone(_pending_email_change(self.user_id))

    def test_active_pending_change_is_returned(self):
        self._insert_change("new@example.com", timedelta(days=1))

        row = _pending_email_change(self.user_id)

        self.assertIsNotNone(row)
        self.assertEqual(row["new_email"], "new@example.com")

    def test_expired_pending_change_is_ignored(self):
        self._insert_change("expired@example.com", -timedelta(days=1))

        self.assertIsNone(_pending_email_change(self.user_id))

    def test_used_pending_change_is_ignored(self):
        self._insert_change("used@example.com", timedelta(days=1), used_at="2020-01-01T00:00:00+00:00")

        self.assertIsNone(_pending_email_change(self.user_id))


class ProfileDetailJsonDoesNotLeakEmailTests(unittest.TestCase):
    """Non-regression: now that _profile_payload includes `email`, the JSON
    endpoint for viewing ANOTHER user's profile must still never expose it
    (see the profile.pop("email", None) guard in app.profile.routes.detail)."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self._original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app
        from app.security import hash_password

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            for username, email in (("alice", "alice@example.com"), ("bob", "bob@example.com")):
                execute(
                    "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                    "VALUES (?, ?, 'Doe', 'Jane', ?, 1)",
                    (email, username, hash_password("StrongPass123!")),
                )
                execute(
                    "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES "
                    "((SELECT id FROM users WHERE username = ?), 'everyone', '')",
                    (username,),
                )

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _login_and_get_token(self, username):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.client.post(
            "/login",
            data={"username": username, "password": "StrongPass123!", "csrf_token": token},
        )

    def test_json_detail_of_another_users_profile_never_contains_email(self):
        from app.db import query_one

        with self.app.app_context():
            bob_id = query_one("SELECT id FROM users WHERE username = 'bob'")["id"]

        self._login_and_get_token("alice")

        response = self.client.get(f"/profile/{bob_id}?format=json")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("email", response.get_json())

    def test_html_detail_of_another_users_profile_never_contains_email(self):
        from app.db import query_one

        with self.app.app_context():
            bob_id = query_one("SELECT id FROM users WHERE username = 'bob'")["id"]

        self._login_and_get_token("alice")

        response = self.client.get(f"/profile/{bob_id}")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("bob@example.com", response.get_data(as_text=True))

    def test_html_profile_displays_gender_when_set(self):
        from app.db import query_one

        with self.app.app_context():
            bob_id = query_one("SELECT id FROM users WHERE username = 'bob'")["id"]
            execute("UPDATE profiles SET gender = 'non-binary' WHERE user_id = ?", (bob_id,))

        self._login_and_get_token("alice")
        response = self.client.get(f"/profile/{bob_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Gender: Non-binary", response.get_data(as_text=True))


class ProfileDetailAccessTests(ProfileDetailJsonDoesNotLeakEmailTests):
    """Issue #82: /profile/<id> requires authentication and never exposes
    another user's exact coordinates; the owner keeps them on /profile/edit."""

    def setUp(self):
        super().setUp()
        from app.db import query_one

        with self.app.app_context():
            self.alice_id = query_one("SELECT id FROM users WHERE username = 'alice'")["id"]
            self.bob_id = query_one("SELECT id FROM users WHERE username = 'bob'")["id"]
            execute(
                "UPDATE users SET first_name = 'Robert', last_name = 'Builder' WHERE id = ?",
                (self.bob_id,),
            )
            execute(
                "UPDATE profiles SET bio = 'Secret bob bio', latitude = 48.8566, longitude = 2.3522 "
                "WHERE user_id = ?",
                (self.bob_id,),
            )
            execute(
                "UPDATE profiles SET latitude = 52.52, longitude = 13.405 WHERE user_id = ?",
                (self.alice_id,),
            )

    def _profile_views_count(self):
        from app.db import query_one

        with self.app.app_context():
            return query_one(
                "SELECT COUNT(*) AS n FROM profile_views WHERE viewed_id = ?", (self.bob_id,)
            )["n"]

    def test_anonymous_html_detail_is_rejected_without_leaking_profile(self):
        response = self.client.get(f"/profile/{self.bob_id}")

        self.assertEqual(response.status_code, 401)
        body = response.get_data(as_text=True)
        for leaked in ("bob", "bob@example.com", "Secret bob bio", "Robert", "Builder"):
            self.assertNotIn(leaked, body)

    def test_anonymous_json_detail_is_rejected(self):
        response = self.client.get(f"/profile/{self.bob_id}?format=json")

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("username", response.get_json() or {})

    def test_anonymous_detail_records_no_profile_view(self):
        self.client.get(f"/profile/{self.bob_id}")

        self.assertEqual(self._profile_views_count(), 0)

    def test_logged_in_visit_records_profile_view(self):
        self._login_and_get_token("alice")

        response = self.client.get(f"/profile/{self.bob_id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._profile_views_count(), 1)

    def test_json_detail_of_another_user_has_no_coordinates(self):
        self._login_and_get_token("alice")

        response = self.client.get(f"/profile/{self.bob_id}?format=json")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertNotIn("latitude", data)
        self.assertNotIn("longitude", data)

    def test_html_detail_of_another_user_has_no_coordinates(self):
        self._login_and_get_token("alice")

        body = self.client.get(f"/profile/{self.bob_id}").get_data(as_text=True)

        self.assertNotIn("48.8566", body)
        self.assertNotIn("2.3522", body)

    def test_own_edit_page_still_contains_own_coordinates(self):
        self._login_and_get_token("alice")

        response = self.client.get("/profile/edit")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('value="52.52"', body)
        self.assertIn('value="13.405"', body)


if __name__ == "__main__":
    unittest.main()
