import os
import secrets
import tempfile
import unittest

from app import config as app_config


class PopularityScoreDisplayTests(unittest.TestCase):
    """The popularity score already computed by update_popularity() (app/utils.py)
    must reach the suggestion cards rendered on the home page ("/"), via
    profile_card.html. Regression guard: home() used to build the per-card dict
    in app/routes.py without forwarding `popularity_score` from candidate_profiles().
    """

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app_config.Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.db_path)

    def _create_user(self, username, popularity_score=0):
        from app.db import execute, query_one

        with self.app.app_context():
            execute(
                """
                INSERT INTO users (email, username, first_name, last_name, password_hash, email_verified)
                VALUES (?, ?, ?, ?, ?, 1)
                """,
                (f"{username}@example.com", username, "First", "Last", "hash"),
            )
            row = query_one("SELECT id FROM users WHERE username = ?", (username,))
            user_id = row["id"]
            execute(
                "INSERT INTO profiles (user_id, age, popularity_score) VALUES (?, 25, ?)",
                (user_id, popularity_score),
            )
        return user_id

    def _login_as(self, user_id):
        from app.db import execute

        token = secrets.token_hex(16)
        with self.app.app_context():
            execute(
                "INSERT INTO user_sessions (user_id, session_token) VALUES (?, ?)",
                (user_id, token),
            )
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["session_token"] = token

    def test_home_page_displays_zero_popularity_score(self):
        viewer_id = self._create_user("viewer")
        self._create_user("candidate", popularity_score=0)
        self._login_as(viewer_id)

        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Popularity: 0", html)

    def test_home_page_displays_high_popularity_score(self):
        viewer_id = self._create_user("viewer")
        self._create_user("candidate", popularity_score=142)
        self._login_as(viewer_id)

        resp = self.client.get("/")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Popularity: 142", html)

    def test_profile_detail_page_displays_popularity_score(self):
        viewer_id = self._create_user("viewer")
        candidate_id = self._create_user("candidate", popularity_score=77)
        self._login_as(viewer_id)

        resp = self.client.get(f"/profile/{candidate_id}")
        html = resp.get_data(as_text=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn("Popularity: 77", html)


if __name__ == "__main__":
    unittest.main()
