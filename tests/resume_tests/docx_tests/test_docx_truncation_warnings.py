"""Tests for DOCX renderer truncation warnings and empty-section suppression.

Covers:
  Defect 1 — ExperienceSectionRenderer truncation warnings (docx_sections_exp.py):
    1. 6 roles with max_items=5 -> 5 rendered AND a warning naming the dropped role
    2. a role whose bullets exceed prior_max_bullets -> truncated AND a warning
    3. no truncation when everything fits -> NO warning emitted

  Defect 2 — section heading suppression (docx_standard.py):
    4. a template section with an unknown key ("projects") -> no heading rendered
    5. a template section whose data is empty -> no heading rendered
    6. a section with data -> heading IS present (anti-regression guard)

  Bonus (coordinator note) — summary list renders all bullets without silent drop.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import patch

from resume.schema import Resume
from tests.resume_tests.docx_tests.fixtures import make_mock_doc as _make_mock_doc
from tests.resume_tests.fixtures import mock_docx_modules


# ---------------------------------------------------------------------------
# Defect 1: ExperienceSectionRenderer truncation warnings
# ---------------------------------------------------------------------------

@mock_docx_modules
class TestExperienceTruncationWarnings(unittest.TestCase):
    """ExperienceSectionRenderer emits warnings on truncation."""

    def _make_renderer(self):
        from resume.docx_sections_exp import ExperienceSectionRenderer
        return ExperienceSectionRenderer(_make_mock_doc())

    def _make_roles(self, n: int, bullets_per_role: int = 0) -> list[dict]:
        return [
            {
                "title": f"Engineer {i}",
                "company": f"Company {i}",
                "bullets": [f"Bullet {j}" for j in range(bullets_per_role)],
            }
            for i in range(n)
        ]

    # --- Test 1: 6 roles, max_items=5 -> warning naming the dropped role ---

    def test_6_roles_max_5_warns_with_dropped_role_name(self):
        renderer = self._make_renderer()
        roles = self._make_roles(6)
        data = {"experience": roles}
        sec = {"max_items": 5}

        buf = io.StringIO()
        with redirect_stderr(buf):
            renderer.render(Resume.from_dict(data), sec)

        stderr = buf.getvalue()
        self.assertIn("resume:", stderr)
        self.assertIn("max_items=5", stderr)
        self.assertIn("1 of 6", stderr)
        # Dropped role is "Company 5" (the 6th, index 5)
        self.assertIn("Company 5", stderr)

    def test_6_roles_max_5_renders_exactly_5_roles(self):
        """Only 5 roles are rendered when max_items=5."""
        from resume.docx_sections_exp import ExperienceSectionRenderer
        doc = _make_mock_doc()
        renderer = ExperienceSectionRenderer(doc)
        roles = self._make_roles(6)
        data = {"experience": roles}
        sec = {"max_items": 5}

        with redirect_stderr(io.StringIO()):
            renderer.render(Resume.from_dict(data), sec)

        # 5 roles -> 5 header paragraphs (add_paragraph called once per role header)
        self.assertEqual(doc.add_paragraph.call_count, 5)

    # --- Test 2: bullets exceed prior_max_bullets -> warning names role and counts ---

    def test_prior_bullet_truncation_warns_role_name_and_counts(self):
        renderer = self._make_renderer()
        # idx=0: recent role (Acme), idx=1: prior role (LinkedIn) with 5 bullets
        # recent_roles_count=1 means roles at idx >= 1 are "prior"
        data = {
            "experience": [
                {"company": "Acme", "bullets": ["b1"]},  # recent
                {"company": "LinkedIn", "bullets": [f"b{i}" for i in range(5)]},  # prior
            ]
        }
        sec = {
            "recent_roles_count": 1,
            "prior_max_bullets": 3,
        }

        buf = io.StringIO()
        with redirect_stderr(buf):
            renderer.render(Resume.from_dict(data), sec)

        stderr = buf.getvalue()
        self.assertIn("resume:", stderr)
        self.assertIn("LinkedIn", stderr)
        self.assertIn("5", stderr)
        self.assertIn("3", stderr)

    # --- Test 3: no truncation -> NO warning emitted ---

    def test_no_warning_when_within_limits(self):
        renderer = self._make_renderer()
        roles = self._make_roles(3, bullets_per_role=2)
        data = {"experience": roles}
        sec = {"max_items": 5, "max_bullets": 5}

        buf = io.StringIO()
        with redirect_stderr(buf):
            renderer.render(Resume.from_dict(data), sec)

        self.assertEqual(buf.getvalue(), "")

    def test_no_warning_at_exact_max_items_boundary(self):
        renderer = self._make_renderer()
        roles = self._make_roles(5)
        data = {"experience": roles}
        sec = {"max_items": 5}

        buf = io.StringIO()
        with redirect_stderr(buf):
            renderer.render(Resume.from_dict(data), sec)

        self.assertEqual(buf.getvalue(), "")


# ---------------------------------------------------------------------------
# Defect 2a: _section_has_data logic
# ---------------------------------------------------------------------------

@mock_docx_modules
class TestSectionHasData(unittest.TestCase):
    """_section_has_data correctly identifies empty vs populated sections."""

    def _fn(self):
        from resume.docx_standard import _section_has_data
        return _section_has_data

    def _resume(self, data):
        from resume.schema import Resume
        return Resume.from_dict(data)

    def test_unknown_key_is_treated_as_having_data(self):
        # "projects" is not a registered key; we conservatively assume it has data
        # to avoid silently hiding real content from an unrecognised renderer.
        fn = self._fn()
        self.assertTrue(fn("projects", self._resume({})))

    def test_known_key_missing_from_data_returns_false(self):
        fn = self._fn()
        self.assertFalse(fn("interests", self._resume({})))

    def test_known_key_with_empty_list_returns_false(self):
        fn = self._fn()
        self.assertFalse(fn("interests", self._resume({"interests": []})))

    def test_known_key_with_data_returns_true(self):
        fn = self._fn()
        self.assertTrue(fn("interests", self._resume({"interests": ["Hiking"]})))

    def test_summary_headline_fallback_prevents_false_empty(self):
        fn = self._fn()
        # SummarySectionRenderer reads resume.summary or resume.headline
        self.assertTrue(fn("summary", self._resume({"headline": "Software Engineer"})))
        self.assertFalse(fn("summary", self._resume({})))

    def test_skills_accepts_skills_groups_or_flat_skills(self):
        fn = self._fn()
        self.assertTrue(fn("skills", self._resume({"skills": ["Python"]})))
        self.assertTrue(fn("skills", self._resume({"skills_groups": [{"title": "Lang", "items": ["Go"]}]})))
        self.assertFalse(fn("skills", self._resume({})))


# ---------------------------------------------------------------------------
# Defect 2b: StandardResumeWriter section-heading suppression
# ---------------------------------------------------------------------------

@mock_docx_modules
class TestStandardResumeWriterSectionSuppression(unittest.TestCase):
    """_render_content skips headings for unknown-key or empty-data sections."""

    def _make_writer(self, data: dict, sections: list[dict]):
        from resume.docx_standard import StandardResumeWriter
        template = {"sections": sections}
        writer = StandardResumeWriter(data, template)
        writer.doc = _make_mock_doc()
        return writer

    def _heading_titles(self, writer) -> list[str]:
        """Extract the text argument from each add_heading call."""
        return [
            args[0]
            for args, _kwargs in writer.doc.add_heading.call_args_list
        ]

    def _render_sections_only(self, writer):
        """Run _render_content with document-header stubbed out."""
        with (
            patch("resume.docx_standard._tight_paragraph"),
            patch("resume.docx_standard._flush_left"),
            patch("resume.docx_standard._parse_hex_color", return_value=None),
        ):
            writer._render_document_header = lambda: None
            writer._resolve_sections = lambda: writer.template["sections"]
            writer._render_content()

    # --- Test 4: unknown key "projects" -> no heading rendered ---

    def test_unknown_key_produces_no_heading(self):
        writer = self._make_writer(
            data={"projects": [{"name": "Foo"}]},
            sections=[{"key": "projects", "title": "Notable Projects"}],
        )
        self._render_sections_only(writer)
        self.assertNotIn("Notable Projects", self._heading_titles(writer))

    # --- Test 5: known section with empty data -> no heading rendered ---

    def test_empty_data_produces_no_heading(self):
        writer = self._make_writer(
            data={},  # "interests" key is absent
            sections=[{"key": "interests", "title": "Interests"}],
        )
        self._render_sections_only(writer)
        self.assertNotIn("Interests", self._heading_titles(writer))

    def test_empty_list_data_produces_no_heading(self):
        writer = self._make_writer(
            data={"interests": []},
            sections=[{"key": "interests", "title": "Interests"}],
        )
        self._render_sections_only(writer)
        self.assertNotIn("Interests", self._heading_titles(writer))

    # --- Test 6: section with data -> heading IS present (anti-regression) ---

    def test_populated_section_produces_heading(self):
        writer = self._make_writer(
            data={"interests": ["Hiking", "Photography"]},
            sections=[{"key": "interests", "title": "Interests"}],
        )
        with patch("resume.docx_standard.InterestsSectionRenderer") as mock_cls:
            mock_cls.return_value.render.return_value = ["Hiking", "Photography"]
            self._render_sections_only(writer)
        self.assertIn("Interests", self._heading_titles(writer))


# ---------------------------------------------------------------------------
# Bonus: summary list renders all items without silent drop
# ---------------------------------------------------------------------------

@mock_docx_modules
class TestSummaryListRendersAllBullets(unittest.TestCase):
    """SummarySectionRenderer renders every item in a list summary without truncation."""

    def _make_renderer(self):
        from resume.docx_sections_skills import SummarySectionRenderer
        doc = _make_mock_doc()
        return SummarySectionRenderer(doc), doc

    def test_all_list_items_rendered(self):
        renderer, doc = self._make_renderer()
        items = ["Point A", "Point B", "Point C", "Point D"]
        data = {"summary": items}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(doc.add_paragraph.call_count, len(items))

    def test_five_list_items_produces_five_paragraphs(self):
        renderer, doc = self._make_renderer()
        items = [f"Claim {i}" for i in range(5)]
        data = {"summary": items}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(doc.add_paragraph.call_count, 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
