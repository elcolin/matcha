import unittest

from app.auth.routes import _is_locked_out
from app.db import execute, query_one
from tests.helpers import DBTestCase


class IsLockedOutTests(DBTestCase):
    def test_no_attempts_is_not_locked_out(self):
        self.assertFalse(_is_locked_out("alice"))

    def test_fewer_failures_than_the_threshold_is_not_locked_out(self):
        for _ in range(5):  # threshold (LOGIN_RATE_MAX_FAILS) is 6
            execute("INSERT INTO login_attempts (username, success) VALUES (?, 0)", ("alice",))

        self.assertFalse(_is_locked_out("alice"))

    def test_reaching_the_threshold_locks_the_account_out(self):
        for _ in range(6):
            execute("INSERT INTO login_attempts (username, success) VALUES (?, 0)", ("alice",))

        self.assertTrue(_is_locked_out("alice"))

    def test_successful_attempts_do_not_count_towards_lockout(self):
        for _ in range(6):
            execute("INSERT INTO login_attempts (username, success) VALUES (?, 1)", ("alice",))

        self.assertFalse(_is_locked_out("alice"))

    def test_lockout_is_scoped_to_the_username(self):
        for _ in range(6):
            execute("INSERT INTO login_attempts (username, success) VALUES (?, 0)", ("alice",))

        self.assertFalse(_is_locked_out("bob"))

    def test_failures_outside_the_rate_window_do_not_count(self):
        for _ in range(6):
            execute(
                "INSERT INTO login_attempts (username, success, attempted_at) VALUES (?, 0, datetime('now', '-20 minutes'))",
                ("alice",),
            )

        # LOGIN_RATE_WINDOW_MINUTES is 15, so 20-minute-old failures are stale.
        self.assertFalse(_is_locked_out("alice"))

    def test_stale_attempts_older_than_two_days_are_purged(self):
        execute(
            "INSERT INTO login_attempts (username, success, attempted_at) VALUES (?, 0, datetime('now', '-3 days'))",
            ("alice",),
        )

        _is_locked_out("alice")

        row = query_one("SELECT COUNT(*) AS c FROM login_attempts WHERE username = ?", ("alice",))
        self.assertEqual(row["c"], 0)


if __name__ == "__main__":
    unittest.main()
