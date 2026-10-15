import os
import re
import tempfile
import unittest

from app.config import Config
from app.db import execute, query_one


class ProfileEditLinkTests(unittest.TestCase):
    """Issue #94: the "Edit profile" link on one's own profile must point to
    /profile/edit without a stray ?id= query string, and must never appear
    when viewing someone else's profile."""

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
            self.alice_id = query_one("SELECT id FROM users WHERE username = 'alice'")["id"]
            self.bob_id = query_one("SELECT id FROM users WHERE username = 'bob'")["id"]

    def tearDown(self):
        Config.DATABASE_PATH = self._original_db_path
        os.close(self.db_fd)
        os.remove(self.db_path)

    def _login(self, username):
        html = self.client.get("/login").get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        self.client.post(
            "/login",
            data={"username": username, "password": "StrongPass123!", "csrf_token": token},
        )

    def test_own_profile_edit_link_has_no_query_string(self):
        self._login("alice")

        response = self.client.get(f"/profile/{self.alice_id}")
        body = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn('href="/profile/edit"', body)
        self.assertNotIn("/profile/edit?", body)

    def test_other_users_profile_has_no_edit_link(self):
        self._login("alice")

        response = self.client.get(f"/profile/{self.bob_id}")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("/profile/edit", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
