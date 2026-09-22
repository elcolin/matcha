import os
import secrets
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app import config as app_config


def _future_iso(seconds=30):
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _past_iso(seconds=30):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


class OnlineStatusEndToEndTests(unittest.TestCase):
    """Simulates inactivity (online_until in the past) and checks every surface
    that must reflect it: the profile JSON payload, the rendered profile page,
    the rendered homepage suggestion cards, and the rendered chat page."""

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

    def _create_user(self, username):
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
                "INSERT INTO profiles (user_id, gender, sexual_preference, age) VALUES (?, 'female', 'everyone', 25)",
                (user_id,),
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

    def _make_match(self, a_id, b_id):
        from app.db import execute

        with self.app.app_context():
            execute("INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (a_id, b_id))
            execute("INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (b_id, a_id))

    def _set_online_until(self, user_id, value):
        from app.db import execute

        with self.app.app_context():
            execute("UPDATE users SET online_until = ? WHERE id = ?", (value, user_id))

    def test_stale_activity_reports_offline_everywhere(self):
        viewer = self._create_user("viewer_e2e")
        target = self._create_user("target_e2e")
        self._make_match(viewer, target)
        # Simulate the 30s online window having elapsed.
        self._set_online_until(target, _past_iso())
        self._login_as(viewer)

        json_resp = self.client.get(f"/profile/{target}?format=json")
        self.assertFalse(json_resp.get_json()["online"])

        profile_html = self.client.get(f"/profile/{target}").get_data(as_text=True)
        self.assertIn('online-indicator offline', profile_html)
        self.assertIn('Offline', profile_html)

        home_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('online-indicator offline', home_html)

        chat_html = self.client.get(f"/chat/view/{target}").get_data(as_text=True)
        self.assertIn('online-indicator offline', chat_html)
        # The sidebar match indicator must not rely on color alone.
        self.assertIn('title="Offline"', chat_html)
        # The literal 'Online now' string also appears inside the polling
        # <script> as a JS fallback value, so assert on the rendered label
        # markup instead of the raw page text.
        self.assertIn('id="partner-online-label"', chat_html)
        self.assertIn('Offline', chat_html.split('id="partner-online-label"')[1][:100])

    def test_fresh_activity_reports_online_everywhere(self):
        viewer = self._create_user("viewer_e2e2")
        target = self._create_user("target_e2e2")
        self._make_match(viewer, target)
        self._set_online_until(target, _future_iso())
        self._login_as(viewer)

        json_resp = self.client.get(f"/profile/{target}?format=json")
        self.assertTrue(json_resp.get_json()["online"])

        profile_html = self.client.get(f"/profile/{target}").get_data(as_text=True)
        self.assertIn('online-indicator online', profile_html)
        self.assertIn('Online', profile_html)

        chat_html = self.client.get(f"/chat/view/{target}").get_data(as_text=True)
        self.assertIn('online-indicator online', chat_html)
        self.assertIn('Online now', chat_html)
        # The sidebar match indicator must not rely on color alone.
        self.assertIn('title="Online"', chat_html)


if __name__ == "__main__":
    unittest.main()
