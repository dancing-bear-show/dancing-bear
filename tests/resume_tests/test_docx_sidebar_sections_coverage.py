"""Coverage tests for resume/docx_sidebar_sections.py.

Targets the 129 uncovered lines+branches in the module, with emphasis on
sad paths (empty/None inputs, missing optional fields, invalid colours).

Functions tested (module-level):
  _add_colored_bullet_run
  _render_exp_entry
  _render_pres_entry

Methods tested (SidebarResumeWriter):
  _normalize_summary_items  (staticmethod)
  _render_centered_header_line
  _render_page_header
  _render_sidebar_summary
  _render_sidebar_skills
  _render_sidebar_content
  _render_main_content
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tests.resume_tests.fixtures import (
    make_experience_entry,
    make_education_entry,
    make_skills_group,
    make_candidate,
)
from resume.schema import ExperienceEntry, Presentation, PriorityItem, Resume


# ---------------------------------------------------------------------------
# Shared cell factory — reused across all test classes.
# ---------------------------------------------------------------------------

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


def _make_writer(data=None, template=None):
    """Return a SidebarResumeWriter with a MagicMock doc (no I/O)."""
    from resume.docx_sidebar_sections import SidebarResumeWriter
    if data is None:
        data = {"name": "Jane Doe", "email": "jane@example.com"}
    if template is None:
        template = {"page": {}, "layout": {}, "sections": []}
    writer = SidebarResumeWriter(data, template)
    writer.doc = MagicMock()
    return writer


# ===========================================================================
# _add_colored_bullet_run
# ===========================================================================

class TestAddColoredBulletRun(unittest.TestCase):
    """Tests for module-level _add_colored_bullet_run."""

    def setUp(self):
        from resume.docx_sidebar_sections import _add_colored_bullet_run
        self._fn = _add_colored_bullet_run

    def _make_p(self):
        p = MagicMock()
        run = MagicMock()
        run.font = MagicMock()
        p.add_run.return_value = run
        return p, run

    def test_adds_bullet_glyph_run(self):
        p, _run = self._make_p()
        self._fn(p, "#4A90A4")
        p.add_run.assert_called_once_with("• ")

    def test_valid_hex_sets_font_color(self):
        """When _parse_hex_color returns a tuple, font.color.rgb is assigned."""
        p, run = self._make_p()
        with patch("resume.docx_sidebar_sections._parse_hex_color", return_value=(74, 144, 164)):
            self._fn(p, "#4A90A4")
        self.assertIsNotNone(run.font.color.rgb)

    def test_invalid_hex_does_not_set_font_color(self):
        """When _parse_hex_color returns falsy, font.color.rgb is NOT touched."""
        p, run = self._make_p()
        original_rgb = run.font.color.rgb
        with patch("resume.docx_sidebar_sections._parse_hex_color", return_value=None):
            self._fn(p, "INVALID")
        self.assertEqual(run.font.color.rgb, original_rgb)

    def test_empty_string_color_does_not_set_font_color(self):
        """An empty colour string is also falsy — rgb should not be set."""
        p, run = self._make_p()
        original_rgb = run.font.color.rgb
        with patch("resume.docx_sidebar_sections._parse_hex_color", return_value=None):
            self._fn(p, "")
        self.assertEqual(run.font.color.rgb, original_rgb)


# ===========================================================================
# _render_exp_entry
# ===========================================================================

class TestRenderExpEntry(unittest.TestCase):
    """Tests for module-level _render_exp_entry."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_exp_entry
        self._fn = _render_exp_entry

    def test_full_entry_produces_title_company_and_bullets(self):
        """title + company + 2 bullets = 4 paragraphs."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict(make_experience_entry(bullets=["Built APIs", "Led team"]))
        self._fn(cell, exp, {"body_pt": 10, "meta_pt": 9}, "#4A90A4", 5)
        self.assertEqual(len(paras), 4)

    def test_entry_without_end_uses_presente_suffix(self):
        """When end is absent, span includes 'presente'."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict({"title": "Dev", "start": "2021", "bullets": []})
        self._fn(cell, exp, {"body_pt": 10}, "#4A90A4", 3)
        self.assertEqual(len(paras), 1)
        title_para = paras[0]
        span_texts = [r.text for r in title_para.runs if "presente" in (r.text or "")]
        self.assertTrue(span_texts, "Expected 'presente' in span run text")

    def test_entry_with_end_uses_dash_separator(self):
        """When end is present, span uses ' – ' separator."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict({"title": "Dev", "start": "2020", "end": "2023", "bullets": []})
        self._fn(cell, exp, {"body_pt": 10}, "#4A90A4", 3)
        title_para = paras[0]
        span_texts = [r.text for r in title_para.runs if "–" in (r.text or "")]
        self.assertTrue(span_texts, "Expected dash in span run text")

    def test_no_company_skips_company_paragraph(self):
        """When company is absent, no company paragraph is added."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict({"title": "Dev", "start": "2020", "bullets": ["Bullet"]})
        self._fn(cell, exp, {"body_pt": 10}, "#4A90A4", 5)
        self.assertEqual(len(paras), 2)

    def test_max_bullets_caps_rendered_bullets(self):
        """Bullets are capped at max_bullets."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict(make_experience_entry(bullets=["a", "b", "c", "d", "e"]))
        self._fn(cell, exp, {"body_pt": 10, "meta_pt": 9}, "#4A90A4", 2)
        # title + company + 2 bullets = 4
        self.assertEqual(len(paras), 4)

    def test_bullet_text_key_renders_prose(self):
        """Bullet entries whose text arrived under the 'text' key render their prose."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict(
            {"title": "Dev", "company": "", "start": "2020", "bullets": [{"text": "Did something"}]}
        )
        self._fn(cell, exp, {"body_pt": 10}, "#4A90A4", 5)
        bullet_para = paras[-1]
        bullet_texts = [r.text for r in bullet_para.runs]
        self.assertIn("Did something", bullet_texts)

    def test_empty_bullets_list_produces_only_title_and_company(self):
        """When bullets is [], only title and company paragraphs are produced."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict(make_experience_entry(bullets=[]))
        self._fn(cell, exp, {"body_pt": 10, "meta_pt": 9}, "#4A90A4", 5)
        self.assertEqual(len(paras), 2)

    def test_missing_bullets_key_produces_only_title_and_company(self):
        """When bullets key is absent, schema defaults to [] and only title+company render."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict({"title": "Dev", "company": "Corp", "start": "2020"})
        self._fn(cell, exp, {"body_pt": 10, "meta_pt": 9}, "#4A90A4", 5)
        self.assertEqual(len(paras), 2)

    def test_missing_title_renders_empty_title(self):
        """Missing title key falls back to empty string without crashing."""
        cell, paras = _make_cell()
        exp = ExperienceEntry.from_dict({"company": "Corp", "start": "2020", "bullets": []})
        self._fn(cell, exp, {"body_pt": 10, "meta_pt": 9}, "#4A90A4", 5)
        self.assertEqual(len(paras), 2)


# ===========================================================================
# _render_pres_entry
# ===========================================================================

class TestRenderPresEntry(unittest.TestCase):
    """Tests for module-level _render_pres_entry."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_pres_entry
        self._fn = _render_pres_entry

    def test_full_entry_produces_four_paragraphs(self):
        """title + authors + event + note = 4 paragraphs."""
        cell, paras = _make_cell()
        pres = Presentation.from_dict({"title": "My Talk", "authors": "A. Author", "event": "PyCon", "note": "Best Paper"})
        self._fn(cell, pres, {"body_pt": 10, "meta_pt": 9}, "#4A90A4")
        self.assertEqual(len(paras), 4)

    def test_no_note_with_event_has_three_paragraphs(self):
        """When note is absent but event is present, 3 paragraphs are produced."""
        cell, paras = _make_cell()
        pres = Presentation.from_dict({"title": "My Talk", "authors": "A. Author", "event": "PyCon", "note": ""})
        self._fn(cell, pres, {"body_pt": 10}, "#4A90A4")
        self.assertEqual(len(paras), 3)

    def test_no_note_no_event_has_two_paragraphs(self):
        """When note and event are absent, 2 paragraphs are produced."""
        cell, paras = _make_cell()
        pres = Presentation.from_dict({"title": "My Talk", "authors": "A. Author", "event": "", "note": ""})
        self._fn(cell, pres, {"body_pt": 10}, "#4A90A4")
        self.assertEqual(len(paras), 2)

    def test_minimal_entry_title_only(self):
        """When only title is supplied, only one paragraph is produced."""
        cell, paras = _make_cell()
        pres = Presentation.from_dict({"title": "Just a Title"})
        self._fn(cell, pres, {"body_pt": 10}, "#4A90A4")
        self.assertEqual(len(paras), 1)

    def test_missing_title_falls_back_to_empty_string(self):
        """Missing title key does not crash; authors still renders."""
        cell, paras = _make_cell()
        pres = Presentation.from_dict({"authors": "A. Author"})
        self._fn(cell, pres, {"body_pt": 10}, "#4A90A4")
        # title para (empty title) + authors para = 2
        self.assertEqual(len(paras), 2)

    def test_title_run_is_bold(self):
        """Title run is marked bold."""
        cell, paras = _make_cell()
        pres = Presentation.from_dict({"title": "Bold Talk"})
        self._fn(cell, pres, {"body_pt": 10}, "#4A90A4")
        title_para = paras[0]
        # Second run is the title run (first is bullet)
        title_run = title_para.runs[1]
        self.assertTrue(title_run.bold)


# ===========================================================================
# SidebarResumeWriter._normalize_summary_items
# ===========================================================================

class TestNormalizeSummaryItems(unittest.TestCase):
    """Tests for the _normalize_summary_items staticmethod."""

    def setUp(self):
        from resume.docx_sidebar_sections import SidebarResumeWriter
        self._fn = SidebarResumeWriter._normalize_summary_items

    def test_empty_list_returns_empty_list(self):
        """An empty list of PriorityItem returns []."""
        self.assertEqual(self._fn([]), [])

    def test_text_keyed_items_return_prose(self):
        """Items whose text arrived under the canonical 'text' key return their prose."""
        items = [PriorityItem.from_dict({"text": "hello"}), PriorityItem.from_dict({"text": "world"})]
        self.assertEqual(self._fn(items), ["hello", "world"])

    def test_alias_keyed_item_returns_alias_key_name(self):
        """An item whose text arrived under an alias key ('line', 'bullet') renders
        the alias key name, not the prose -- replicating pre-migration _replayed_text
        behaviour where only the literal 'text' key was honoured."""
        item = PriorityItem.from_dict({"line": "my prose"})
        result = self._fn([item])
        # _replayed_text returns the key name ("line"), not the prose value,
        # for alias-keyed entries.  This is deliberate: golden pins this.
        self.assertEqual(result, ["line"])

    def test_multiple_text_keyed_items_all_returned(self):
        """All items in the list are returned, not just the first."""
        items = [PriorityItem.from_dict({"text": str(i)}) for i in range(4)]
        self.assertEqual(self._fn(items), ["0", "1", "2", "3"])


# ===========================================================================
# SidebarResumeWriter._render_centered_header_line
# ===========================================================================

class TestRenderCenteredHeaderLine(unittest.TestCase):
    """Tests for _render_centered_header_line method."""

    def _make_style(self, bg_rgb=None):
        from resume.render_config import CenteredHeaderLineStyle
        return CenteredHeaderLineStyle(
            size_pt=20, color="#1A365D", bold=True, after_pt=0, bg_rgb=bg_rgb
        )

    def test_shading_applied_when_bg_rgb_provided(self):
        writer = _make_writer()
        p = MagicMock()
        p.add_run.return_value = MagicMock()
        style = self._make_style(bg_rgb=(247, 249, 252))

        with patch("resume.docx_sidebar_sections._parse_hex_color", return_value=(26, 54, 93)), \
             patch("resume.docx_sidebar_sections._tight_paragraph"), \
             patch("resume.docx_sidebar_sections._apply_paragraph_shading") as mock_shade, \
             patch.object(writer, "_center_paragraph"):
            writer._render_centered_header_line(p, "Name", style)
            mock_shade.assert_called_once_with(p, (247, 249, 252))

    def test_shading_not_applied_when_bg_rgb_is_none(self):
        writer = _make_writer()
        p = MagicMock()
        p.add_run.return_value = MagicMock()
        style = self._make_style(bg_rgb=None)

        with patch("resume.docx_sidebar_sections._parse_hex_color", return_value=(26, 54, 93)), \
             patch("resume.docx_sidebar_sections._tight_paragraph"), \
             patch("resume.docx_sidebar_sections._apply_paragraph_shading") as mock_shade, \
             patch.object(writer, "_center_paragraph"):
            writer._render_centered_header_line(p, "Name", style)
            mock_shade.assert_not_called()

    def test_invalid_color_skips_rgb_assignment(self):
        """If _parse_hex_color returns None, font.color.rgb is not set."""
        writer = _make_writer()
        p = MagicMock()
        run = MagicMock()
        run.font = MagicMock()
        p.add_run.return_value = run
        style = self._make_style(bg_rgb=None)
        original_rgb = run.font.color.rgb

        with patch("resume.docx_sidebar_sections._parse_hex_color", return_value=None), \
             patch("resume.docx_sidebar_sections._tight_paragraph"), \
             patch.object(writer, "_center_paragraph"):
            writer._render_centered_header_line(p, "Name", style)
        self.assertEqual(run.font.color.rgb, original_rgb)

    def test_run_text_and_bold_are_set(self):
        writer = _make_writer()
        p = MagicMock()
        run = MagicMock()
        run.font = MagicMock()
        p.add_run.return_value = run
        style = self._make_style()

        with patch("resume.docx_sidebar_sections._parse_hex_color", return_value=None), \
             patch("resume.docx_sidebar_sections._tight_paragraph"), \
             patch.object(writer, "_center_paragraph"):
            writer._render_centered_header_line(p, "Hello", style)

        p.add_run.assert_called_once_with("Hello")
        self.assertTrue(run.bold)


# ===========================================================================
# SidebarResumeWriter._render_page_header
# ===========================================================================

class TestRenderPageHeader(unittest.TestCase):
    """Tests for _render_page_header method."""

    def _setup_header(self, writer):
        """Attach a mock header to writer.doc.sections[0]."""
        header = MagicMock()
        para = MagicMock()
        para.add_run.return_value = MagicMock()
        header.paragraphs = [para]
        header.add_paragraph.return_value = MagicMock()
        writer.doc.sections = [MagicMock()]
        writer.doc.sections[0].header = header
        return header

    def test_name_always_rendered(self):
        writer = _make_writer(data={"name": "Jane"})
        self._setup_header(writer)
        with patch.object(writer, "_render_centered_header_line") as mock_chl:
            writer._render_page_header()
        texts = [c[0][1] for c in mock_chl.call_args_list]
        self.assertIn("Jane", texts)

    def test_headline_rendered_when_present(self):
        writer = _make_writer(data={"name": "Jane", "headline": "Engineer"})
        self._setup_header(writer)
        with patch.object(writer, "_render_centered_header_line") as mock_chl:
            writer._render_page_header()
        texts = [c[0][1] for c in mock_chl.call_args_list]
        self.assertIn("Engineer", texts)

    def test_headline_absent_only_two_calls_with_contact(self):
        """No headline + single contact field = 2 header lines (name + contact)."""
        writer = _make_writer(data={"name": "Jane", "email": "j@j.com"})
        self._setup_header(writer)
        with patch.object(writer, "_render_centered_header_line") as mock_chl:
            writer._render_page_header()

        # Assert WHICH lines were rendered, not merely how many — a bare count
        # passes even when the wrong two lines are emitted.
        texts = [c.args[1] for c in mock_chl.call_args_list]
        self.assertEqual(texts, ["Jane", "j@j.com"])

    def test_no_contact_parts_skips_contact_line(self):
        """When phone, email, and location are all empty, contact line is skipped."""
        writer = _make_writer(data={"name": "Jane", "headline": "Engineer"})
        self._setup_header(writer)
        with patch.object(writer, "_render_centered_header_line") as mock_chl:
            writer._render_page_header()

        texts = [c.args[1] for c in mock_chl.call_args_list]
        self.assertEqual(texts, ["Jane", "Engineer"])
        self.assertNotIn("", texts)

    def test_contact_line_joins_non_empty_parts(self):
        """phone, email, location are joined with ' | '."""
        writer = _make_writer(data={"name": "Jane", "phone": "555", "email": "j@j.com", "location": "NY"})
        self._setup_header(writer)
        with patch.object(writer, "_render_centered_header_line") as mock_chl:
            writer._render_page_header()
        texts = [c[0][1] for c in mock_chl.call_args_list]
        contact_text = texts[-1]
        self.assertIn("555", contact_text)
        self.assertIn("j@j.com", contact_text)
        self.assertIn("NY", contact_text)
        self.assertIn("|", contact_text)

    def test_all_three_sections_rendered_when_all_present(self):
        data = {"name": "Jane", "headline": "Eng", "email": "j@j.com", "phone": "555", "location": "NY"}
        writer = _make_writer(data=data)
        self._setup_header(writer)
        with patch.object(writer, "_render_centered_header_line") as mock_chl:
            writer._render_page_header()
        self.assertEqual(mock_chl.call_count, 3)

    def test_header_paragraph_cleared_when_existing(self):
        """Existing header paragraph is cleared (not a new one added for name)."""
        writer = _make_writer(data={"name": "Jane"})
        header = self._setup_header(writer)
        existing_para = header.paragraphs[0]
        with patch.object(writer, "_render_centered_header_line"):
            writer._render_page_header()
        existing_para.clear.assert_called_once()

    def test_header_add_paragraph_called_when_no_existing(self):
        """If header has no paragraphs, a new one is added for name."""
        writer = _make_writer(data={"name": "Jane"})
        header = MagicMock()
        header.paragraphs = []
        new_para = MagicMock()
        new_para.add_run.return_value = MagicMock()
        header.add_paragraph.return_value = new_para
        writer.doc.sections = [MagicMock()]
        writer.doc.sections[0].header = header

        with patch.object(writer, "_render_centered_header_line"):
            writer._render_page_header()

        header.add_paragraph.assert_called()


# ===========================================================================
# SidebarResumeWriter._render_sidebar_summary
# ===========================================================================

class TestRenderSidebarSummary(unittest.TestCase):
    """Tests for _render_sidebar_summary method."""

    def test_renders_when_summary_section_exists_and_data_present(self):
        data = make_candidate(summary=["I am great", "I know things"])
        template = {
            "page": {}, "layout": {},
            "sections": [{"key": "summary", "title": "Profile"}],
        }
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_summary(cell)
            mock_sec.assert_called_once()
            call_kwargs = mock_sec.call_args[1]
            self.assertTrue(call_kwargs.get("bulleted"))

    def test_skips_when_no_summary_section_key(self):
        data = make_candidate(summary=["Summary"])
        template = {"page": {}, "layout": {}, "sections": [{"key": "experience", "title": "Exp"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_summary(cell)
            mock_sec.assert_not_called()

    def test_skips_when_summary_data_is_empty(self):
        data = make_candidate(summary=[])
        template = {"page": {}, "layout": {}, "sections": [{"key": "summary", "title": "P"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_summary(cell)
            mock_sec.assert_not_called()

    def test_skips_when_summary_data_is_absent(self):
        data = {"name": "Jane"}
        template = {"page": {}, "layout": {}, "sections": [{"key": "summary", "title": "P"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_summary(cell)
            mock_sec.assert_not_called()

    def test_summary_capped_at_six_items(self):
        data = make_candidate(summary=["a", "b", "c", "d", "e", "f", "g"])
        template = {"page": {}, "layout": {}, "sections": [{"key": "summary", "title": "P"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_summary(cell)
            items_passed = mock_sec.call_args[0][2]
            self.assertLessEqual(len(items_passed), 6)

    def test_uses_section_title_from_template(self):
        data = make_candidate(summary=["Item"])
        template = {"page": {}, "layout": {}, "sections": [{"key": "summary", "title": "My Profile"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_summary(cell)
            title_passed = mock_sec.call_args[0][1]
            self.assertEqual(title_passed, "My Profile")


# ===========================================================================
# SidebarResumeWriter._render_sidebar_skills
# ===========================================================================

class TestRenderSidebarSkills(unittest.TestCase):
    """Tests for _render_sidebar_skills method."""

    def test_renders_when_skills_section_exists_and_items_present(self):
        group = make_skills_group(items=["Python", "Go", "Docker"])
        data = make_candidate(skills_groups=[group])
        template = {"page": {}, "layout": {}, "sections": [{"key": "skills", "title": "Skills"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_skills(cell)
            mock_sec.assert_called_once()
            items_passed = mock_sec.call_args[0][2]
            self.assertIn("Python", items_passed)

    def test_skips_when_no_skills_section_key(self):
        group = make_skills_group()
        data = make_candidate(skills_groups=[group])
        template = {"page": {}, "layout": {}, "sections": [{"key": "experience", "title": "Exp"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_skills(cell)
            mock_sec.assert_not_called()

    def test_skips_when_skills_groups_empty(self):
        data = make_candidate(skills_groups=[])
        template = {"page": {}, "layout": {}, "sections": [{"key": "skills", "title": "S"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_skills(cell)
            mock_sec.assert_not_called()

    def test_skips_when_skills_groups_absent(self):
        data = {"name": "Jane"}
        template = {"page": {}, "layout": {}, "sections": [{"key": "skills", "title": "S"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_skills(cell)
            mock_sec.assert_not_called()

    def test_dict_items_use_name_key(self):
        group = make_skills_group(items=[{"name": "Python"}, {"name": "Go"}])
        data = make_candidate(skills_groups=[group])
        template = {"page": {}, "layout": {}, "sections": [{"key": "skills", "title": "S"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_skills(cell)
            items_passed = mock_sec.call_args[0][2]
            self.assertIn("Python", items_passed)
            self.assertIn("Go", items_passed)

    def test_items_capped_at_eight(self):
        group = make_skills_group(items=["a", "b", "c", "d", "e", "f", "g", "h", "i"])
        data = make_candidate(skills_groups=[group])
        template = {"page": {}, "layout": {}, "sections": [{"key": "skills", "title": "S"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_skills(cell)
            items_passed = mock_sec.call_args[0][2]
            self.assertLessEqual(len(items_passed), 8)

    def test_flattens_multiple_groups(self):
        group1 = make_skills_group(items=["Python"])
        group2 = make_skills_group(items=["Docker"])
        data = make_candidate(skills_groups=[group1, group2])
        template = {"page": {}, "layout": {}, "sections": [{"key": "skills", "title": "S"}]}
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_sidebar_section") as mock_sec:
            writer._render_sidebar_skills(cell)
            items_passed = mock_sec.call_args[0][2]
            self.assertIn("Python", items_passed)
            self.assertIn("Docker", items_passed)


# ===========================================================================
# SidebarResumeWriter._render_sidebar_content
# ===========================================================================

class TestRenderSidebarContent(unittest.TestCase):
    """Tests for _render_sidebar_content method (delegates to summary + skills)."""

    def test_calls_both_summary_and_skills(self):
        writer = _make_writer()
        cell = MagicMock()
        with patch.object(writer, "_render_sidebar_summary") as mock_sum, \
             patch.object(writer, "_render_sidebar_skills") as mock_sk:
            writer._render_sidebar_content(cell)
            mock_sum.assert_called_once_with(cell)
            mock_sk.assert_called_once_with(cell)


# ===========================================================================
# SidebarResumeWriter._render_main_content
# ===========================================================================

class TestRenderMainContent(unittest.TestCase):
    """Tests for _render_main_content method."""

    def test_dispatches_known_section_keys(self):
        """Heading is rendered and renderer is called for each known section."""
        from resume.docx_sidebar_sections import SidebarResumeWriter

        data = make_candidate(
            experience=[make_experience_entry()],
            education=[make_education_entry()],
        )
        template = {
            "page": {}, "layout": {},
            "sections": [
                {"key": "education", "title": "Education"},
                {"key": "experience", "title": "Experience"},
            ],
        }
        writer = _make_writer(data=data, template=template)
        cell = MagicMock()

        mock_edu = MagicMock()
        mock_exp = MagicMock()
        original = SidebarResumeWriter._MAIN_SECTION_RENDERERS.copy()
        SidebarResumeWriter._MAIN_SECTION_RENDERERS["education"] = mock_edu
        SidebarResumeWriter._MAIN_SECTION_RENDERERS["experience"] = mock_exp

        try:
            with patch("resume.docx_sidebar_sections._render_main_section_heading") as mock_heading:
                writer._render_main_content(cell)
                self.assertEqual(mock_heading.call_count, 2)
                self.assertTrue(mock_edu.called)
                self.assertTrue(mock_exp.called)
        finally:
            SidebarResumeWriter._MAIN_SECTION_RENDERERS.update(original)

    def test_unknown_section_key_is_skipped(self):
        """Sections with unrecognised keys are skipped without error."""
        template = {
            "page": {}, "layout": {},
            "sections": [{"key": "unknown_key", "title": "Whatever"}],
        }
        writer = _make_writer(template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_main_section_heading") as mock_heading:
            writer._render_main_content(cell)
            mock_heading.assert_not_called()

    def test_empty_sections_produces_no_headings(self):
        template = {"page": {}, "layout": {}, "sections": []}
        writer = _make_writer(template=template)
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_main_section_heading") as mock_heading:
            writer._render_main_content(cell)
            mock_heading.assert_not_called()

    def test_no_sections_key_in_template(self):
        """If template has no 'sections' key, no sections are iterated."""
        writer = _make_writer(template={"page": {}, "layout": {}})
        cell = MagicMock()

        with patch("resume.docx_sidebar_sections._render_main_section_heading") as mock_heading:
            writer._render_main_content(cell)
            mock_heading.assert_not_called()


# ===========================================================================
# Module-level education / teaching / experience / presentations helpers
# ===========================================================================

class TestRenderMainEducation(unittest.TestCase):
    """Tests for module-level _render_main_education."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_main_education
        self._fn = _render_main_education

    def test_empty_education_list_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"education": []}), {"body_pt": 10})
        self.assertEqual(len(paras), 0)

    def test_missing_education_key_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({}), {"body_pt": 10})
        self.assertEqual(len(paras), 0)

    def test_single_entry_produces_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"education": [make_education_entry()]}), {"body_pt": 10, "meta_pt": 9})
        # At minimum: degree paragraph + edu meta paragraph
        self.assertGreaterEqual(len(paras), 2)

    def test_degree_run_is_bold(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"education": [make_education_entry(degree="B.S. CS")]}), {"body_pt": 10})
        degree_para = paras[0]
        # Second run (after bullet run) is the degree
        degree_run = degree_para.runs[1]
        self.assertTrue(degree_run.bold)


class TestRenderMainTeaching(unittest.TestCase):
    """Tests for module-level _render_main_teaching."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_main_teaching
        self._fn = _render_main_teaching

    def test_empty_teaching_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"teaching": []}), {"body_pt": 10})
        self.assertEqual(len(paras), 0)

    def test_missing_teaching_key_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({}), {"body_pt": 10})
        self.assertEqual(len(paras), 0)

    def test_plain_string_without_parens_produces_one_paragraph(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"teaching": ["Workshop"]}), {"body_pt": 10})
        self.assertEqual(len(paras), 1)

    def test_string_with_parens_produces_title_and_institution(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"teaching": ["Python (MIT)"]}), {"body_pt": 10, "meta_pt": 9})
        self.assertEqual(len(paras), 2)

    def test_dict_item_with_parens(self):
        """teaching is deliberately untyped; dict items with 'text' key are preserved."""
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"teaching": [{"text": "DB (Stanford)"}]}), {"body_pt": 10, "meta_pt": 9})
        self.assertEqual(len(paras), 2)

    def test_title_run_is_uppercase(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"teaching": ["Python Workshop"]}), {"body_pt": 10})
        run_texts = [r.text for r in paras[0].runs]
        self.assertIn("PYTHON WORKSHOP", run_texts)


class TestRenderMainExperience(unittest.TestCase):
    """Tests for module-level _render_main_experience."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_main_experience
        self._fn = _render_main_experience

    def test_empty_experience_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        sec = {"recent_max_bullets": 3}
        self._fn(cell, Resume.from_dict({"experience": []}), {"body_pt": 10}, sec)
        self.assertEqual(len(paras), 0)

    def test_missing_experience_key_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({}), {"body_pt": 10}, {"recent_max_bullets": 3})
        self.assertEqual(len(paras), 0)

    def test_renders_all_experience_entries(self):
        cell, paras = _make_cell()
        resume = Resume.from_dict({
            "experience": [make_experience_entry(bullets=[]), make_experience_entry(bullets=[])],
        })
        self._fn(cell, resume, {"body_pt": 10, "meta_pt": 9}, {"recent_max_bullets": 3})
        # Each entry: title + company = 2 paras; 2 entries = 4
        self.assertEqual(len(paras), 4)

    def test_uses_recent_max_bullets_from_sec(self):
        """max_bullets is read from sec dict."""
        cell, paras = _make_cell()
        resume = Resume.from_dict({"experience": [make_experience_entry(bullets=["a", "b", "c", "d"])]})
        self._fn(cell, resume, {"body_pt": 10, "meta_pt": 9}, {"recent_max_bullets": 2})
        # title + company + 2 bullets = 4
        self.assertEqual(len(paras), 4)


class TestRenderMainPresentations(unittest.TestCase):
    """Tests for module-level _render_main_presentations."""

    def setUp(self):
        from resume.docx_sidebar_sections import _render_main_presentations
        self._fn = _render_main_presentations

    def test_empty_presentations_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({"presentations": []}), {"body_pt": 10})
        self.assertEqual(len(paras), 0)

    def test_missing_presentations_key_produces_no_paragraphs(self):
        cell, paras = _make_cell()
        self._fn(cell, Resume.from_dict({}), {"body_pt": 10})
        self.assertEqual(len(paras), 0)

    def test_renders_full_entry(self):
        cell, paras = _make_cell()
        resume = Resume.from_dict({
            "presentations": [{"title": "My Talk", "authors": "A. B.", "event": "PyCon", "note": "Best"}],
        })
        self._fn(cell, resume, {"body_pt": 10})
        # One paragraph each for title, authors, event and note.
        self.assertEqual(len(paras), 4)

    def test_renders_multiple_entries(self):
        cell, paras = _make_cell()
        resume = Resume.from_dict({
            "presentations": [
                {"title": "Talk 1", "note": ""},
                {"title": "Talk 2", "note": ""},
            ],
        })
        self._fn(cell, resume, {"body_pt": 10})
        # Each minimal entry = 1 para; 2 entries = 2
        self.assertEqual(len(paras), 2)


if __name__ == "__main__":
    unittest.main()
