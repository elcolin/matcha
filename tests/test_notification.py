"""
Tests unitaires pour la creation des notifications (app/notifications/ +
app/utils.add_notification, appelee depuis app/profile/routes.py).

Style aligne sur tests/test_security.py : unittest pur (pas de pytest, pas de
fixtures), pour tourner avec `python -m unittest discover` comme en CI.

L'app utilise du SQLite brut (app/db.py) et pas d'ORM : les utilisateurs de
test sont inseres directement en base (email deja verifie) pour eviter de
passer par /register, qui envoie un vrai email via SMTP.
"""

import json
import os
import tempfile
import unittest

from app import create_app
from app.config import Config
from app.db import execute, query_all
from app.security import hash_password

PASSWORD = "StrongPass123!"


def _make_verified_user(email, username):
    """Insere un utilisateur avec email deja verifie + profil minimal."""
    cur = execute(
        "INSERT INTO users (email, username, last_name, first_name, password_hash, email_verified) "
        "VALUES (?, ?, ?, ?, ?, 1)",
        (email, username, "Test", "User", hash_password(PASSWORD)),
    )
    user_id = cur.lastrowid
    execute(
        "INSERT OR IGNORE INTO profiles (user_id, sexual_preference, bio) VALUES (?, 'everyone', '')",
        (user_id,),
    )
    return user_id


def _give_profile_photo(user_id):
    """like_profile() exige que l'utilisateur qui like ait une photo de profil."""
    execute(
        "INSERT INTO photos (user_id, url, is_profile_photo) VALUES (?, ?, 1)",
        (user_id, f"https://example.com/{user_id}.jpg"),
    )


class NotificationCreationTests(unittest.TestCase):
    """Verifie que l'acces aux routes concernees insere bien les notifications attendues."""

    def setUp(self):
        db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        # create_app() lit Config.DATABASE_PATH au moment de l'appel : on le
        # pointe vers une base SQLite temporaire, isolee pour ce test.
        Config.DATABASE_PATH = self.db_path

        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

        with self.app.app_context():
            self.user_a = _make_verified_user("alice@example.com", "alice")
            self.user_b = _make_verified_user("bob@example.com", "bob")

    def tearDown(self):
        os.remove(self.db_path)

    # -- helpers ------------------------------------------------------

    def login(self, username):
        return self.client.post("/login", data={"username": username, "password": PASSWORD})

    def give_profile_photo(self, user_id):
        with self.app.app_context():
            _give_profile_photo(user_id)

    def notifications_for(self, user_id, notif_type=None):
        with self.app.app_context():
            if notif_type:
                rows = query_all(
                    "SELECT * FROM notifications WHERE user_id = ? AND type = ? ORDER BY id ASC",
                    (user_id, notif_type),
                )
            else:
                rows = query_all(
                    "SELECT * FROM notifications WHERE user_id = ? ORDER BY id ASC",
                    (user_id,),
                )
            return [dict(r) for r in rows]

    # -- profile view ---------------------------------------------------

    def test_viewing_profile_creates_profile_view_notification(self):
        self.login("alice")

        response = self.client.get(f"/profile/{self.user_b}?format=json")

        self.assertEqual(response.status_code, 200)
        notifs = self.notifications_for(self.user_b, "profile_view")
        self.assertEqual(len(notifs), 1)
        self.assertEqual(json.loads(notifs[0]["payload"]), {"viewer_id": self.user_a})
        self.assertEqual(notifs[0]["is_read"], 0)

    def test_viewing_profile_twice_same_day_does_not_duplicate_notification(self):
        self.login("alice")

        self.client.get(f"/profile/{self.user_b}?format=json")
        self.client.get(f"/profile/{self.user_b}?format=json")

        self.assertEqual(len(self.notifications_for(self.user_b, "profile_view")), 1)

    def test_viewing_own_profile_creates_no_notification(self):
        self.login("alice")

        self.client.get(f"/profile/{self.user_a}?format=json")

        self.assertEqual(self.notifications_for(self.user_a), [])

    def test_viewing_profile_without_login_creates_no_notification(self):
        response = self.client.get(f"/profile/{self.user_b}?format=json")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.notifications_for(self.user_b), [])

    # -- like / match -----------------------------------------------------

    def test_liking_profile_creates_like_received_notification(self):
        self.give_profile_photo(self.user_a)
        self.login("alice")

        response = self.client.post(f"/profile/{self.user_b}/like", json={})

        self.assertEqual(response.status_code, 200)
        notifs = self.notifications_for(self.user_b, "like_received")
        self.assertEqual(len(notifs), 1)
        self.assertEqual(json.loads(notifs[0]["payload"]), {"from_user_id": self.user_a})
        self.assertEqual(self.notifications_for(self.user_b, "new_match"), [])

    def test_liking_without_profile_photo_returns_error_and_no_notification(self):
        self.login("alice")

        response = self.client.post(f"/profile/{self.user_b}/like", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.notifications_for(self.user_b), [])

    def test_mutual_like_creates_new_match_notification_for_both_users(self):
        self.give_profile_photo(self.user_a)
        self.give_profile_photo(self.user_b)

        self.login("alice")
        self.client.post(f"/profile/{self.user_b}/like", json={})

        self.login("bob")
        response = self.client.post(f"/profile/{self.user_a}/like", json={})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["connected"])

        match_for_a = self.notifications_for(self.user_a, "new_match")
        match_for_b = self.notifications_for(self.user_b, "new_match")
        self.assertEqual(len(match_for_a), 1)
        self.assertEqual(len(match_for_b), 1)
        self.assertEqual(json.loads(match_for_a[0]["payload"]), {"user_id": self.user_b})
        self.assertEqual(json.loads(match_for_b[0]["payload"]), {"user_id": self.user_a})

    def test_delete_like_creates_unliked_notification(self):
        self.give_profile_photo(self.user_a)
        self.login("alice")
        self.client.post(f"/profile/{self.user_b}/like", json={})

        response = self.client.delete(f"/profile/{self.user_b}/like", json={})

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["liked_by_me"])
        notifs = self.notifications_for(self.user_b, "unliked")
        self.assertEqual(len(notifs), 1)
        self.assertEqual(json.loads(notifs[0]["payload"]), {"from_user_id": self.user_a})

    def test_unlike_form_route_notifies_only_when_a_like_existed(self):
        self.login("alice")

        self.client.post(f"/profile/{self.user_b}/unlike")
        self.assertEqual(self.notifications_for(self.user_b, "unliked"), [])

        self.give_profile_photo(self.user_a)
        self.client.post(f"/profile/{self.user_b}/like", json={})
        self.client.post(f"/profile/{self.user_b}/unlike")

        self.assertEqual(len(self.notifications_for(self.user_b, "unliked")), 1)

    # -- exposition via les routes de app/notifications --------------------

    def test_notifications_list_route_reflects_created_notification(self):
        self.login("alice")
        self.client.get(f"/profile/{self.user_b}?format=json")

        self.login("bob")
        response = self.client.get("/notifications")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["type"], "profile_view")
        self.assertEqual(data[0]["payload"], {"viewer_id": self.user_a})

    def test_unread_count_and_mark_read_flow(self):
        self.login("alice")
        self.client.get(f"/profile/{self.user_b}?format=json")

        self.login("bob")
        unread = self.client.get("/notifications/unread-count").get_json()
        self.assertEqual(unread["unread"], 1)

        mark_read = self.client.post("/notifications/mark-read")
        self.assertEqual(mark_read.get_json(), {"ok": True})

        unread_after = self.client.get("/notifications/unread-count").get_json()
        self.assertEqual(unread_after["unread"], 0)

    def test_notifications_view_page_renders_created_notification(self):
        self.login("alice")
        self.client.get(f"/profile/{self.user_b}?format=json")

        self.login("bob")
        response = self.client.get("/notifications/view")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Profile view", response.data)

    def test_notifications_routes_require_login(self):
        for path in ("/notifications", "/notifications/unread-count", "/notifications/view"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)

        response = self.client.post("/notifications/mark-read")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
