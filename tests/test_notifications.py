import os
import secrets
import tempfile
import unittest

from app import config as app_config


class BlockedUserNotificationsTests(unittest.TestCase):
    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp()
        app_config.Config.DATABASE_PATH = self.db_path

        from app import create_app

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self._next_id = 1

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

    def _block(self, blocker_id, blocked_id):
        from app.db import execute

        with self.app.app_context():
            execute(
                "INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
                (blocker_id, blocked_id),
            )

    def _notifications_for(self, user_id):
        from app.db import query_all

        with self.app.app_context():
            return query_all("SELECT * FROM notifications WHERE user_id = ?", (user_id,))

    def _profile_views_between(self, viewer_id, viewed_id):
        from app.db import query_all

        with self.app.app_context():
            return query_all(
                "SELECT * FROM profile_views WHERE viewer_id = ? AND viewed_id = ?",
                (viewer_id, viewed_id),
            )

    def test_viewing_profile_of_blocking_user_sends_no_notification(self):
        a_id = self._create_user("alice")
        b_id = self._create_user("bob")
        self._block(a_id, b_id)  # A blocks B
        self._login_as(b_id)

        resp = self.client.get(f"/profile/{a_id}?format=json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._notifications_for(a_id), [])
        self.assertEqual(self._profile_views_between(b_id, a_id), [])

    def test_viewing_profile_of_blocked_user_sends_no_notification(self):
        a_id = self._create_user("carol")
        b_id = self._create_user("dave")
        self._block(b_id, a_id)  # B blocks A, A still tries to view B
        self._login_as(a_id)

        resp = self.client.get(f"/profile/{b_id}?format=json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._notifications_for(b_id), [])
        self.assertEqual(self._profile_views_between(a_id, b_id), [])

    def test_viewing_profile_without_block_still_sends_notification(self):
        a_id = self._create_user("eve")
        b_id = self._create_user("frank")
        self._login_as(b_id)

        resp = self.client.get(f"/profile/{a_id}?format=json")

        self.assertEqual(resp.status_code, 200)
        notifications = self._notifications_for(a_id)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["type"], "profile_view")
        self.assertEqual(len(self._profile_views_between(b_id, a_id)), 1)

    def test_unlike_between_blocked_users_sends_no_notification(self):
        from app.db import execute

        a_id = self._create_user("grace")
        b_id = self._create_user("heidi")

        # Simulate a stale like row that survived a direct block (defense in depth,
        # since block_profile() already deletes likes on block).
        with self.app.app_context():
            execute(
                "INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
                (b_id, a_id),
            )
        self._block(a_id, b_id)
        self._login_as(b_id)

        resp = self.client.post(f"/profile/{a_id}/unlike")

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._notifications_for(a_id), [])


if __name__ == "__main__":
    unittest.main()
