import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scripts.generate_chat import (
    build_prompt,
    clean_generated_text,
    is_valid_message,
    stagger_timestamps,
)


class IsValidMessageTests(unittest.TestCase):
    def test_accepts_short_casual_french_message(self):
        self.assertTrue(is_valid_message("Salut, ca va et toi ?"))

    def test_rejects_empty_message(self):
        self.assertFalse(is_valid_message(""))
        self.assertFalse(is_valid_message("   "))

    def test_rejects_too_long_message(self):
        long_text = " ".join(["mot"] * 60)
        self.assertFalse(is_valid_message(long_text))

    def test_rejects_ai_refusal_style_message(self):
        self.assertFalse(is_valid_message("As an AI, I cannot chat like a real person."))
        self.assertFalse(is_valid_message("Bien sûr, voici un message pour toi."))

    def test_rejects_message_with_brackets(self):
        self.assertFalse(is_valid_message("Salut [insert name here], comment vas-tu ?"))

    def test_rejects_message_mentioning_being_an_assistant(self):
        self.assertFalse(is_valid_message("Je suis un assistant virtuel, je ne peux pas sortir."))


class CleanGeneratedTextTests(unittest.TestCase):
    def test_strips_leading_speaker_label(self):
        self.assertEqual(clean_generated_text("A: Salut toi !", label="A"), "Salut toi !")

    def test_strips_surrounding_quotes(self):
        self.assertEqual(clean_generated_text('"Coucou, ca va ?"'), "Coucou, ca va ?")

    def test_keeps_only_first_line(self):
        self.assertEqual(
            clean_generated_text("Salut !\nEt un message en trop."),
            "Salut !",
        )


class BuildPromptTests(unittest.TestCase):
    def test_empty_history_ends_with_bare_next_label(self):
        prompt = build_prompt([], "A")
        self.assertTrue(prompt.endswith("\n\nA:"))

    def test_includes_full_transcript_in_order(self):
        history = [("A", "Hey!"), ("B", "Hi, how are you?"), ("A", "Good, you?")]
        prompt = build_prompt(history, "B")
        transcript = "A: Hey!\nB: Hi, how are you?\nA: Good, you?"
        self.assertTrue(prompt.endswith(f"{transcript}\nB:"))

    def test_next_label_is_last_line(self):
        prompt = build_prompt([("A", "Salut")], "B")
        self.assertEqual(prompt.splitlines()[-1], "B:")

    def test_intro_precedes_transcript_separated_by_blank_line(self):
        prompt = build_prompt([("A", "Hey")], "B")
        intro, rest = prompt.split("\n\n", 1)
        self.assertTrue(intro)
        self.assertTrue(rest.startswith("A: Hey"))


class StaggerTimestampsTests(unittest.TestCase):
    def test_returns_requested_count(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        timestamps = stagger_timestamps(start, 5)
        self.assertEqual(len(timestamps), 5)

    def test_timestamps_are_strictly_increasing_and_after_start(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        timestamps = stagger_timestamps(start, 6)

        previous = start
        for ts in timestamps:
            self.assertGreater(ts, previous)
            previous = ts

    def test_returns_empty_list_for_zero_count(self):
        self.assertEqual(stagger_timestamps(datetime.now(), 0), [])

    def test_respects_gap_bounds(self):
        start = datetime(2026, 1, 1, 12, 0, 0)
        timestamps = stagger_timestamps(start, 3, min_gap_minutes=10, max_gap_minutes=10)

        self.assertEqual(timestamps, [start + timedelta(minutes=10 * (i + 1)) for i in range(3)])


if __name__ == "__main__":
    unittest.main()
