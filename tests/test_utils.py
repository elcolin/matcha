import unittest

from flask import g

from app.db import execute, query_one
from app.utils import (
    APIError,
    add_notification,
    is_blocked_between,
    is_match,
    login_required,
    update_popularity,
)
from tests.helpers import DBTestCase


class UpdatePopularityTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.user_id = self.create_user(email="a@example.com", username="alice")

    def test_no_activity_gives_zero_score(self):
        score = update_popularity(self.user_id)

        self.assertEqual(score, 0)
        row = query_one("SELECT popularity_score FROM profiles WHERE user_id = ?", (self.user_id,))
        self.assertEqual(row["popularity_score"], 0)

    def test_views_and_likes_increase_score(self):
        other_id = self.create_user(email="b@example.com", username="bob")
        execute(
            "INSERT INTO profile_views (viewer_id, viewed_id) VALUES (?, ?)",
            (other_id, self.user_id),
        )
        execute(
            "INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
            (other_id, self.user_id),
        )

        score = update_popularity(self.user_id)

        # 1 view + 1 like * 10 (POPULARITY_LIKE_WEIGHT)
        self.assertEqual(score, 11)

    def test_reports_penalize_score_but_never_go_negative(self):
        other_id = self.create_user(email="b@example.com", username="bob")
        execute(
            "INSERT INTO reports (reporter_id, reported_id) VALUES (?, ?)",
            (other_id, self.user_id),
        )

        score = update_popularity(self.user_id)

        self.assertEqual(score, 0)


class BlockedBetweenTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user(email="a@example.com", username="alice")
        self.bob = self.create_user(email="b@example.com", username="bob")

    def test_no_block_returns_false(self):
        self.assertFalse(is_blocked_between(self.alice, self.bob))

    def test_block_detected_in_either_direction(self):
        execute(
            "INSERT INTO blocks (blocker_id, blocked_id) VALUES (?, ?)",
            (self.alice, self.bob),
        )

        self.assertTrue(is_blocked_between(self.alice, self.bob))
        self.assertTrue(is_blocked_between(self.bob, self.alice))


class IsMatchTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.alice = self.create_user(email="a@example.com", username="alice")
        self.bob = self.create_user(email="b@example.com", username="bob")

    def test_one_sided_like_is_not_a_match(self):
        execute(
            "INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
            (self.alice, self.bob),
        )

        self.assertFalse(is_match(self.alice, self.bob))

    def test_mutual_like_is_a_match(self):
        execute(
            "INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
            (self.alice, self.bob),
        )
        execute(
            "INSERT INTO likes (from_user_id, to_user_id) VALUES (?, ?)",
            (self.bob, self.alice),
        )

        self.assertTrue(is_match(self.alice, self.bob))
        self.assertTrue(is_match(self.bob, self.alice))


class AddNotificationTests(DBTestCase):
    def test_inserts_a_notification_row_with_payload(self):
        user_id = self.create_user(email="a@example.com", username="alice")

        add_notification(user_id, "like_received", '{"from_user_id": 2}')

        row = query_one("SELECT type, payload, is_read FROM notifications WHERE user_id = ?", (user_id,))
        self.assertEqual(row["type"], "like_received")
        self.assertEqual(row["payload"], '{"from_user_id": 2}')
        self.assertEqual(row["is_read"], 0)


class LoginRequiredTests(DBTestCase):
    def test_raises_api_error_when_no_current_user(self):
        g.current_user = None

        @login_required
        def protected():
            return "ok"

        with self.assertRaises(APIError) as ctx:
            protected()
        self.assertEqual(ctx.exception.status, 401)

    def test_calls_wrapped_function_when_authenticated(self):
        g.current_user = {"id": 1}

        @login_required
        def protected():
            return "ok"

        self.assertEqual(protected(), "ok")


if __name__ == "__main__":
    unittest.main()
