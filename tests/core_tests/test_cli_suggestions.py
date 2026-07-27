"""Tests for core/cli_suggestions.py — fuzzy 'did you mean' suggestions."""
from __future__ import annotations

import unittest

from core.cli_suggestions import suggest_command, suggest_flags


class TestSuggestCommand(unittest.TestCase):
    """Test suggest_command() scoring and ranking."""

    CHOICES = ["labels", "filters", "forwarding", "signatures", "status", "export", "import"]

    def test_exact_match(self):
        result = suggest_command("labels", self.CHOICES)
        self.assertEqual(result[0], "labels")

    def test_starts_with_match(self):
        result = suggest_command("lab", self.CHOICES)
        self.assertIn("labels", result)
        self.assertEqual(result[0], "labels")

    def test_contains_match(self):
        result = suggest_command("orward", self.CHOICES)
        self.assertIn("forwarding", result)

    def test_typo_suggestion(self):
        # "labelz" should suggest "labels"
        result = suggest_command("labelz", self.CHOICES)
        self.assertIn("labels", result)

    def test_no_match_returns_empty(self):
        result = suggest_command("xyzzy", ["labels", "filters"])
        self.assertEqual(result, [])

    def test_empty_query_returns_empty(self):
        result = suggest_command("", self.CHOICES)
        self.assertEqual(result, [])

    def test_empty_choices_returns_empty(self):
        result = suggest_command("labels", [])
        self.assertEqual(result, [])

    def test_max_results_respected(self):
        result = suggest_command("s", self.CHOICES, max_results=2)
        self.assertLessEqual(len(result), 2)

    def test_word_part_overlap(self):
        # "sign" partially matches "signatures" via word parts
        result = suggest_command("sign", ["signatures", "filters"])
        self.assertIn("signatures", result)

    def test_results_are_ranked(self):
        # Exact match should beat starts-with which should beat contains
        choices = ["hello-world", "hello", "say-hello"]
        result = suggest_command("hello", choices)
        if result:
            self.assertEqual(result[0], "hello")

    def test_case_insensitive(self):
        result = suggest_command("LABELS", ["labels", "filters"])
        self.assertIn("labels", result)


class TestSuggestFlags(unittest.TestCase):
    """Test suggest_flags() using difflib."""

    FLAGS = ["--verbose", "--quiet", "--dry-run", "--output", "--profile", "--format"]

    def test_close_match(self):
        result = suggest_flags("--verbos", self.FLAGS)
        self.assertIn("--verbose", result)

    def test_exact_match(self):
        result = suggest_flags("--verbose", self.FLAGS)
        self.assertIn("--verbose", result)

    def test_no_close_match_returns_empty(self):
        result = suggest_flags("--xyzzy", self.FLAGS)
        self.assertEqual(result, [])

    def test_empty_flag_returns_empty(self):
        result = suggest_flags("", self.FLAGS)
        self.assertEqual(result, [])

    def test_empty_choices_returns_empty(self):
        result = suggest_flags("--verbose", [])
        self.assertEqual(result, [])

    def test_max_results_respected(self):
        # All flags contain "-" so multiple could match
        result = suggest_flags("--dry-ru", self.FLAGS, max_results=2)
        self.assertLessEqual(len(result), 2)

    def test_short_flag_suggestion(self):
        flags = ["-v", "--verbose", "-q", "--quiet"]
        result = suggest_flags("-vv", flags)
        # Should not error; result may be empty or contain a suggestion
        self.assertIsInstance(result, list)

    def test_returns_list(self):
        result = suggest_flags("--verbos", self.FLAGS)
        self.assertIsInstance(result, list)


if __name__ == "__main__":
    unittest.main()
