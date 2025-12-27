"""Tests for mail/llm_adapter.py text summarization utilities."""

import unittest

from mail.llm_adapter import summarize_text


class SummarizeTextTests(unittest.TestCase):
    def test_empty_text(self):
        result = summarize_text("")
        self.assertEqual(result, "(no content)")

    def test_none_text(self):
        result = summarize_text(None)
        self.assertEqual(result, "(no content)")

    def test_whitespace_only(self):
        result = summarize_text("   \n\t  ")
        self.assertEqual(result, "(no content)")

    def test_short_text_unchanged(self):
        text = "This is a short sentence."
        result = summarize_text(text)
        self.assertEqual(result, "This is a short sentence.")

    def test_respects_max_words(self):
        text = "One two three four five six seven eight nine ten eleven twelve."
        result = summarize_text(text, max_words=5)
        words = result.split()
        self.assertLessEqual(len(words), 5)

    def test_sentence_boundary_splitting(self):
        text = "First sentence. Second sentence. Third sentence."
        result = summarize_text(text, max_words=10)
        # Should prefer complete sentences
        self.assertIn("First sentence.", result)

    def test_collapses_whitespace(self):
        text = "Word1    Word2\n\nWord3\tWord4"
        result = summarize_text(text)
        self.assertNotIn("  ", result)
        self.assertNotIn("\n", result)
        self.assertNotIn("\t", result)

    def test_question_mark_boundary(self):
        text = "Is this a question? Yes it is. Another statement."
        result = summarize_text(text, max_words=8)
        self.assertIn("Is this a question?", result)

    def test_exclamation_boundary(self):
        text = "Wow! That's amazing. More text here."
        result = summarize_text(text, max_words=5)
        self.assertIn("Wow!", result)

    def test_instructions_adds_prefix(self):
        text = "Some content here."
        result = summarize_text(text, instructions="Be concise")
        self.assertTrue(result.startswith("Summary:"))

    def test_without_instructions_no_prefix(self):
        text = "Some content here."
        result = summarize_text(text)
        self.assertFalse(result.startswith("Summary:"))

    def test_long_text_truncated(self):
        text = " ".join([f"word{i}" for i in range(200)])
        result = summarize_text(text, max_words=50)
        words = result.split()
        self.assertLessEqual(len(words), 50)

    def test_preserves_content_when_under_limit(self):
        text = "This is exactly the text."
        result = summarize_text(text, max_words=100)
        self.assertEqual(result, "This is exactly the text.")

    def test_multiple_sentence_types(self):
        text = "Statement one. Question two? Exclamation three! Statement four."
        result = summarize_text(text, max_words=20)
        # Should include multiple sentences
        self.assertIn("Statement one.", result)
        self.assertIn("Question two?", result)

    def test_partial_sentence_when_needed(self):
        text = "This is a very long sentence that goes on and on with many words."
        result = summarize_text(text, max_words=5)
        words = result.split()
        self.assertLessEqual(len(words), 5)

    def test_default_max_words(self):
        # Default is 120 words
        text = " ".join([f"word{i}" for i in range(150)])
        result = summarize_text(text)
        words = result.split()
        self.assertLessEqual(len(words), 120)

    def test_unicode_content(self):
        text = "Café résumé naïve. Émojis 🎉 work too."
        result = summarize_text(text)
        self.assertIn("Café", result)

    def test_strips_leading_trailing_whitespace(self):
        text = "  Content with spaces.  "
        result = summarize_text(text)
        self.assertFalse(result.startswith(" "))
        self.assertFalse(result.endswith(" "))


if __name__ == "__main__":
    unittest.main()
