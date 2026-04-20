"""Tests for mail/llm_adapter.py."""

from __future__ import annotations

import unittest

from mail.llm_adapter import summarize_text


class TestSummarizeTextEmpty(unittest.TestCase):
    """Covers line 27: empty/whitespace-only input returns sentinel."""

    def test_empty_string_returns_no_content(self):
        self.assertEqual(summarize_text(""), "(no content)")

    def test_whitespace_only_returns_no_content(self):
        self.assertEqual(summarize_text("   \n\t  "), "(no content)")

class TestSummarizeTextBasic(unittest.TestCase):
    """Covers the happy path through sentence splitting."""

    def test_single_sentence_returned_verbatim(self):
        result = summarize_text("Hello world.")
        self.assertEqual(result, "Hello world.")

    def test_multiple_sentences_within_budget(self):
        text = "First sentence. Second sentence. Third sentence."
        result = summarize_text(text, max_words=20)
        self.assertIn("First sentence", result)
        self.assertIn("Second sentence", result)

    def test_whitespace_collapsed(self):
        result = summarize_text("Hello   world.  How   are  you.")
        self.assertNotIn("  ", result)


class TestSummarizeTextWordBudget(unittest.TestCase):
    """Covers lines 44-48 and 52: trimming within a sentence and budget cap."""

    def test_long_single_sentence_trimmed_to_max_words(self):
        # One long sentence with no sentence-end boundaries forces trimming.
        words = ["word"] * 200
        text = " ".join(words) + "."
        result = summarize_text(text, max_words=10)
        self.assertLessEqual(len(result.split()), 10)

    def test_exact_budget_hit_stops_loop(self):
        # Craft two sentences whose total words exactly hits max_words (line 52).
        # "One two." = 2 words, "Three four." = 2 words; max_words=4 -> both fit,
        # and words >= max_words triggers break on the second iteration.
        result = summarize_text("One two. Three four.", max_words=4)
        self.assertIn("One two", result)
        self.assertIn("Three four", result)

    def test_budget_overflow_trims_last_sentence(self):
        # "Alpha beta." = 2 words; "gamma delta epsilon." = 3 words; max_words=4
        # First part fits (words=2), second part would push to 5 > 4:
        # remaining=2, so only first two words of second sentence are appended.
        result = summarize_text("Alpha beta. Gamma delta epsilon.", max_words=4)
        result_words = result.split()
        self.assertLessEqual(len(result_words), 4)
        self.assertIn("Alpha", result)

    def test_zero_remaining_words_skips_append(self):
        # If the first sentence exactly exhausts the budget (remaining == 0),
        # the partial-append branch is skipped (line 45 guard: `if remaining > 0`).
        # "a b c d." = 4 words; max_words=4; second sentence should not appear.
        result = summarize_text("a b c d. extra words here.", max_words=4)
        self.assertNotIn("extra", result)


class TestSummarizeTextFallback(unittest.TestCase):
    """Covers line 57: fallback to word-only splitting when sentence split yields nothing."""

    def test_no_sentence_boundaries_falls_back_to_words(self):
        # Text with no sentence-ending punctuation; re.split produces a single
        # part that fits within budget, so `out` is non-empty and the fallback
        # is NOT triggered. Use a max_words of 0 to produce an empty `out`.
        # With max_words=0: first part has w>0 but words+w>0, remaining=0,
        # nothing appended -> summary="" -> fallback runs.
        text = "hello world foo bar"
        result = summarize_text(text, max_words=0)
        # Fallback: s.split()[:0] => "" — still returns empty string joined
        self.assertEqual(result, "")

    def test_fallback_with_small_budget_returns_leading_words(self):
        # Provide text with no punctuation so the whole thing is one "part".
        # max_words=3 -> first part has >3 words, remaining=3, trimmed and appended.
        text = "alpha bravo charlie delta echo"
        result = summarize_text(text, max_words=3)
        self.assertEqual(result, "alpha bravo charlie")


class TestSummarizeTextInstructions(unittest.TestCase):
    """Covers line 61: instructions kwarg prepends 'Summary:' prefix."""

    def test_instructions_adds_summary_prefix(self):
        result = summarize_text("Some content here.", instructions="be brief")
        self.assertTrue(result.startswith("Summary:"))
        self.assertIn("Some content here", result)

    def test_no_instructions_no_prefix(self):
        result = summarize_text("Some content here.")
        self.assertFalse(result.startswith("Summary:"))

    def test_instructions_none_no_prefix(self):
        result = summarize_text("Some content here.", instructions=None)
        self.assertFalse(result.startswith("Summary:"))


if __name__ == "__main__":
    unittest.main()
