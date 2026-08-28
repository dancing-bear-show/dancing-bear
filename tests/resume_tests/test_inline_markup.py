"""Tests for the inline emphasis markup parser.

These cover the parser in isolation. The renderer-level tests that prove the
markup reaches each candidate prose field live in
``tests/resume_tests/docx_tests/test_docx_inline_markup.py``.
"""
from __future__ import annotations

import unittest

from resume.inline_markup import (
    MarkupSpan,
    has_inline_markup,
    parse_inline_markup,
    strip_inline_markup,
)


def flatten(text: str) -> list[tuple[str, bool, bool]]:
    """Return parsed spans as ``(text, bold, italic)`` triples."""
    return [(s.text, s.bold, s.italic) for s in parse_inline_markup(text)]


class TestBoldAndItalic(unittest.TestCase):
    """Emphasis delimiters produce runs carrying the right flags."""

    def test_bold_delimiters_produce_a_bold_span(self):
        self.assertEqual(flatten("**bold**"), [("bold", True, False)])

    def test_italic_delimiters_produce_an_italic_span(self):
        self.assertEqual(flatten("*italic*"), [("italic", False, True)])

    def test_surrounding_text_stays_plain(self):
        self.assertEqual(
            flatten("Led **the team** to ship"),
            [("Led ", False, False), ("the team", True, False), (" to ship", False, False)],
        )

    def test_bold_and_italic_in_one_string(self):
        self.assertEqual(
            flatten("**scaled** the *platform*"),
            [
                ("scaled", True, False),
                (" the ", False, False),
                ("platform", False, True),
            ],
        )

    def test_adjacent_emphasis_spans_stay_separate(self):
        """Two spans that touch must not merge into one run."""
        self.assertEqual(
            flatten("**bold***italic*"),
            [("bold", True, False), ("italic", False, True)],
        )

    def test_emphasis_at_start_and_end_of_string(self):
        self.assertEqual(
            flatten("**first** middle **last**"),
            [
                ("first", True, False),
                (" middle ", False, False),
                ("last", True, False),
            ],
        )

    def test_emphasis_spanning_the_whole_string(self):
        self.assertEqual(flatten("*everything*"), [("everything", False, True)])

    def test_plain_text_produces_exactly_one_span(self):
        """No markup means no gratuitous splitting into multiple runs."""
        spans = parse_inline_markup("Reduced incident volume by forty percent")
        self.assertEqual(len(spans), 1)
        self.assertEqual(
            spans[0], MarkupSpan("Reduced incident volume by forty percent", False, False)
        )

    def test_empty_string_produces_no_spans(self):
        self.assertEqual(parse_inline_markup(""), [])


class TestLiteralAsterisksSurvive(unittest.TestCase):
    """Unmatched or intra-word asterisks must render literally, never swallow text.

    This is the backward-compatibility guarantee: existing candidate data was
    authored with no markup convention, so any asterisk already in it must
    come out unchanged.
    """

    def assert_literal(self, text: str) -> None:
        """Assert text passes through as a single unmodified plain span."""
        self.assertEqual(flatten(text), [(text, False, False)])

    def test_spaced_asterisk_is_literal(self):
        self.assert_literal("a * b")

    def test_multiplication_is_literal(self):
        self.assert_literal("5 * 3 = 15")

    def test_glob_in_filename_is_literal(self):
        self.assert_literal("file*.txt")

    def test_intra_word_asterisk_is_literal(self):
        self.assert_literal("a*b")

    def test_unclosed_bold_is_literal(self):
        self.assert_literal("**unclosed")

    def test_unclosed_italic_is_literal(self):
        self.assert_literal("*unclosed")

    def test_lone_asterisk_is_literal(self):
        self.assert_literal("*")

    def test_bare_double_asterisk_is_literal(self):
        self.assert_literal("**")

    def test_leading_asterisk_with_space_is_literal(self):
        self.assert_literal("* leading")

    def test_trailing_asterisk_is_literal(self):
        self.assert_literal("trailing *")

    def test_exponent_notation_is_literal(self):
        self.assert_literal("2**8 = 256")

    def test_footnote_marker_is_literal(self):
        self.assert_literal("Certified*")

    def test_empty_emphasis_produces_no_run(self):
        """```****``` must not yield an empty run, nor invent an italic span."""
        self.assert_literal("****")

    def test_unmatched_delimiter_never_drops_characters(self):
        """Whatever happens, no input character may disappear."""
        for text in ("a * b", "5 * 3", "file*.txt", "**unclosed", "****", "2**8"):
            with self.subTest(text=text):
                self.assertEqual(strip_inline_markup(text), text)


class TestUnderscoresAreNotMarkup(unittest.TestCase):
    """``_`` is deliberately not a delimiter: identifiers must survive."""

    def test_single_underscores_are_literal(self):
        self.assertEqual(flatten("_x_"), [("_x_", False, False)])

    def test_double_underscores_are_literal(self):
        self.assertEqual(flatten("__init__"), [("__init__", False, False)])

    def test_snake_case_identifier_is_literal(self):
        self.assertEqual(
            flatten("some_function_name"), [("some_function_name", False, False)]
        )

    def test_underscored_filename_is_literal(self):
        self.assertEqual(
            flatten("docx_renderers.py"), [("docx_renderers.py", False, False)]
        )


class TestNestingDegradesPredictably(unittest.TestCase):
    """Nesting is unsupported; the inner delimiters stay literal, not dropped."""

    def test_italic_inside_bold_keeps_inner_delimiters_literal(self):
        self.assertEqual(flatten("**a *b* c**"), [("a *b* c", True, False)])

    def test_bold_inside_italic_keeps_inner_delimiters_literal(self):
        self.assertEqual(flatten("*a**b*"), [("a**b", False, True)])

    def test_nesting_never_loses_the_inner_text(self):
        self.assertEqual(strip_inline_markup("**a *b* c**"), "a *b* c")


class TestHelpers(unittest.TestCase):
    """``has_inline_markup`` and ``strip_inline_markup``."""

    def test_has_inline_markup_true_for_emphasis(self):
        self.assertTrue(has_inline_markup("a **b** c"))
        self.assertTrue(has_inline_markup("a *b* c"))

    def test_has_inline_markup_false_for_literal_asterisks(self):
        self.assertFalse(has_inline_markup("5 * 3 = 15"))
        self.assertFalse(has_inline_markup("plain text"))
        self.assertFalse(has_inline_markup(""))

    def test_strip_inline_markup_removes_matched_delimiters(self):
        self.assertEqual(strip_inline_markup("Led **the team** to *ship*"), "Led the team to ship")

    def test_strip_inline_markup_leaves_plain_text_alone(self):
        self.assertEqual(strip_inline_markup("no markup here"), "no markup here")


if __name__ == "__main__":
    unittest.main()
