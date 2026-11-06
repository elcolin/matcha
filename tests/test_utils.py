import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from email_validator import EmailNotValidError
from flask import g

from app.db import execute, query_one
from app.utils import (
    APIError,
    add_notification,
    format_datetime,
    is_blocked_between,
    is_match,
    login_required,
    normalize_email,
    time_ago,
    update_popularity,
)
from tests.helpers import DBTestCase



class NormalizeEmailTests(unittest.TestCase):
    def test_lowercases_local_part_and_domain(self):
        self.assertEqual(normalize_email("Taken@Example.COM"), "taken@example.com")

    def test_invalid_address_raises(self):
        with self.assertRaises(EmailNotValidError):
            normalize_email("not-an-email")


class EmailUniquenessSchemaTests(DBTestCase):
    def test_case_variant_of_existing_email_violates_unique_constraint(self):
        self.create_user(email="a@x.com", username="first")
        with self.assertRaises(sqlite3.IntegrityError):
            self.create_user(email="A@x.com", username="second")


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


class TimeAgoTests(unittest.TestCase):
    NOW = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)

    def _ago(self, **delta):
        return time_ago((self.NOW - timedelta(**delta)).isoformat(), now=self.NOW)

    def test_missing_or_invalid_value_returns_none(self):
        self.assertIsNone(time_ago(None, now=self.NOW))
        self.assertIsNone(time_ago("", now=self.NOW))
        self.assertIsNone(time_ago("not a date", now=self.NOW))

    def test_under_a_minute_is_just_now(self):
        self.assertEqual(self._ago(seconds=30), "just now")

    def test_future_timestamp_is_just_now(self):
        self.assertEqual(self._ago(seconds=-30), "just now")

    def test_units_and_pluralization(self):
        self.assertEqual(self._ago(minutes=1), "1 minute ago")
        self.assertEqual(self._ago(minutes=5), "5 minutes ago")
        self.assertEqual(self._ago(hours=1), "1 hour ago")
        self.assertEqual(self._ago(hours=2, minutes=59), "2 hours ago")
        self.assertEqual(self._ago(days=1), "1 day ago")
        self.assertEqual(self._ago(days=2), "2 days ago")
        self.assertEqual(self._ago(days=60), "2 months ago")
        self.assertEqual(self._ago(days=400), "1 year ago")

    def test_naive_timestamp_is_treated_as_utc(self):
        naive = (self.NOW - timedelta(hours=3)).replace(tzinfo=None).isoformat()
        self.assertEqual(time_ago(naive, now=self.NOW), "3 hours ago")


class FormatDatetimeTests(unittest.TestCase):
    def test_missing_or_invalid_value_returns_none(self):
        self.assertIsNone(format_datetime(None))
        self.assertIsNone(format_datetime(""))
        self.assertIsNone(format_datetime("not a date"))

    def test_formats_aware_timestamp_in_utc(self):
        self.assertEqual(
            format_datetime("2026-11-04T14:32:57.123456+00:00"),
            "Nov 4, 2026 at 14:32 UTC",
        )

    def test_converts_other_timezones_to_utc(self):
        self.assertEqual(
            format_datetime("2026-11-04T09:05:00+02:00"),
            "Nov 4, 2026 at 07:05 UTC",
        )

    def test_naive_timestamp_is_treated_as_utc(self):
        self.assertEqual(
            format_datetime("2026-01-09 08:03:00"),
            "Jan 9, 2026 at 08:03 UTC",
        )


if __name__ == "__main__":
    unittest.main()
