import unittest

from flask import render_template

from tests.test_profile_edit_location import _ProfileEditTestCase


class MissingLocationDisplayTests(_ProfileEditTestCase):
    """A profile without city/neighborhood/age must never render "None"."""

    def _create_bare_profile(self):
        from app.db import execute

        with self.app.app_context():
            cur = execute(
                "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
                "VALUES ('bob@example.com', 'bob', 'Smith', 'Bob', 'x', 1)"
            )
            execute(
                "INSERT INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
                (cur.lastrowid,),
            )
            return cur.lastrowid

    def test_profile_detail_page_does_not_render_none(self):
        bob_id = self._create_bare_profile()
        self._login_and_get_token()

        html = self.client.get(f"/profile/{bob_id}").get_data(as_text=True)

        self.assertIn("Bob", html)
        self.assertNotIn("None", html)

    def test_profile_card_does_not_render_none(self):
        profile = {
            "id": 1,
            "first_name": "Bob",
            "username": "bob",
            "age": None,
            "city": None,
            "neighborhood": None,
            "photos": [],
            "distance_km": None,
            "shared_tags_count": 0,
            "online": False,
            "popularity_score": 0,
        }
        with self.app.test_request_context():
            html = render_template("components/profile_card.html", profile=profile)

        self.assertIn("Bob", html)
        self.assertNotIn("None", html)

    def test_profile_card_shows_available_location_parts(self):
        profile = {
            "id": 1,
            "first_name": "Bob",
            "username": "bob",
            "age": 30,
            "city": "Lyon",
            "neighborhood": None,
            "photos": [],
            "distance_km": None,
            "shared_tags_count": 0,
            "online": False,
            "popularity_score": 0,
        }
        with self.app.test_request_context():
            html = render_template("components/profile_card.html", profile=profile)

        self.assertIn("Bob, 30", html)
        self.assertIn("Lyon", html)
        self.assertNotIn("•", html)


if __name__ == "__main__":
    unittest.main()
