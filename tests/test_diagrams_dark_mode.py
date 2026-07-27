"""Tests for diagrams/dark_mode.py."""

from __future__ import annotations

import unittest

from diagrams.dark_mode import (
    RECT_ALPHA,
    apply_dark_mode_fixes,
    _has_init_directive,
    _inject_timeline_palette,
    _is_timeline,
    _rewrite_rect_rgb_to_rgba,
)


class TestRewriteRectRgbToRgba(unittest.TestCase):
    def test_plain_rect_rgb(self):
        source = "sequenceDiagram\n    rect rgb(255, 0, 0)\n    end"
        out = _rewrite_rect_rgb_to_rgba(source)
        self.assertIn(f"rect rgba(255, 0, 0, {RECT_ALPHA})", out)
        self.assertNotIn("rect rgb(", out)

    def test_existing_rgba_untouched(self):
        source = "sequenceDiagram\n    rect rgba(255, 0, 0, 0.5)\n    end"
        out = _rewrite_rect_rgb_to_rgba(source)
        self.assertIn("rect rgba(255, 0, 0, 0.5)", out)

    def test_case_insensitive_match(self):
        source = "rect RGB(10, 20, 30)"
        out = _rewrite_rect_rgb_to_rgba(source)
        self.assertIn(f"rect rgba(10, 20, 30, {RECT_ALPHA})", out)

    def test_no_match_returns_original(self):
        source = "flowchart TB\n    A-->B"
        self.assertEqual(_rewrite_rect_rgb_to_rgba(source), source)

    def test_multiple_rects_all_replaced(self):
        source = "rect rgb(1, 2, 3)\nrect rgb(4, 5, 6)"
        out = _rewrite_rect_rgb_to_rgba(source)
        self.assertNotIn("rect rgb(", out)
        self.assertEqual(out.count("rect rgba"), 2)

    def test_idempotent(self):
        source = "rect rgb(100, 200, 50)"
        out1 = _rewrite_rect_rgb_to_rgba(source)
        out2 = _rewrite_rect_rgb_to_rgba(out1)
        self.assertEqual(out1, out2)


class TestIsTimeline(unittest.TestCase):
    def test_timeline_diagram(self):
        source = "timeline\n    section A\n        event: 2024"
        self.assertTrue(_is_timeline(source))

    def test_flowchart_not_timeline(self):
        source = "flowchart TB\n    A-->B"
        self.assertFalse(_is_timeline(source))

    def test_sequence_not_timeline(self):
        source = "sequenceDiagram\n    A->>B: hi"
        self.assertFalse(_is_timeline(source))

    def test_blank_lines_skipped(self):
        source = "\n\ntimeline\n    section A"
        self.assertTrue(_is_timeline(source))

    def test_comment_lines_skipped(self):
        source = "%% This is a comment\ntimeline\n    section A"
        self.assertTrue(_is_timeline(source))

    def test_frontmatter_skipped(self):
        source = "---\ntitle: My Chart\n---\ntimeline\n    section A"
        self.assertTrue(_is_timeline(source))

    def test_bom_prefix_stripped(self):
        source = "﻿timeline\n    section A"
        self.assertTrue(_is_timeline(source))

    def test_empty_string(self):
        self.assertFalse(_is_timeline(""))


class TestHasInitDirective(unittest.TestCase):
    def test_with_init_directive(self):
        source = '%%{init: {"theme": "dark"}}%%\ntimeline'
        self.assertTrue(_has_init_directive(source))

    def test_without_init_directive(self):
        source = "timeline\n    section A"
        self.assertFalse(_has_init_directive(source))

    def test_partial_match_not_enough(self):
        source = "%% Just a comment %%"
        self.assertFalse(_has_init_directive(source))


class TestInjectTimelinePalette(unittest.TestCase):
    def test_timeline_gets_directive(self):
        source = "timeline\n    section A"
        out = _inject_timeline_palette(source)
        self.assertIn("%%{init:", out)
        self.assertIn("cScale0", out)
        self.assertIn("cScale1", out)
        self.assertIn("cScale2", out)

    def test_non_timeline_unchanged(self):
        source = "flowchart TB\n    A-->B"
        self.assertEqual(_inject_timeline_palette(source), source)

    def test_existing_init_not_overwritten(self):
        source = '%%{init: {"theme": "default"}}%%\ntimeline'
        out = _inject_timeline_palette(source)
        self.assertIn('{"theme": "default"}', out)
        # Should not add a second init block
        self.assertEqual(out.count("%%{init:"), 1)

    def test_directive_prepended_before_content(self):
        source = "timeline\n    section A"
        out = _inject_timeline_palette(source)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("%%{init:"))
        self.assertIn("timeline", lines[1])

    def test_idempotent(self):
        source = "timeline\n    section A"
        out1 = _inject_timeline_palette(source)
        out2 = _inject_timeline_palette(out1)
        self.assertEqual(out1, out2)


class TestApplyDarkModeFixes(unittest.TestCase):
    def test_rect_rgb_rewritten(self):
        source = "sequenceDiagram\n    rect rgb(0, 128, 255)\n    end"
        out = apply_dark_mode_fixes(source)
        self.assertNotIn("rect rgb(", out)
        self.assertIn("rect rgba(", out)

    def test_timeline_palette_injected(self):
        source = "timeline\n    section A"
        out = apply_dark_mode_fixes(source)
        self.assertIn("cScale0", out)

    def test_flowchart_unchanged(self):
        source = "flowchart TB\n    A-->B"
        out = apply_dark_mode_fixes(source)
        self.assertEqual(out, source)

    def test_idempotent_on_sequence(self):
        source = "sequenceDiagram\n    rect rgb(10, 20, 30)\n    end"
        out1 = apply_dark_mode_fixes(source)
        out2 = apply_dark_mode_fixes(out1)
        self.assertEqual(out1, out2)

    def test_idempotent_on_timeline(self):
        source = "timeline\n    section A"
        out1 = apply_dark_mode_fixes(source)
        out2 = apply_dark_mode_fixes(out1)
        self.assertEqual(out1, out2)

    def test_both_fixes_applied_independently(self):
        # rect_rgb only in sequence diagrams, timeline palette only in timeline
        seq_source = "sequenceDiagram\n    rect rgb(5, 10, 15)"
        timeline_source = "timeline\n    section A"

        seq_out = apply_dark_mode_fixes(seq_source)
        self.assertIn("rgba", seq_out)
        self.assertNotIn("cScale", seq_out)

        tl_out = apply_dark_mode_fixes(timeline_source)
        self.assertNotIn("rgba", tl_out)
        self.assertIn("cScale", tl_out)


if __name__ == "__main__":
    unittest.main()
