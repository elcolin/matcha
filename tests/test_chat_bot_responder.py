import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.chat_bot_responder import (
    BOT_LABEL,
    PARTNER_LABEL,
    build_bot_history,
    is_bot_username,
    needs_bot_reply,
)


class IsBotUsernameTests(unittest.TestCase):
    def test_accepts_bot_prefixed_username(self):
        self.assertTrue(is_bot_username("bot_ana"))

    def test_rejects_empty_username(self):
        self.assertFalse(is_bot_username(""))

    def test_rejects_none_username(self):
        self.assertFalse(is_bot_username(None))

    def test_rejects_regular_username(self):
        self.assertFalse(is_bot_username("analyste"))


class NeedsBotReplyTests(unittest.TestCase):
    def test_no_last_message_means_no_reply(self):
        self.assertFalse(needs_bot_reply(None, bot_id=1))

    def test_last_message_from_bot_itself_means_no_reply(self):
        last_message = {"sender_id": 1, "content": "Hey!"}
        self.assertFalse(needs_bot_reply(last_message, bot_id=1))

    def test_last_message_from_partner_means_reply(self):
        last_message = {"sender_id": 2, "content": "Hey!"}
        self.assertTrue(needs_bot_reply(last_message, bot_id=1))


class BuildBotHistoryTests(unittest.TestCase):
    def test_empty_rows_returns_empty_list(self):
        self.assertEqual(build_bot_history([], bot_id=1), [])

    def test_labels_bot_and_partner_messages_in_order(self):
        rows = [
            {"sender_id": 2, "content": "Salut !"},
            {"sender_id": 1, "content": "Hey, ca va ?"},
            {"sender_id": 2, "content": "Oui et toi ?"},
        ]
        history = build_bot_history(rows, bot_id=1)
        self.assertEqual(
            history,
            [
                (PARTNER_LABEL, "Salut !"),
                (BOT_LABEL, "Hey, ca va ?"),
                (PARTNER_LABEL, "Oui et toi ?"),
            ],
        )

    def test_does_not_mutate_input_rows(self):
        rows = [{"sender_id": 2, "content": "Salut !"}]
        original = list(rows)
        build_bot_history(rows, bot_id=1)
        self.assertEqual(rows, original)


if __name__ == "__main__":
    unittest.main()
