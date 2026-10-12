import unittest
from datetime import datetime, timedelta, timezone

from app.db import execute
from app.profile.routes import _compute_online, _profile_payload
from tests.helpers import DBTestCase


def _iso(delta_seconds):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


class ComputeOnlineTests(unittest.TestCase):
    def test_none_is_offline(self):
        self.assertFalse(_compute_online(None))

    def test_future_timestamp_is_online(self):
        self.assertTrue(_compute_online(_iso(30)))

    def test_past_timestamp_is_offline(self):
        self.assertFalse(_compute_online(_iso(-30)))


class ProfilePayloadOnlineTests(DBTestCase):
    def test_online_true_when_online_until_in_future(self):
        user_id = self.create_user(email="a@example.com", username="alice")
        execute("UPDATE users SET online_until = ? WHERE id = ?", (_iso(30), user_id))

        payload = _profile_payload(user_id)

        self.assertTrue(payload["online"])

    def test_online_false_when_online_until_in_past(self):
        user_id = self.create_user(email="b@example.com", username="bob")
        execute("UPDATE users SET online_until = ? WHERE id = ?", (_iso(-30), user_id))

        payload = _profile_payload(user_id)

        self.assertFalse(payload["online"])

    def test_online_false_when_online_until_is_null(self):
        user_id = self.create_user(email="c@example.com", username="carol")

        payload = _profile_payload(user_id)

        self.assertFalse(payload["online"])


if __name__ == "__main__":
    unittest.main()
