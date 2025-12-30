"""Tests for resume/style.py text analysis functions."""
import tempfile
import unittest
from pathlib import Path

from resume.style import (
    DEFAULT_STOPWORDS,
    _iter_texts,
    _sentences,
    _tokenize,
    build_style_profile,
    extract_style_keywords,
)


class TestTokenize(unittest.TestCase):
    """Tests for _tokenize function."""

    def test_tokenize_simple_words(self):
        """_tokenize should extract simple words."""
        tokens = _tokenize("Hello world from Python")
        self.assertEqual(tokens, ["Hello", "world", "from", "Python"])

    def test_tokenize_with_punctuation(self):
        """_tokenize should handle punctuation."""
        tokens = _tokenize("Hello, world! How are you?")
        self.assertEqual(tokens, ["Hello", "world", "How", "are", "you"])

    def test_tokenize_with_numbers(self):
        """_tokenize should handle words with numbers."""
        tokens = _tokenize("Python3 and C++11 are great")
        self.assertEqual(tokens, ["Python3", "and", "C++11", "are", "great"])

    def test_tokenize_with_special_chars(self):
        """_tokenize should handle words with dots, dashes, underscores."""
        tokens = _tokenize("email@example.com user_name file-name node.js")
        # Pattern requires at least 2 chars after first letter
        self.assertIn("user_name", tokens)
        self.assertIn("file-name", tokens)

    def test_tokenize_empty_string(self):
        """_tokenize should return empty list for empty string."""
        tokens = _tokenize("")
        self.assertEqual(tokens, [])


class TestSentences(unittest.TestCase):
    """Tests for _sentences function."""

    def test_sentences_with_periods(self):
        """_sentences should split on periods."""
        text = "First sentence. Second sentence. Third sentence."
        sents = _sentences(text)
        self.assertEqual(len(sents), 3)
        self.assertEqual(sents[0], "First sentence.")

    def test_sentences_with_mixed_punctuation(self):
        """_sentences should split on !, ?, and ."""
        text = "Question? Answer! Statement."
        sents = _sentences(text)
        self.assertEqual(len(sents), 3)

    def test_sentences_strips_whitespace(self):
        """_sentences should strip whitespace from each sentence."""
        text = "  Sentence one.   Sentence two.  "
        sents = _sentences(text)
        self.assertEqual(sents[0], "Sentence one.")
        self.assertEqual(sents[1], "Sentence two.")

    def test_sentences_empty_string(self):
        """_sentences should return empty list for empty string."""
        sents = _sentences("")
        self.assertEqual(sents, [])


class TestIterTexts(unittest.TestCase):
    """Tests for _iter_texts function."""

    def test_iter_texts_nonexistent_directory(self):
        """_iter_texts should return empty list for nonexistent directory."""
        texts = list(_iter_texts("/nonexistent/path"))
        self.assertEqual(texts, [])

    def test_iter_texts_finds_txt_files(self):
        """_iter_texts should find .txt files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a test file
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text("Test content")

            texts = list(_iter_texts(tmpdir))
            self.assertEqual(len(texts), 1)
            self.assertEqual(texts[0], "Test content")

    def test_iter_texts_finds_md_files(self):
        """_iter_texts should find .md files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.md"
            test_file.write_text("Markdown content")

            texts = list(_iter_texts(tmpdir))
            self.assertEqual(len(texts), 1)
            self.assertEqual(texts[0], "Markdown content")

    def test_iter_texts_recursively(self):
        """_iter_texts should recursively find files in subdirectories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create nested structure
            subdir = Path(tmpdir) / "subdir"
            subdir.mkdir()
            (Path(tmpdir) / "root.txt").write_text("Root")
            (subdir / "nested.txt").write_text("Nested")

            texts = list(_iter_texts(tmpdir))
            self.assertEqual(len(texts), 2)
            self.assertIn("Root", texts)
            self.assertIn("Nested", texts)


class TestBuildStyleProfile(unittest.TestCase):
    """Tests for build_style_profile function."""

    def test_build_style_profile_empty_directory(self):
        """build_style_profile should return empty profile for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            profile = build_style_profile(tmpdir)
            self.assertEqual(profile['files'], 0)
            self.assertEqual(profile['tokens'], [])
            self.assertEqual(profile['bigrams'], [])
            self.assertEqual(profile['avg_sentence_length'], 0.0)

    def test_build_style_profile_with_content(self):
        """build_style_profile should analyze text content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create test file with repeated words
            test_file = Path(tmpdir) / "test.txt"
            test_file.write_text(
                "Python programming. Python development. "
                "Software engineering. Software design."
            )

            profile = build_style_profile(tmpdir, top_n=10)
            self.assertEqual(profile['files'], 1)
            self.assertIn('top_unigrams', profile)
            self.assertIn('top_bigrams', profile)
            self.assertIn('avg_sentence_length', profile)

            # Should find "python" and "software" as top words (stopwords filtered)
            top_words = profile['top_unigrams']
            self.assertIn('python', top_words)
            self.assertIn('software', top_words)

    def test_build_style_profile_filters_stopwords(self):
        """build_style_profile should filter common stopwords."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            # Lots of stopwords, only "important" and "word" are not stopwords
            test_file.write_text(
                "The important word is the most important word in the text."
            )

            profile = build_style_profile(tmpdir, top_n=10)
            top_words = profile['top_unigrams']

            # "the", "is", "in" are stopwords and should not appear
            self.assertNotIn('the', top_words)
            self.assertNotIn('is', top_words)
            self.assertNotIn('in', top_words)

            # "important" and "word" should appear
            self.assertIn('important', top_words)
            self.assertIn('word', top_words)

    def test_build_style_profile_calculates_avg_sentence_length(self):
        """build_style_profile should calculate average sentence length."""
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.txt"
            # Two sentences: "Short." (1 word) and "This is longer." (3 words)
            test_file.write_text("Short. This is longer.")

            profile = build_style_profile(tmpdir)
            # Average should be (1 + 3) / 2 = 2.0
            self.assertEqual(profile['avg_sentence_length'], 2.0)


class TestExtractStyleKeywords(unittest.TestCase):
    """Tests for extract_style_keywords function."""

    def test_extract_style_keywords_from_profile(self):
        """extract_style_keywords should extract keywords from profile."""
        profile = {
            'top_unigrams': ['python', 'programming', 'software', 'development'],
            'top_bigrams': ['machine learning', 'data science'],
        }

        keywords = extract_style_keywords(profile, limit=5)

        self.assertLessEqual(len(keywords), 5)
        self.assertIn('python', keywords)
        self.assertIn('programming', keywords)

    def test_extract_style_keywords_includes_bigrams(self):
        """extract_style_keywords should include bigrams."""
        profile = {
            'top_unigrams': ['word1', 'word2'],
            'top_bigrams': ['bigram one', 'bigram two'],
        }

        keywords = extract_style_keywords(profile, limit=10)

        # Should include both unigrams and bigrams
        self.assertIn('word1', keywords)
        self.assertIn('bigram one', keywords)

    def test_extract_style_keywords_respects_limit(self):
        """extract_style_keywords should respect the limit parameter."""
        profile = {
            'top_unigrams': ['w' + str(i) for i in range(50)],
            'top_bigrams': ['b' + str(i) for i in range(50)],
        }

        keywords = extract_style_keywords(profile, limit=10)
        self.assertEqual(len(keywords), 10)

    def test_extract_style_keywords_empty_profile(self):
        """extract_style_keywords should handle empty profile."""
        profile = {}
        keywords = extract_style_keywords(profile)
        self.assertEqual(keywords, [])


if __name__ == '__main__':
    unittest.main()
