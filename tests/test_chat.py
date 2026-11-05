import os
import secrets
import tempfile
import unittest

from app import config as app_config
from tests.helpers import complete_profile


class ChatMessageNotificationsTests(unittest.TestCase):
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
            complete_profile(user_id)
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

    def _notifications_for(self, user_id):
        from app.db import query_all

        with self.app.app_context():
            return query_all("SELECT * FROM notifications WHERE user_id = ?", (user_id,))

    def _csrf_headers(self):
        self.client.get("/login")
        with self.client.session_transaction() as sess:
            return {"X-CSRFToken": sess["csrf_token"]}

    def test_send_message_notifies_receiver(self):
        a_id = self._create_user("olive")
        b_id = self._create_user("pete")
        self._make_match(a_id, b_id)
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/send", json={"content": "hello"}, headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200)

        notifications = self._notifications_for(b_id)
        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0]["type"], "message_received")

    def test_offline_receiver_gets_message_in_history(self):
        a_id = self._create_user("sam")
        b_id = self._create_user("tina")
        self._make_match(a_id, b_id)
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/send", json={"content": "see you"}, headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200)

        # b was offline when the message was sent; it is there on their next visit.
        self._login_as(b_id)
        rows = self.client.get(f"/chat/{a_id}").get_json()
        self.assertEqual([r["content"] for r in rows], ["see you"])

    def test_presence_route_removed(self):
        a_id = self._create_user("uma")
        b_id = self._create_user("vic")
        self._make_match(a_id, b_id)
        self._login_as(a_id)

        resp = self.client.post(f"/chat/{b_id}/presence", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 404)

        html = self.client.get(f"/chat/view/{b_id}").get_data(as_text=True)
        self.assertNotIn("pingPresence", html)
        self.assertNotIn("/presence", html)

if __name__ == "__main__":
    unittest.main()
