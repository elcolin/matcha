import os
import secrets
import tempfile
import unittest

from app.config import Config


class SearchRouteTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        self.original_db_path = Config.DATABASE_PATH
        Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        Config.DATABASE_PATH = self.original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _create_user(self, username, age):
        from app.db import execute, query_one

        with self.app.app_context():
            execute(
                """
                INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (f"{username}@example.com", username, username.title(), "User", "hash"),
            )
            user_id = query_one("SELECT id FROM users WHERE username = ?", (username,))["id"]
            execute("INSERT INTO profiles (user_id, age) VALUES (?, ?)", (user_id, age))
        return user_id

    def _login_as(self, user_id):
        from app.db import execute

        token = secrets.token_hex(16)
        with self.app.app_context():
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (user_id, token),
            )
        with self.client.session_transaction() as session:
            session["user_id"] = user_id
            session["session_token"] = token

    def test_search_page_requires_login(self):
        response = self.client.get("/search")

        self.assertEqual(response.status_code, 401)

    def test_search_page_is_linked_from_home_and_filters_results(self):
        viewer_id = self._create_user("viewer", 28)
        matching_id = self._create_user("matching", 32)
        self._create_user("too_young", 25)
        self._login_as(viewer_id)

        home = self.client.get("/")
        home_html = home.get_data(as_text=True)
        self.assertEqual(home.status_code, 200)
        self.assertIn('href="/search"', home_html)
        self.assertIn("Search profiles", home_html)

        initial = self.client.get("/search")
        self.assertEqual(initial.status_code, 200)
        self.assertIn("Advanced search", initial.get_data(as_text=True))

        results = self.client.get("/search?min_age=30&sort_by=age&order=asc")
        html = results.get_data(as_text=True)
        self.assertEqual(results.status_code, 200)
        self.assertIn("Matching, 32", html)
        self.assertNotIn("Too_young, 25", html)
        self.assertIn(f'href="/profile/{matching_id}"', html)


if __name__ == "__main__":
    unittest.main()
