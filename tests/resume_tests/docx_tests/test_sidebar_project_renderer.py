"""Tests for the sidebar _render_proj_entry parity fixes.

Covers the gap items called out by the pre-PR review:
- Link field is rendered as a hyperlink (not ignored)
- Bullet text is normalised before display
- Keyword bolding is applied when keywords are provided
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


def _make_cell():
    """Return (cell_mock, paragraphs_list) with a tracking add_paragraph."""
    cell = MagicMock()
    paragraphs = []

    def _add_paragraph():
        p = MagicMock()
        runs = []

        def _add_run(text=""):
            r = MagicMock()
            r.text = text
            r.font = MagicMock()
            r.bold = False
            r.italic = False
            runs.append(r)
            return r

        p.add_run = _add_run
        p.paragraph_format = MagicMock()
        p.runs = runs
        paragraphs.append(p)
        return p

    cell.add_paragraph = _add_paragraph
    cell.paragraphs = paragraphs
    return cell, paragraphs


class TestRenderProjEntryLink(unittest.TestCase):
    """_render_proj_entry renders the ``link`` field as a hyperlink."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_proj_entry
        self._fn = _render_proj_entry

    def test_link_calls_add_hyperlink(self):
        """When ``link`` is set, ``add_hyperlink`` is called with the resolved URL."""
        from resume.schema import Project

        cell, _ = _make_cell()
        proj = Project.from_dict({"name": "My Project", "link": "https://github.com/user/repo"})

        with patch("resume.docx_sidebar_sections.add_hyperlink") as mock_hl, \
             patch("resume.docx_sidebar_sections.normalize_link_url", return_value="https://github.com/user/repo"), \
             patch("resume.docx_sidebar_sections.display_url", return_value="github.com/user/repo"):
            self._fn(cell, proj, {"body_pt": 10}, "#4A90A4")

        mock_hl.assert_called_once()
        call_args = mock_hl.call_args
        # Second positional arg is the URL
        self.assertIn("github.com/user/repo", call_args[0][1])

    def test_no_link_does_not_call_add_hyperlink(self):
        """When ``link`` is absent, ``add_hyperlink`` is never called."""
        from resume.schema import Project

        cell, _ = _make_cell()
        proj = Project.from_dict({"name": "No Link Project"})

        with patch("resume.docx_sidebar_sections.add_hyperlink") as mock_hl:
            self._fn(cell, proj, {"body_pt": 10}, "#4A90A4")

        mock_hl.assert_not_called()

    def test_empty_link_does_not_call_add_hyperlink(self):
        """An empty link string is treated as absent."""
        from resume.schema import Project

        cell, _ = _make_cell()
        proj = Project.from_dict({"name": "Empty Link", "link": ""})

        with patch("resume.docx_sidebar_sections.add_hyperlink") as mock_hl:
            self._fn(cell, proj, {"body_pt": 10}, "#4A90A4")

        mock_hl.assert_not_called()


class TestRenderProjEntryKeywordBolding(unittest.TestCase):
    """_render_proj_entry applies keyword bolding when keywords are provided."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_proj_entry
        self._fn = _render_proj_entry

    def test_keyword_bolding_called_with_keywords(self):
        """``bold_text_in_paragraph`` is invoked for each bullet when keywords given."""
        from resume.schema import Project

        cell, _ = _make_cell()
        proj = Project.from_dict({
            "name": "Project",
            "bullets": [{"text": "Built with Python"}],
        })
        keywords = ["Python"]

        with patch("resume.docx_sidebar_sections.bold_text_in_paragraph") as mock_bold:
            self._fn(cell, proj, {"body_pt": 10}, "#4A90A4", keywords=keywords)

        mock_bold.assert_called_once()
        _, call_text, call_kw = mock_bold.call_args[0]
        self.assertIn("Python", call_text)
        self.assertEqual(call_kw, keywords)

    def test_no_keywords_still_renders_bullet(self):
        """Without keywords, bullets are rendered as plain text (no bold helper)."""
        from resume.schema import Project

        cell, _ = _make_cell()
        proj = Project.from_dict({
            "name": "Project",
            "bullets": [{"text": "Plain bullet"}],
        })

        with patch("resume.docx_sidebar_sections.bold_text_in_paragraph") as mock_bold:
            self._fn(cell, proj, {"body_pt": 10}, "#4A90A4")

        # Still called — bold_text_in_paragraph handles the None keywords case.
        mock_bold.assert_called_once()
        _, _, call_kw = mock_bold.call_args[0]
        self.assertIsNone(call_kw)


class TestRenderProjEntryBulletNormalisation(unittest.TestCase):
    """_render_proj_entry normalises bullet text before display."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_proj_entry
        self._fn = _render_proj_entry

    def test_normalize_bullet_called_for_each_bullet(self):
        """TextFormatter.normalize_bullet is invoked for each non-empty bullet."""
        from resume.schema import Project

        cell, _ = _make_cell()
        proj = Project.from_dict({
            "name": "Project",
            "bullets": [{"text": "Built APIs."}, {"text": "Wrote tests."}],
        })

        with patch("resume.docx_sidebar_sections.TextFormatter.normalize_bullet", side_effect=lambda t, **_: t) as mock_norm, \
             patch("resume.docx_sidebar_sections.bold_text_in_paragraph"):
            self._fn(cell, proj, {"body_pt": 10}, "#4A90A4")

        self.assertEqual(mock_norm.call_count, 2)

    def test_empty_bullet_text_is_skipped(self):
        """Bullets with empty text after normalisation are not rendered."""
        from resume.schema import Project

        cell, paras = _make_cell()
        proj = Project.from_dict({
            "name": "Project",
            "bullets": [{"text": ""}],
        })
        # name para only; no bullet para
        self._fn(cell, proj, {"body_pt": 10}, "#4A90A4")
        # Only the name paragraph should be present
        self.assertEqual(len(paras), 1)


if __name__ == "__main__":
    unittest.main()
