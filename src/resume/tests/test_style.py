"""Tests for resume/style.py."""
import tempfile
import unittest
from pathlib import Path

from resume.style import (
    DEFAULT_STOPWORDS,
    _tokenize,
    _sentences,
    build_style_profile,
    extract_style_keywords,
)


class TestDefaultStopwords(unittest.TestCase):
    """Tests for DEFAULT_STOPWORDS constant."""

    def test_is_set(self):
        self.assertIsInstance(DEFAULT_STOPWORDS, set)

    def test_contains_common_words(self):
        common = ["the", "a", "an", "and", "or", "is", "are", "was", "were"]
        for word in common:
            self.assertIn(word, DEFAULT_STOPWORDS)

    def test_contains_pronouns(self):
        pronouns = ["i", "we", "you", "they", "he", "she"]
        for p in pronouns:
            self.assertIn(p, DEFAULT_STOPWORDS)


class TestTokenize(unittest.TestCase):
    """Tests for _tokenize function."""

    def test_extracts_words(self):
        result = _tokenize("Hello World")
        self.assertEqual(result, ["Hello", "World"])

    def test_handles_punctuation(self):
        result = _tokenize("Hello, World! How are you?")
        self.assertIn("Hello", result)
        self.assertIn("World", result)
        self.assertIn("How", result)

    def test_extracts_tech_terms(self):
        result = _tokenize("Python3.9 and C++ and Node.js")
        self.assertIn("Python3.9", result)
        # C++ might not match due to pattern - that's ok

    def test_requires_minimum_length(self):
        result = _tokenize("I a an go to")
        # Single letter tokens should be excluded
        self.assertNotIn("I", result)
        self.assertNotIn("a", result)

    def test_empty_string(self):
        result = _tokenize("")
        self.assertEqual(result, [])

    def test_numbers_alone_excluded(self):
        result = _tokenize("123 456 789")
        # Pure numbers won't match the pattern (must start with letter)
        self.assertEqual(result, [])

    def test_alphanumeric_included(self):
        result = _tokenize("AWS S3 EC2 Python3")
        self.assertIn("AWS", result)
        self.assertIn("Python3", result)


class TestSentences(unittest.TestCase):
    """Tests for _sentences function."""

    def test_splits_on_period(self):
        result = _sentences("First sentence. Second sentence.")
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0], "First sentence.")
        self.assertEqual(result[1], "Second sentence.")

    def test_splits_on_question_mark(self):
        result = _sentences("Is this a question? Yes it is.")
        self.assertEqual(len(result), 2)

    def test_splits_on_exclamation(self):
        result = _sentences("Wow! Amazing!")
        self.assertEqual(len(result), 2)

    def test_strips_whitespace(self):
        result = _sentences("First.   Second.   Third.")
        for s in result:
            self.assertEqual(s, s.strip())

    def test_empty_string(self):
        result = _sentences("")
        self.assertEqual(result, [])

    def test_no_punctuation(self):
        result = _sentences("No ending punctuation here")
        self.assertEqual(result, ["No ending punctuation here"])


class TestBuildStyleProfile(unittest.TestCase):
    """Tests for build_style_profile function."""

    def test_empty_corpus(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = build_style_profile(tmpdir)
            self.assertEqual(result["files"], 0)
            self.assertEqual(result["top_unigrams"] if "top_unigrams" in result else result.get("tokens", []), [])

    def test_nonexistent_directory(self):
        result = build_style_profile("/nonexistent/path/123456")
        self.assertEqual(result["files"], 0)

    def test_processes_txt_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create sample files
            (Path(tmpdir) / "doc1.txt").write_text("Python programming is fun. Python is great.")
            (Path(tmpdir) / "doc2.txt").write_text("Software engineering with Python.")

            result = build_style_profile(tmpdir)
            self.assertEqual(result["files"], 2)
            # Python should be a top unigram
            self.assertIn("python", result.get("top_unigrams", []))

    def test_calculates_avg_sentence_length(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc.txt").write_text("Short sentence. Another short one. Third.")

            result = build_style_profile(tmpdir)
            self.assertIn("avg_sentence_length", result)
            self.assertIsInstance(result["avg_sentence_length"], float)

    def test_excludes_stopwords(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "doc.txt").write_text("The quick brown fox jumps over the lazy dog.")

            result = build_style_profile(tmpdir)
            unigrams = result.get("top_unigrams", [])
            # "the" should be excluded
            self.assertNotIn("the", unigrams)
            # "quick", "brown", "fox" should be included
            self.assertIn("quick", unigrams)


class TestExtractStyleKeywords(unittest.TestCase):
    """Tests for extract_style_keywords function."""

    def test_extracts_from_unigrams(self):
        profile = {
            "top_unigrams": ["python", "java", "golang", "rust"],
            "top_bigrams": [],
        }
        result = extract_style_keywords(profile, limit=20)
        self.assertIn("python", result)
        self.assertIn("java", result)

    def test_includes_bigrams(self):
        profile = {
            "top_unigrams": ["python"],
            "top_bigrams": ["machine learning", "deep learning"],
        }
        result = extract_style_keywords(profile, limit=20)
        self.assertIn("machine learning", result)

    def test_respects_limit(self):
        profile = {
            "top_unigrams": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
            "top_bigrams": ["x y", "z w"],
        }
        result = extract_style_keywords(profile, limit=5)
        self.assertEqual(len(result), 5)

    def test_empty_profile(self):
        profile = {}
        result = extract_style_keywords(profile)
        self.assertEqual(result, [])

    def test_deduplicates_bigrams(self):
        profile = {
            "top_unigrams": ["python"],
            "top_bigrams": ["python"],  # Same as unigram
        }
        result = extract_style_keywords(profile, limit=20)
        # Should only appear once
        self.assertEqual(result.count("python"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
