import json

from app.db import execute, query_all
from app.utils import is_match
from scripts.match_users import match_users, resolve_user_id
from tests.helpers import DBTestCase


class MatchUsersScriptTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user(email="alice@test", username="alice")
        self.bob = self.create_user(email="bob@test", username="bob")

    def notifications(self, user_id):
        return [
            (row["type"], json.loads(row["payload"]))
            for row in query_all(
                "SELECT type, payload FROM notifications WHERE user_id = ? ORDER BY id", (user_id,)
            )
        ]

    def test_resolve_user_id_accepts_id_or_username(self):
        self.assertEqual(resolve_user_id(str(self.alice)), self.alice)
        self.assertEqual(resolve_user_id("bob"), self.bob)

    def test_resolve_user_id_rejects_unknown_user(self):
        with self.assertRaises(ValueError):
            resolve_user_id("nobody")
        with self.assertRaises(ValueError):
            resolve_user_id("9999")

    def test_match_creates_mutual_likes_and_notifications(self):
        self.assertTrue(match_users(self.alice, self.bob))

        self.assertTrue(is_match(self.alice, self.bob))
        self.assertEqual(
            self.notifications(self.bob),
            [("like_received", {"from_user_id": self.alice}), ("new_match", {"user_id": self.alice})],
        )
        self.assertEqual(
            self.notifications(self.alice),
            [("like_received", {"from_user_id": self.bob}), ("new_match", {"user_id": self.bob})],
        )

    def test_match_completes_an_existing_one_way_like(self):
        execute("INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)", (self.alice, self.bob))

        self.assertTrue(match_users(self.alice, self.bob))

        self.assertTrue(is_match(self.alice, self.bob))
        self.assertEqual([n[0] for n in self.notifications(self.bob)], ["new_match"])
        self.assertEqual([n[0] for n in self.notifications(self.alice)], ["like_received", "new_match"])

    def test_match_is_a_no_op_when_already_matched(self):
        match_users(self.alice, self.bob)
        before = len(query_all("SELECT id FROM notifications"))

        self.assertFalse(match_users(self.alice, self.bob))
        self.assertEqual(len(query_all("SELECT id FROM notifications")), before)

    def test_match_updates_popularity_of_both_users(self):
        match_users(self.alice, self.bob)

        scores = query_all("SELECT popularity_score FROM profiles WHERE user_id IN (?, ?)", (self.alice, self.bob))
        self.assertTrue(all(row["popularity_score"] > 0 for row in scores))

    def test_match_refuses_self(self):
        with self.assertRaises(ValueError):
            match_users(self.alice, self.alice)

    def test_match_refuses_blocked_pair(self):
        execute("INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)", (self.bob, self.alice))

        with self.assertRaises(ValueError):
            match_users(self.alice, self.bob)
        self.assertFalse(query_all("SELECT id FROM likes"))
