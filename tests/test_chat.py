import os
import secrets
import tempfile
import unittest

from app import config as app_config


class ChatPresenceAndMessageNotificationsTests(unittest.TestCase):
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

    def _like(self, from_user_id, to_user_id):
        from app.db import execute

        with self.app.app_context():
            execute(
                "INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
                (from_user_id, to_user_id),
            )

    def _make_match(self, a_id, b_id):
        self._like(a_id, b_id)
        self._like(b_id, a_id)

    def _block(self, blocker_id, blocked_id):
        from app.db import execute

        with self.app.app_context():
            execute(
                "INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
                (blocker_id, blocked_id),
            )

    def _set_presence(self, user_id, partner_id, seconds_ago):
        from app.db import execute

        with self.app.app_context():
            execute(
                """
                INSERT INTO chat_presence (user_id, partner_id, updated_at)
                VALUES (?, ?, datetime('now', ?))
                ON CONFLICT(user_id, partner_id)
                DO UPDATE SET updated_at = excluded.updated_at
                """,
                (user_id, partner_id, f"-{seconds_ago} seconds"),
            )

    def _notifications_for(self, user_id):
        from app.db import query_all

        with self.app.app_context():
            return query_all("SELECT * FROM notifications WHERE user_id = ?", (user_id,))

    def _csrf_headers(self):
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            return {"X-CSRFToken": sess["csrf_token"]}

    def test_is_viewing_chat_true_for_fresh_presence(self):
        from app.chat.routes import _is_viewing_chat

        a_id = self._create_user("alice")
        b_id = self._create_user("bob")
        self._set_presence(a_id, b_id, seconds_ago=1)

        with self.app.app_context():
            self.assertTrue(_is_viewing_chat(a_id, b_id))

    def test_is_viewing_chat_false_for_stale_presence(self):
        from app.chat.routes import _is_viewing_chat

        a_id = self._create_user("carol")
        b_id = self._create_user("dave")
        self._set_presence(a_id, b_id, seconds_ago=30)

        with self.app.app_context():
            self.assertFalse(_is_viewing_chat(a_id, b_id))

    def test_is_viewing_chat_false_when_no_presence_row(self):
        from app.chat.routes import _is_viewing_chat

        a_id = self._create_user("eve")
        b_id = self._create_user("frank")

        with self.app.app_context():
            self.assertFalse(_is_viewing_chat(a_id, b_id))

    def test_presence_ping_upserts_row_for_matched_users(self):
        a_id = self._create_user("gina")
        b_id = self._create_user("harry")
        self._make_match(a_id, b_id)
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/presence", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200)

        from app.chat.routes import _is_viewing_chat

        with self.app.app_context():
            self.assertTrue(_is_viewing_chat(a_id, b_id))

        # Pinging again should update (not duplicate) the row.
        resp = self.client.post(f"/chat/{b_id}/presence", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200)

        from app.db import query_all

        with self.app.app_context():
            rows = query_all(
                "SELECT * FROM chat_presence WHERE user_id = ? AND partner_id = ?",
                (a_id, b_id),
            )
        self.assertEqual(len(rows), 1)

    def test_presence_ping_requires_login(self):
        a_id = self._create_user("iris")
        b_id = self._create_user("jack")

        resp = self.client.post(f"/chat/{b_id}/presence", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 401)

    def test_presence_ping_rejected_when_not_matched(self):
        a_id = self._create_user("kevin")
        b_id = self._create_user("laura")
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/presence", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 403)

    def test_presence_ping_rejected_when_blocked(self):
        a_id = self._create_user("mia")
        b_id = self._create_user("noah")
        self._make_match(a_id, b_id)
        self._block(b_id, a_id)
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/presence", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 403)

    def test_send_message_notifies_receiver_when_not_viewing_chat(self):
        a_id = self._create_user("olive")
        b_id = self._create_user("pete")
        self._make_match(a_id, b_id)
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/send", json={"content": "hello"}, headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200)

        notifications = self._notifications_for(b_id)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["type"], "message_received")

    def test_send_message_does_not_notify_receiver_when_actively_viewing_chat(self):
        a_id = self._create_user("quinn")
        b_id = self._create_user("ruth")
        self._make_match(a_id, b_id)
        self._set_presence(b_id, a_id, seconds_ago=1)
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/send", json={"content": "hi there"}, headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200)

        self.assertEqual(self._notifications_for(b_id), [])


if __name__ == "__main__":
    unittest.main()
