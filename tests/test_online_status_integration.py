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


class OnlineStatusIntegrationTests(unittest.TestCase):
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

    def test_profile_detail_json_includes_online_field(self):
        viewer = self._create_user("viewer1")
        target = self._create_user("target1")
        self._set_online_until(target, _future_iso())
        self._login_as(viewer)

        resp = self.client.get(f"/profile/{target}?format=json")

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["online"])

    def test_profile_detail_json_offline_when_online_until_in_past(self):
        viewer = self._create_user("viewer2")
        target = self._create_user("target2")
        self._set_online_until(target, _past_iso())
        self._login_as(viewer)

        resp = self.client.get(f"/profile/{target}?format=json")

        self.assertFalse(resp.get_json()["online"])

    def test_chat_matches_for_includes_online_status(self):
        from app.chat.routes import _matches_for

        a_id = self._create_user("chata")
        b_id = self._create_user("chatb")
        self._make_match(a_id, b_id)
        self._set_online_until(b_id, _future_iso())

        with self.app.app_context():
            matches = _matches_for(a_id)

        self.assertEqual(len(matches), 1)
        self.assertTrue(matches[0]["online"])

    def test_chat_matches_for_offline_when_no_recent_activity(self):
        from app.chat.routes import _matches_for

        a_id = self._create_user("chatc")
        b_id = self._create_user("chatd")
        self._make_match(a_id, b_id)

        with self.app.app_context():
            matches = _matches_for(a_id)

        self.assertEqual(len(matches), 1)
        self.assertFalse(matches[0]["online"])

    def test_users_online_status_endpoint_requires_login(self):
        target = self._create_user("target3")

        resp = self.client.get(f"/users/{target}/online-status")

        self.assertEqual(resp.status_code, 401)

    def test_users_online_status_endpoint_returns_online_flag(self):
        viewer = self._create_user("viewer4")
        target = self._create_user("target4")
        self._make_match(viewer, target)
        self._set_online_until(target, _future_iso())
        self._login_as(viewer)

        resp = self.client.get(f"/users/{target}/online-status")

        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data["online"])
        self.assertIn("last_seen_at", data)

    def test_users_online_status_endpoint_returns_offline_for_unknown_activity(self):
        viewer = self._create_user("viewer5")
        target = self._create_user("target5")
        self._make_match(viewer, target)
        self._login_as(viewer)

        resp = self.client.get(f"/users/{target}/online-status")

        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["online"])

    def test_users_online_status_endpoint_returns_404_for_unknown_user(self):
        viewer = self._create_user("viewer6")
        self._login_as(viewer)

        resp = self.client.get("/users/999999/online-status")

        self.assertEqual(resp.status_code, 404)

    def test_users_online_status_endpoint_forbidden_when_not_matched(self):
        viewer = self._create_user("viewer7")
        target = self._create_user("target7")
        self._login_as(viewer)

        resp = self.client.get(f"/users/{target}/online-status")

        self.assertIn(resp.status_code, (403, 404))

    def test_users_online_status_endpoint_forbidden_when_blocked(self):
        from app.db import execute

        viewer = self._create_user("viewer8")
        target = self._create_user("target8")
        self._make_match(viewer, target)
        with self.app.app_context():
            execute(
                "INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
                (target, viewer),
            )
        self._login_as(viewer)

        resp = self.client.get(f"/users/{target}/online-status")

        self.assertIn(resp.status_code, (403, 404))


if __name__ == "__main__":
    unittest.main()
