import importlib
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.db import query_one
from app.profile.routes import _compute_online
from tests.helpers import DBTestCase

# scripts.generate_users builds a Flask app at import time.
with patch("app.create_app", return_value=MagicMock()):
    create_bot_user_module = importlib.import_module("scripts.create_bot_user")


@patch("scripts.create_bot_user.create_photos")
@patch("scripts.create_bot_user.generate_profile")
class CreateBotUserTests(DBTestCase):
    def test_creates_verified_bot_prefixed_user(self, _mock_profile, _mock_photos):
        bot = create_bot_user_module.create_bot_user("ana")
        row = query_one("SELECT username, email_verified FROM users WHERE id = ?", (bot["id"],))
        self.assertEqual(row["username"], "bot_ana")
        self.assertEqual(row["email_verified"], 1)

    def test_sets_presence_fields(self, _mock_profile, _mock_photos):
        bot = create_bot_user_module.create_bot_user("ana")
        row = query_one(
            "SELECT last_seen_at, online_until FROM users WHERE id = ?", (bot["id"],)
        )
        self.assertIsNotNone(row["last_seen_at"])
        # Offline until scripts/chat_bot_responder.py runs and keeps it online;
        # the stored value must still be parseable by _compute_online.
        self.assertFalse(_compute_online(row["online_until"]))


if __name__ == "__main__":
    unittest.main()
