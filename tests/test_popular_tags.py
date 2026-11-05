import os
import secrets
import tempfile
import unittest

from app.config import Config
from app.db import execute
from app.utils import popular_tags
from tests.helpers import DBTestCase, complete_profile


def _tag_user(user_id, *names):
    for name in names:
        execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        execute(
            "INSERT INTO user_tags (user_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
            (user_id, name),
        )


class PopularTagsTests(DBTestCase):
    def test_orders_by_usage_then_name_and_skips_unused_tags(self):
        a = self.create_user(email="a@example.com", username="a")
        b = self.create_user(email="b@example.com", username="b")
        c = self.create_user(email="c@example.com", username="c")
        _tag_user(a, "music", "hiking", "coffee")
        _tag_user(b, "music", "coffee")
        _tag_user(c, "music")
        execute("INSERT INTO tags (name) VALUES ('orphan')")

        self.assertEqual(popular_tags(), ["music", "coffee", "hiking"])

    def test_respects_limit(self):
        a = self.create_user(email="a@example.com", username="a")
        _tag_user(a, "b-tag", "a-tag", "c-tag")

        self.assertEqual(popular_tags(limit=2), ["a-tag", "b-tag"])

    def test_empty_when_no_tags(self):
        self.assertEqual(popular_tags(), [])


class TagSuggestionsRenderingTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.original_db_path = Config.DATABASE_PATH
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
            execute("INSERT INTO profiles (user_id, age) VALUES (?, 30)", (self.user_id,))
            _tag_user(self.user_id, "birdwatching", "<script>x</script>")
            complete_profile(self.user_id)
            token = secrets.token_hex(16)
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (self.user_id, token),
            )
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id
            session["session_token"] = token

    def tearDown(self):
        Config.DATABASE_PATH = self.original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _assert_datalist(self, html):
        self.assertIn('list="tag-suggestions"', html)
        self.assertIn('<datalist id="tag-suggestions">', html)
        self.assertIn('<option value="birdwatching">', html)
        # Tag names are user input: they must be escaped, never rendered raw.
        self.assertNotIn("<script>x</script>", html)

    def test_profile_edit_offers_popular_tags(self):
        response = self.client.get("/profile/edit")

        self.assertEqual(response.status_code, 200)
        self._assert_datalist(response.get_data(as_text=True))

    def test_search_offers_popular_tags(self):
        response = self.client.get("/search")

        self.assertEqual(response.status_code, 200)
        self._assert_datalist(response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
