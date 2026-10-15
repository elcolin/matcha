import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.chat_bot_responder import (
    BOT_LABEL,
    MAX_GENERATION_ATTEMPTS,
    MODEL,
    PARTNER_LABEL,
    build_bot_history,
    build_reply_prompt,
    generate_bot_reply,
    is_bot_username,
    needs_bot_reply,
    run,
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

    def test_does_not_clean_or_truncate_partner_content(self):
        # `clean_generated_text` (quote/newline/label stripping) must only ever be
        # applied to the bot's own generated reply, never to history read back from
        # the database -- otherwise the model would receive a mangled version of
        # what its partner actually said.
        raw_content = '  "Salut !"\net une deuxieme ligne  '
        rows = [{"sender_id": 2, "content": raw_content}]
        history = build_bot_history(rows, bot_id=1)
        self.assertEqual(history, [(PARTNER_LABEL, raw_content)])


class BuildReplyPromptTests(unittest.TestCase):
    def test_instructs_bot_to_answer_partner_last_message(self):
        history = [(PARTNER_LABEL, "I just adopted a golden retriever puppy named Max!")]
        prompt = build_reply_prompt(history, BOT_LABEL, PARTNER_LABEL)
        self.assertIn("I just adopted a golden retriever puppy named Max!", prompt)
        self.assertIn(PARTNER_LABEL, prompt.rsplit("\n", 1)[0].splitlines()[-1])

    def test_ends_with_bare_bot_label(self):
        history = [(PARTNER_LABEL, "Hey!")]
        prompt = build_reply_prompt(history, BOT_LABEL, PARTNER_LABEL)
        self.assertEqual(prompt.splitlines()[-1], f"{BOT_LABEL}:")

    def test_falls_back_to_plain_prompt_without_any_partner_message(self):
        # The bot never starts a conversation, but this keeps the helper total:
        # with no partner line to react to, it degrades to the base prompt.
        history = [(BOT_LABEL, "Hey!")]
        prompt = build_reply_prompt(history, BOT_LABEL, PARTNER_LABEL)
        self.assertNotIn("Respond directly", prompt)
        self.assertEqual(prompt.splitlines()[-1], f"{BOT_LABEL}:")

    def test_reacts_to_the_most_recent_partner_message(self):
        history = [
            (PARTNER_LABEL, "old message"),
            (BOT_LABEL, "ok"),
            (PARTNER_LABEL, "latest message"),
        ]
        prompt = build_reply_prompt(history, BOT_LABEL, PARTNER_LABEL)
        self.assertIn("latest message", prompt)
        self.assertNotIn("Respond directly to what A just said above (\"old message\")", prompt)


class GenerateBotReplyPromptRegressionTests(unittest.TestCase):
    """Empirically pins down that the wiring from DB history to the prompt actually
    sent to Ollama is correct: a unique marker placed in the partner's last message
    must be found in the exact prompt string passed to `call_ollama`."""

    @patch("scripts.chat_bot_responder.call_ollama")
    @patch("scripts.chat_bot_responder.query_all")
    def test_prompt_sent_to_ollama_contains_partner_last_message(
        self, mock_query_all, mock_call_ollama
    ):
        marker = "UNIQUE_MARKER_PUPPY_MAX"
        mock_query_all.return_value = [
            {"sender_id": 2, "content": "Hey!"},
            {"sender_id": 1, "content": "Hi there"},
            {"sender_id": 2, "content": f"Guess what, {marker}!"},
        ]
        mock_call_ollama.return_value = f"{BOT_LABEL}: sure thing"

        generate_bot_reply(bot_id=1, partner_id=2)

        self.assertTrue(mock_call_ollama.called)
        prompt_sent = mock_call_ollama.call_args[0][0]
        self.assertIn(marker, prompt_sent)
        # the marker must appear on the transcript's last partner line, right
        # before the bot's own turn -- not buried/dropped by truncation.
        lines = prompt_sent.strip().splitlines()
        next_label_index = lines.index(f"{BOT_LABEL}:")
        self.assertTrue(any(marker in line for line in lines[:next_label_index]))


class GenerateBotReplyMislabelGuardTests(unittest.TestCase):
    """Small instruct models sometimes drift and complete the partner's turn
    instead of the bot's own (i.e. answer prefixed with `A:` instead of `B:`),
    which leaks that literal prefix into the message actually sent since
    `clean_generated_text` only strips the *expected* label. This must be
    treated as an invalid candidate and retried, like any other malformed
    generation."""

    @patch("scripts.chat_bot_responder.call_ollama")
    @patch("scripts.chat_bot_responder.query_all")
    def test_retries_when_model_answers_as_partner_label(self, mock_query_all, mock_call_ollama):
        mock_query_all.return_value = [{"sender_id": 2, "content": "What's up?"}]
        mock_call_ollama.side_effect = [
            f"{PARTNER_LABEL}: I'm doing great, thanks for asking!",
            f"{BOT_LABEL}: I'm doing great, thanks for asking!",
        ]

        reply = generate_bot_reply(bot_id=1, partner_id=2)

        self.assertEqual(reply, "I'm doing great, thanks for asking!")
        self.assertEqual(mock_call_ollama.call_count, 2)

    @patch("scripts.chat_bot_responder.call_ollama")
    @patch("scripts.chat_bot_responder.query_all")
    def test_gives_up_after_max_attempts_if_always_mislabeled(
        self, mock_query_all, mock_call_ollama
    ):
        mock_query_all.return_value = [{"sender_id": 2, "content": "What's up?"}]
        mock_call_ollama.return_value = f"{PARTNER_LABEL}: still the wrong speaker"

        reply = generate_bot_reply(bot_id=1, partner_id=2)

        self.assertIsNone(reply)
        self.assertEqual(mock_call_ollama.call_count, MAX_GENERATION_ATTEMPTS)

    @patch("scripts.chat_bot_responder.call_ollama")
    @patch("scripts.chat_bot_responder.query_all")
    def test_single_message_conversation_still_produces_a_reply(
        self, mock_query_all, mock_call_ollama
    ):
        mock_query_all.return_value = [{"sender_id": 2, "content": "Hi there!"}]
        mock_call_ollama.return_value = f"{BOT_LABEL}: Hey, nice to meet you!"

        reply = generate_bot_reply(bot_id=1, partner_id=2)

        self.assertEqual(reply, "Hey, nice to meet you!")


class GenerateBotReplyEchoGuardTests(unittest.TestCase):
    """Small instruct models sometimes just parrot back the partner's own last
    message instead of generating an actual reply. That must be treated as an
    invalid candidate and retried, like any other malformed generation --
    otherwise the partner sees their own message sent back to them."""

    @patch("scripts.chat_bot_responder.call_ollama")
    @patch("scripts.chat_bot_responder.query_all")
    def test_retries_when_model_echoes_partner_message(self, mock_query_all, mock_call_ollama):
        mock_query_all.return_value = [{"sender_id": 2, "content": "What's up?"}]
        mock_call_ollama.side_effect = [
            f"{BOT_LABEL}: What's up?",
            f"{BOT_LABEL}: Not much, you?",
        ]

        reply = generate_bot_reply(bot_id=1, partner_id=2)

        self.assertEqual(reply, "Not much, you?")
        self.assertEqual(mock_call_ollama.call_count, 2)

    @patch("scripts.chat_bot_responder.call_ollama")
    @patch("scripts.chat_bot_responder.query_all")
    def test_echo_check_ignores_case_and_surrounding_punctuation(
        self, mock_query_all, mock_call_ollama
    ):
        mock_query_all.return_value = [{"sender_id": 2, "content": "What's up?"}]
        mock_call_ollama.side_effect = [
            f'{BOT_LABEL}: "  WHAT\'S UP?  "',
            f"{BOT_LABEL}: Not much, you?",
        ]

        reply = generate_bot_reply(bot_id=1, partner_id=2)

        self.assertEqual(reply, "Not much, you?")
        self.assertEqual(mock_call_ollama.call_count, 2)

    @patch("scripts.chat_bot_responder.call_ollama")
    @patch("scripts.chat_bot_responder.query_all")
    def test_gives_up_after_max_attempts_if_always_echoed(
        self, mock_query_all, mock_call_ollama
    ):
        mock_query_all.return_value = [{"sender_id": 2, "content": "What's up?"}]
        mock_call_ollama.return_value = f"{BOT_LABEL}: What's up?"

        reply = generate_bot_reply(bot_id=1, partner_id=2)

        self.assertIsNone(reply)
        self.assertEqual(mock_call_ollama.call_count, MAX_GENERATION_ATTEMPTS)


class RunAntiLoopGuardTests(unittest.TestCase):
    """Lightweight mocked integration test: runs a single loop iteration of `run`
    with every I/O boundary mocked, to check the bot-vs-bot infinite loop guard end
    to end rather than only at the `is_bot_username` unit level."""

    def _run_one_cycle(self, last_sender_username, mock_check, mock_resolve_bots,
                        mock_find_pairs, mock_last_message, mock_generate_reply,
                        mock_insert, mock_sleep):
        mock_resolve_bots.return_value = [{"id": 1, "username": "bot_ana"}]
        mock_find_pairs.return_value = [{"id": 3, "username": "partner"}]
        mock_last_message.return_value = {
            "sender_id": 3,
            "receiver_id": 1,
            "content": "Hi",
            "sender_username": last_sender_username,
        }
        mock_generate_reply.return_value = "Hey!"
        mock_sleep.side_effect = KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            run()

    @patch("scripts.chat_bot_responder.time.sleep")
    @patch("scripts.chat_bot_responder.insert_bot_message")
    @patch("scripts.chat_bot_responder.generate_bot_reply")
    @patch("scripts.chat_bot_responder.last_message_between")
    @patch("scripts.chat_bot_responder.find_bot_pairs")
    @patch("scripts.chat_bot_responder.resolve_bots")
    @patch("scripts.chat_bot_responder.check_ollama_available")
    def test_never_replies_to_another_bot(
        self, mock_check, mock_resolve_bots, mock_find_pairs, mock_last_message,
        mock_generate_reply, mock_insert, mock_sleep,
    ):
        self._run_one_cycle(
            "bot_carl", mock_check, mock_resolve_bots, mock_find_pairs,
            mock_last_message, mock_generate_reply, mock_insert, mock_sleep,
        )
        mock_generate_reply.assert_not_called()
        mock_insert.assert_not_called()

    @patch("scripts.chat_bot_responder.time.sleep")
    @patch("scripts.chat_bot_responder.insert_bot_message")
    @patch("scripts.chat_bot_responder.generate_bot_reply")
    @patch("scripts.chat_bot_responder.last_message_between")
    @patch("scripts.chat_bot_responder.find_bot_pairs")
    @patch("scripts.chat_bot_responder.resolve_bots")
    @patch("scripts.chat_bot_responder.check_ollama_available")
    def test_replies_to_a_regular_partner(
        self, mock_check, mock_resolve_bots, mock_find_pairs, mock_last_message,
        mock_generate_reply, mock_insert, mock_sleep,
    ):
        self._run_one_cycle(
            "carla", mock_check, mock_resolve_bots, mock_find_pairs,
            mock_last_message, mock_generate_reply, mock_insert, mock_sleep,
        )
        mock_generate_reply.assert_called_once_with(1, 3, model=MODEL)
        mock_insert.assert_called_once_with(1, 3, "Hey!")


if __name__ == "__main__":
    unittest.main()
