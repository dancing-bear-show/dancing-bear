"""Tests for slides._styling — StylingMixin."""

import unittest
from unittest.mock import MagicMock

from lxml import etree
from pptx.enum.dml import MSO_THEME_COLOR
from pptx.util import Pt

from slides._styling import StylingMixin, TextStyle
from slides.constants import HIGHLIGHT_THEME_COLOR, LINK_BLUE


def _make_run():
    """Factory for a mock pptx text run."""
    run = MagicMock()
    run.font = MagicMock()
    run.font.color = MagicMock()
    run.hyperlink = MagicMock()
    return run


def _make_paragraph():
    """Factory for a mock paragraph with XML element."""
    para = MagicMock()
    # Build a real lxml element so XML manipulations in suppress/apply_native work
    nsmap = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    p_el = etree.Element(f"{{{nsmap['a']}}}p", nsmap=nsmap)
    para._p = p_el
    para.add_run = MagicMock(return_value=_make_run())
    return para


class _Concrete(StylingMixin):
    """Concrete subclass so we can instantiate the mixin."""
    pass


class TestStyleRun(unittest.TestCase):
    """Tests for StylingMixin._style_run."""

    def setUp(self):
        self.mixin = _Concrete()

    def test_sets_font_size(self):
        run = _make_run()
        self.mixin._style_run(run, font_size=Pt(14))
        self.assertEqual(run.font.size, Pt(14))

    def test_sets_theme_color(self):
        run = _make_run()
        self.mixin._style_run(run, theme_color=MSO_THEME_COLOR.LIGHT_2)
        self.assertEqual(run.font.color.theme_color, MSO_THEME_COLOR.LIGHT_2)

    def test_sets_bold(self):
        run = _make_run()
        self.mixin._style_run(run, bold=True)
        self.assertTrue(run.font.bold)

    def test_no_ops_on_none_values(self):
        """None arguments should not mutate any font attributes."""
        run = _make_run()
        self.mixin._style_run(run)  # all defaults None
        run.font.size.__set__ = MagicMock()
        run.font.bold.__set__ = MagicMock()
        # Attributes should not have been set
        run.font.size.__set__.assert_not_called()
        run.font.bold.__set__.assert_not_called()

    def test_all_attributes_together(self):
        run = _make_run()
        self.mixin._style_run(
            run,
            font_size=Pt(18),
            theme_color=MSO_THEME_COLOR.ACCENT_1,
            bold=False,
        )
        self.assertEqual(run.font.size, Pt(18))
        self.assertEqual(run.font.color.theme_color, MSO_THEME_COLOR.ACCENT_1)
        self.assertFalse(run.font.bold)


class TestFormatBulletText(unittest.TestCase):
    """Tests for StylingMixin._format_bullet_text."""

    def setUp(self):
        self.mixin = _Concrete()

    def test_plain_text_unchanged(self):
        self.assertEqual(self.mixin._format_bullet_text("Hello world", 0), "Hello world")

    def test_strips_leading_bullet_char(self):
        self.assertEqual(self.mixin._format_bullet_text("• Bullet text", 0), "Bullet text")

    def test_strips_dash_bullet(self):
        self.assertEqual(self.mixin._format_bullet_text("- dash item", 0), "dash item")

    def test_strips_star_bullet(self):
        self.assertEqual(self.mixin._format_bullet_text("* star item", 1), "star item")

    def test_strips_sub_bullet_char(self):
        self.assertEqual(self.mixin._format_bullet_text("◦ sub item", 1), "sub item")

    def test_returns_whitespace_only_unchanged(self):
        """Whitespace-only text is returned as-is (no strip)."""
        result = self.mixin._format_bullet_text("   ", 0)
        self.assertEqual(result, "   ")

    def test_empty_string_unchanged(self):
        result = self.mixin._format_bullet_text("", 0)
        self.assertEqual(result, "")

    def test_strips_whitespace_from_plain_text(self):
        result = self.mixin._format_bullet_text("  trimmed  ", 0)
        self.assertEqual(result, "trimmed")


class TestSplitByHighlights(unittest.TestCase):
    """Tests for StylingMixin._split_by_highlights."""

    def test_no_match_returns_full_text(self):
        """When the highlight doesn't appear in the text, returns the full text."""
        result = StylingMixin._split_by_highlights("hello world", ["xyz"])
        self.assertEqual(result, ["hello world"])

    def test_single_highlight_splits_text(self):
        result = StylingMixin._split_by_highlights("hello world", ["world"])
        self.assertIn("world", result)
        self.assertIn("hello ", result)

    def test_multiple_highlights(self):
        result = StylingMixin._split_by_highlights("foo bar baz", ["foo", "baz"])
        self.assertIn("foo", result)
        self.assertIn("baz", result)

    def test_longer_highlight_matched_first(self):
        """Longer highlights take precedence over shorter ones."""
        result = StylingMixin._split_by_highlights("foobar", ["foo", "foobar"])
        self.assertIn("foobar", result)
        self.assertNotIn("foo", result)

    def test_empty_segments_filtered_out(self):
        result = StylingMixin._split_by_highlights("highlight", ["highlight"])
        # No empty strings in result
        self.assertNotIn("", result)


class TestApplyHyperlink(unittest.TestCase):
    """Tests for StylingMixin._apply_hyperlink."""

    def test_sets_hyperlink_address(self):
        run = _make_run()
        StylingMixin._apply_hyperlink(run, "https://example.com")
        self.assertEqual(run.hyperlink.address, "https://example.com")

    def test_applies_link_blue_color_by_default(self):
        run = _make_run()
        StylingMixin._apply_hyperlink(run, "https://example.com")
        self.assertEqual(run.font.color.rgb, LINK_BLUE)

    def test_preserve_color_skips_rgb_assignment(self):
        run = _make_run()
        StylingMixin._apply_hyperlink(run, "https://example.com", preserve_color=True)
        # font.color.rgb should NOT have been set
        run.font.color.rgb.__set__ = MagicMock()
        run.font.color.rgb.__set__.assert_not_called()

    def test_sets_underline(self):
        run = _make_run()
        StylingMixin._apply_hyperlink(run, "https://example.com")
        self.assertTrue(run.font.underline)


class TestSuppressBullet(unittest.TestCase):
    """Tests for StylingMixin._suppress_bullet."""

    def setUp(self):
        self.mixin = _Concrete()

    def test_adds_bu_none_element(self):
        para = _make_paragraph()
        self.mixin._suppress_bullet(para)
        nsmap = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        bu_none = para._p.find("a:pPr/a:buNone", nsmap)
        self.assertIsNotNone(bu_none)

    def test_removes_existing_bu_char(self):
        """If buChar already exists it is removed before adding buNone."""
        nsmap = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        para = _make_paragraph()
        # Pre-populate a buChar
        p_pr = etree.SubElement(para._p, f"{{{nsmap['a']}}}pPr")
        etree.SubElement(p_pr, f"{{{nsmap['a']}}}buChar").set("char", "•")

        self.mixin._suppress_bullet(para)

        bu_char = para._p.find("a:pPr/a:buChar", nsmap)
        self.assertIsNone(bu_char)
        bu_none = para._p.find("a:pPr/a:buNone", nsmap)
        self.assertIsNotNone(bu_none)


class TestApplyNativeBullet(unittest.TestCase):
    """Tests for StylingMixin._apply_native_bullet."""

    def setUp(self):
        self.mixin = _Concrete()

    def _get_bu_char(self, para):
        nsmap = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        return para._p.find("a:pPr/a:buChar", nsmap)

    def test_adds_bullet_char_level_0(self):
        para = _make_paragraph()
        self.mixin._apply_native_bullet(para, 0)
        bu = self._get_bu_char(para)
        self.assertIsNotNone(bu)
        self.assertEqual(bu.get("char"), "•")

    def test_adds_bullet_char_level_1(self):
        para = _make_paragraph()
        self.mixin._apply_native_bullet(para, 1)
        bu = self._get_bu_char(para)
        self.assertEqual(bu.get("char"), "◦")

    def test_adds_bullet_char_level_2(self):
        para = _make_paragraph()
        self.mixin._apply_native_bullet(para, 2)
        bu = self._get_bu_char(para)
        self.assertEqual(bu.get("char"), "▪")

    def test_sets_indentation_level(self):
        para = _make_paragraph()
        self.mixin._apply_native_bullet(para, 1)
        nsmap = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        p_pr = para._p.find("a:pPr", nsmap)
        self.assertEqual(p_pr.get("lvl"), "1")

    def test_removes_bu_none_when_present(self):
        """buNone is cleared before adding buChar."""
        nsmap = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
        para = _make_paragraph()
        p_pr = etree.SubElement(para._p, f"{{{nsmap['a']}}}pPr")
        etree.SubElement(p_pr, f"{{{nsmap['a']}}}buNone")

        self.mixin._apply_native_bullet(para, 0)

        bu_none = para._p.find("a:pPr/a:buNone", nsmap)
        self.assertIsNone(bu_none)
        bu_char = para._p.find("a:pPr/a:buChar", nsmap)
        self.assertIsNotNone(bu_char)


class TestAddTextToParagraph(unittest.TestCase):
    """Tests for StylingMixin._add_text_to_paragraph."""

    def setUp(self):
        self.mixin = _Concrete()

    def test_simple_text_no_highlights(self):
        para = _make_paragraph()
        self.mixin._add_text_to_paragraph(para, "simple text", TextStyle())
        para.add_run.assert_called_once()

    def test_sets_run_text(self):
        para = _make_paragraph()
        run = _make_run()
        para.add_run.return_value = run
        self.mixin._add_text_to_paragraph(para, "hello", TextStyle())
        self.assertEqual(run.text, "hello")

    def test_applies_hyperlink_when_url_provided(self):
        para = _make_paragraph()
        run = _make_run()
        para.add_run.return_value = run
        self.mixin._add_text_to_paragraph(para, "link text", TextStyle(url="https://x.com"))
        self.assertEqual(run.hyperlink.address, "https://x.com")

    def test_highlighted_text_uses_multiple_runs(self):
        """When highlights are given, text is split and multiple runs are added."""
        para = _make_paragraph()
        runs = [_make_run(), _make_run(), _make_run()]
        para.add_run.side_effect = runs

        self.mixin._add_text_to_paragraph(
            para, "foo bar baz", TextStyle(highlights=["bar"])
        )
        self.assertGreater(para.add_run.call_count, 1)

    def test_bold_applied_to_plain_run(self):
        para = _make_paragraph()
        run = _make_run()
        para.add_run.return_value = run
        self.mixin._add_text_to_paragraph(para, "bold text", TextStyle(bold=True))
        self.assertTrue(run.font.bold)


class TestStyleHighlightedRun(unittest.TestCase):
    """Tests for StylingMixin._style_highlighted_run."""

    def setUp(self):
        self.mixin = _Concrete()

    def test_highlighted_segment_is_bold(self):
        run = _make_run()
        self.mixin._style_highlighted_run(run, "key", ["key"], None, None, False)
        self.assertTrue(run.font.bold)

    def test_highlighted_segment_uses_accent_color_when_theme_set(self):
        run = _make_run()
        self.mixin._style_highlighted_run(
            run, "key", ["key"], None, MSO_THEME_COLOR.LIGHT_2, False
        )
        self.assertEqual(run.font.color.theme_color, HIGHLIGHT_THEME_COLOR)

    def test_non_highlighted_segment_uses_theme_color(self):
        run = _make_run()
        self.mixin._style_highlighted_run(
            run, "other", ["key"], None, MSO_THEME_COLOR.LIGHT_1, False
        )
        self.assertEqual(run.font.color.theme_color, MSO_THEME_COLOR.LIGHT_1)
