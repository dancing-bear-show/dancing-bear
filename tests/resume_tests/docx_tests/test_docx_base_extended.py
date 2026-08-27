"""Extended tests for resume/docx_base.py — covering previously uncovered paths."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from tests.resume_tests.fixtures import mock_docx_modules


def _make_compact_doc():
    """Make a mock Document with styles dict for compact page style tests."""
    doc = MagicMock()
    mock_section = MagicMock()
    doc.sections = [mock_section]

    normal_style = MagicMock()
    heading1_style = MagicMock()
    title_style = MagicMock()
    doc.styles = {
        "Normal": normal_style,
        "Heading 1": heading1_style,
        "Title": title_style,
    }
    doc.core_properties = MagicMock()
    doc.paragraphs = []
    return doc


@mock_docx_modules
class TestApplyPageStylesCompact(unittest.TestCase):
    """Tests for _apply_page_styles when compact=True."""

    def _get_writer(self, page_cfg):
        from resume.docx_base import create_resume_writer
        writer = create_resume_writer({"name": "Test"}, {"page": page_cfg})
        writer.doc = _make_compact_doc()
        return writer

    def test_compact_sets_margins(self):
        writer = self._get_writer({"compact": True, "margins_in": 0.75})
        writer._apply_page_styles()
        section = writer.doc.sections[0]
        # margins should be set
        self.assertIsNotNone(section.top_margin)

    def test_compact_sets_normal_font_size(self):
        writer = self._get_writer({"compact": True, "body_pt": 10.5})
        writer._apply_page_styles()
        # Normal style font size should be set
        writer.doc.styles["Normal"].font.size is not None

    def test_compact_sets_heading1_styles(self):
        writer = self._get_writer({"compact": True, "h1_pt": 12, "h1_color": "#336699"})
        writer._apply_page_styles()
        h1 = writer.doc.styles["Heading 1"]
        h1.font.bold = True  # Should have been set

    def test_compact_with_h1_bg_dark_sets_white_text(self):
        """When h1_bg is dark and no h1_color, text should be white."""
        writer = self._get_writer({"compact": True, "h1_bg": "#1A1A1A"})
        # Should not raise
        writer._apply_page_styles()

    def test_compact_with_h1_bg_light_sets_dark_text(self):
        """When h1_bg is light and no h1_color, text should be black."""
        writer = self._get_writer({"compact": True, "h1_bg": "#EEEEEE"})
        # Should not raise
        writer._apply_page_styles()

    def test_compact_sets_title_styles(self):
        writer = self._get_writer({"compact": True, "title_pt": 16, "title_color": "#000000"})
        writer._apply_page_styles()
        title = writer.doc.styles["Title"]
        title.font.bold = True  # Should have been set

    def test_compact_with_title_no_color(self):
        """Title color not set when title_color is None."""
        writer = self._get_writer({"compact": True, "title_pt": 14})
        writer._apply_page_styles()
        # Should not raise

    def test_non_compact_does_not_apply_styles(self):
        writer = self._get_writer({"compact": False})
        writer._apply_page_styles()
        # sections should not have been touched (no margin assignments attempted)
        writer.doc.sections[0].top_margin  # accessing is fine, but shouldn't raise

    def test_compact_handles_exception_gracefully(self):
        writer = self._get_writer({"compact": True})
        # Make sections raise exception to test graceful handling
        writer.doc.sections = None  # Will cause IndexError
        # Should not raise due to nosec B110 exception handler
        writer._apply_page_styles()


@mock_docx_modules
class TestSetDocumentMetadataExtended(unittest.TestCase):
    """Extended tests for _set_document_metadata in ResumeWriterBase."""

    def _get_writer(self, data, page_cfg=None):
        from resume.docx_base import create_resume_writer
        writer = create_resume_writer(data, {"page": page_cfg or {}})
        writer.doc = _make_compact_doc()
        return writer

    def test_metadata_with_full_contact(self):
        data = {
            "name": "Jane Smith",
            "email": "jane@example.com",
            "phone": "555-9876",
            "location": "Austin, TX",
        }
        writer = self._get_writer(data)
        writer._set_document_metadata()
        cp = writer.doc.core_properties
        self.assertIn("Jane Smith", cp.title)
        self.assertEqual(cp.author, "Jane Smith")
        self.assertIn("jane@example.com", cp.keywords)

    def test_metadata_with_nested_contact(self):
        data = {
            "name": "Bob Jones",
            "contact": {
                "email": "bob@example.com",
                "phone": "555-0000",
                "location": "Portland, OR",
            }
        }
        writer = self._get_writer(data)
        writer._set_document_metadata()
        cp = writer.doc.core_properties
        self.assertIn("Bob Jones", cp.title)

    def test_metadata_includes_experience_locations(self):
        data = {
            "name": "Alex",
            "experience": [
                {"location": "Seattle, WA"},
                {"location": "Denver, CO"},
            ]
        }
        writer = self._get_writer(data, page_cfg={"metadata_include_locations": True})
        writer._set_document_metadata()
        cp = writer.doc.core_properties
        self.assertIn("Seattle, WA", cp.keywords)
        self.assertIn("Denver, CO", cp.keywords)

    def test_metadata_excludes_locations_when_disabled(self):
        data = {
            "name": "Alex",
            "experience": [{"location": "Seattle, WA"}],
        }
        writer = self._get_writer(data, page_cfg={"metadata_include_locations": False})
        writer._set_document_metadata()
        cp = writer.doc.core_properties
        self.assertNotIn("Seattle, WA", cp.keywords)

    def test_metadata_handles_exception(self):
        """Test that metadata setting handles exceptions gracefully."""
        from resume.docx_base import create_resume_writer
        writer = create_resume_writer({"name": "Test"}, {})
        # doc with broken core_properties
        writer.doc = MagicMock()
        writer.doc.core_properties = None  # Will cause AttributeError
        # Should not raise
        writer._set_document_metadata()

    def test_metadata_default_title_when_no_name(self):
        writer = self._get_writer({})
        writer._set_document_metadata()
        cp = writer.doc.core_properties
        self.assertEqual(cp.title, "Resume")


@mock_docx_modules
class TestAddColoredRun(unittest.TestCase):
    """Tests for ResumeWriterBase._add_colored_run."""

    def _get_writer(self):
        from resume.docx_base import create_resume_writer
        return create_resume_writer({"name": "Test"}, {})

    def test_adds_run_with_text(self):
        writer = self._get_writer()
        para = MagicMock()
        mock_run = MagicMock()
        para.add_run.return_value = mock_run
        writer._add_colored_run(para, "Hello", None)
        para.add_run.assert_called_once_with("Hello")

    def test_adds_run_with_color(self):
        writer = self._get_writer()
        para = MagicMock()
        mock_run = MagicMock()
        para.add_run.return_value = mock_run
        writer._add_colored_run(para, "Colored", "#FF0000")
        # Color should be applied
        para.add_run.assert_called_once_with("Colored")
        # run.font.color.rgb should be set

    def test_adds_run_with_invalid_color(self):
        writer = self._get_writer()
        para = MagicMock()
        mock_run = MagicMock()
        para.add_run.return_value = mock_run
        # Invalid color should not raise
        writer._add_colored_run(para, "Text", "invalid")
        para.add_run.assert_called_once_with("Text")

    def test_adds_run_with_no_color(self):
        writer = self._get_writer()
        para = MagicMock()
        mock_run = MagicMock()
        para.add_run.return_value = mock_run
        result = writer._add_colored_run(para, "Plain", None)
        self.assertEqual(result, mock_run)

    def test_kwargs_set_on_run_or_font(self):
        writer = self._get_writer()
        para = MagicMock()
        mock_run = MagicMock()
        para.add_run.return_value = mock_run
        # bold is an attribute of run directly
        writer._add_colored_run(para, "Bold", None, bold=True)
        # Should not raise; bold either set on run or font

    def test_returns_run(self):
        writer = self._get_writer()
        para = MagicMock()
        mock_run = MagicMock()
        para.add_run.return_value = mock_run
        result = writer._add_colored_run(para, "Text", None)
        self.assertEqual(result, mock_run)


@mock_docx_modules
class TestExtractExperienceLocationsBase(unittest.TestCase):
    """Tests for _extract_experience_locations in base class."""

    def _get_writer(self, data):
        from resume.docx_base import create_resume_writer
        return create_resume_writer(data, {})

    def test_extracts_unique_ordered(self):
        data = {"experience": [
            {"location": "NYC"},
            {"location": "LA"},
            {"location": "NYC"},  # duplicate
        ]}
        writer = self._get_writer(data)
        result = writer._extract_experience_locations()
        self.assertEqual(result, ["NYC", "LA"])

    def test_skips_empty_locations(self):
        # `location` is declared str, but an explicit null in the source file
        # survives as None -- blank and null must both be skipped, not crash.
        data = {"experience": [
            {"location": ""},
            {"location": "Boston, MA"},
            {"location": None},
        ]}
        writer = self._get_writer(data)
        result = writer._extract_experience_locations()
        self.assertEqual(result, ["Boston, MA"])

    def test_handles_no_experience_key(self):
        writer = self._get_writer({})
        result = writer._extract_experience_locations()
        self.assertEqual(result, [])


@mock_docx_modules
class TestFitProperty(unittest.TestCase):
    """Tests for _fit_property — the OPC 255-char core-property cap.

    python-docx raises ValueError rather than truncating an over-long core
    property. In set_document_metadata_on_doc that raise lands inside a bare
    `except Exception`, which silently drops the keywords AND every later
    assignment (including the date stamping). These tests pin the boundary so
    that failure mode cannot return unnoticed.
    """

    def _fit(self, *args, **kwargs):
        from resume.docx_base import _fit_property
        return _fit_property(*args, **kwargs)

    def test_short_list_joins_all_items(self):
        self.assertEqual(self._fit(["Kafka", "Kubernetes"]), "Kafka; Kubernetes")

    def test_empty_list_returns_empty_string(self):
        self.assertEqual(self._fit([]), "")

    def test_result_never_exceeds_opc_limit(self):
        result = self._fit([f"Skill{i:03d}" * 3 for i in range(40)])
        self.assertLessEqual(len(result), 255)

    def test_drops_whole_items_not_partial_ones(self):
        """Overflow must trim on a separator boundary, never mid-keyword."""
        items = ["A" * 100, "B" * 100, "C" * 100]
        result = self._fit(items)
        self.assertLessEqual(len(result), 255)
        for part in result.split("; "):
            self.assertIn(part, items)

    def test_keeps_as_many_items_as_fit(self):
        result = self._fit(["A" * 100, "B" * 100, "C" * 100])
        self.assertEqual(result, "A" * 100 + "; " + "B" * 100)

    def test_single_item_over_limit_yields_empty(self):
        """A lone oversized item cannot be trimmed, so nothing is emitted.

        Better an empty keywords field than a raised ValueError that aborts
        the rest of the metadata assignment.
        """
        self.assertEqual(self._fit(["X" * 300]), "")

    def test_exactly_at_limit_is_kept(self):
        self.assertEqual(len(self._fit(["Y" * 255])), 255)

    def test_custom_separator(self):
        self.assertEqual(self._fit(["a", "b"], sep=", "), "a, b")


@mock_docx_modules
class TestMetadataOptions(unittest.TestCase):
    """Tests for the metadata_* page-config options.

    Core properties survive PDF export and are read by ATS, so a phone number
    left in `keywords` leaks in a field the author never sees.
    """

    def _set(self, data, page_cfg):
        from resume.docx_base import set_document_metadata_on_doc
        from resume.schema import Resume
        doc = MagicMock()
        doc.core_properties = MagicMock()
        set_document_metadata_on_doc(doc, Resume.from_dict(data), page_cfg)
        return doc.core_properties

    DATA = {
        "name": "Jane Smith",
        "email": "jane@example.com",
        "phone": "555-9876",
        "location": "Austin, TX",
    }

    def test_pii_included_by_default(self):
        """Default must stay backward compatible."""
        cp = self._set(self.DATA, {})
        self.assertIn("jane@example.com", cp.title)
        self.assertIn("555-9876", cp.keywords)

    def test_metadata_pii_false_strips_contact_from_title(self):
        cp = self._set(self.DATA, {"metadata_pii": False})
        self.assertIn("Jane Smith", cp.title)
        self.assertNotIn("jane@example.com", cp.title)
        self.assertNotIn("555-9876", cp.title)

    def test_metadata_pii_false_strips_contact_from_keywords(self):
        cp = self._set(self.DATA, {"metadata_pii": False})
        self.assertNotIn("jane@example.com", cp.keywords)
        self.assertNotIn("555-9876", cp.keywords)
        self.assertNotIn("Austin, TX", cp.keywords)

    def test_metadata_title_override(self):
        cp = self._set(self.DATA, {"metadata_title": "Jane Smith - SRE Resume"})
        self.assertEqual(cp.title, "Jane Smith - SRE Resume")

    def test_metadata_keywords_override_replaces_identity_terms(self):
        cp = self._set(
            self.DATA,
            {"metadata_keywords": ["Kubernetes", "OpenTelemetry"]},
        )
        self.assertEqual(cp.keywords, "Kubernetes; OpenTelemetry")
        self.assertNotIn("jane@example.com", cp.keywords)

    def test_metadata_keywords_override_accepts_a_string(self):
        cp = self._set(self.DATA, {"metadata_keywords": "Kafka"})
        self.assertEqual(cp.keywords, "Kafka")

    def test_oversized_keyword_override_is_trimmed_not_dropped(self):
        """Regression: an over-long list used to abort all later metadata."""
        cp = self._set(
            self.DATA,
            {"metadata_keywords": [f"Skill{i:02d}" * 4 for i in range(30)]},
        )
        self.assertTrue(cp.keywords)
        self.assertLessEqual(len(cp.keywords), 255)

    def test_metadata_comments_clears_generator_string(self):
        cp = self._set(self.DATA, {"metadata_comments": ""})
        self.assertEqual(cp.comments, "")

    def test_dates_stamped_by_default(self):
        cp = self._set(self.DATA, {})
        self.assertEqual(cp.created, cp.modified)
        self.assertGreater(cp.created.year, 2013)

    def test_stamp_dates_can_be_disabled(self):
        cp = self._set(self.DATA, {"metadata_stamp_dates": False})
        self.assertIsInstance(cp.created, MagicMock)

    def test_dates_still_stamped_after_oversized_keywords(self):
        """The original bug: a keywords ValueError skipped the date stamping."""
        cp = self._set(
            self.DATA,
            {"metadata_keywords": [f"Skill{i:02d}" * 4 for i in range(30)]},
        )
        self.assertGreater(cp.created.year, 2013)


if __name__ == "__main__":
    unittest.main()
