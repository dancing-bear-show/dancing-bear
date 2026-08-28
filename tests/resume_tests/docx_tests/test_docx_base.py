"""Tests for resume/docx_base.py base DOCX writer classes."""

from __future__ import annotations

from tests.fixtures import test_path
import unittest
from unittest.mock import MagicMock, patch

from tests.resume_tests.fixtures import make_docx_paragraph_side_effect, mock_docx_modules

from resume.schema import Resume

@mock_docx_modules
class TestCreateResumeWriter(unittest.TestCase):
    """Tests for create_resume_writer factory function."""

    def test_returns_standard_writer_by_default(self):
        """Test factory returns StandardResumeWriter for no layout specified."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John Doe"})
        template = {"sections": []}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.__class__.__name__, "StandardResumeWriter")

    def test_returns_standard_writer_for_standard_layout(self):
        """Test factory returns StandardResumeWriter for 'standard' layout."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John Doe"})
        template = {"sections": [], "layout": {"type": "standard"}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.__class__.__name__, "StandardResumeWriter")

    def test_returns_sidebar_writer_for_sidebar_layout(self):
        """Test factory returns SidebarResumeWriter for 'sidebar' layout."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John Doe"})
        template = {"sections": [], "layout": {"type": "sidebar"}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.__class__.__name__, "SidebarResumeWriter")

    def test_stores_data_and_template(self):
        """Test writer stores resume and template.

        create_resume_writer requires a typed Resume -- the caller lifts, as
        this test does.  Only the typed object is kept; there is no lowered
        self.data mirror.  The test checks that the writer keeps the Resume
        it was given and the original template.
        """
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John Doe"})
        template = {"sections": [], "page": {"compact": True}}
        writer = create_resume_writer(data, template)
        self.assertIsInstance(writer.resume, Resume)
        self.assertEqual(writer.resume.name, "John Doe")
        self.assertEqual(writer.template, template)

    def test_extracts_page_config(self):
        """Test writer extracts page config from template."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John Doe"})
        template = {"page": {"compact": True, "margins_in": 0.4}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.page_cfg, {"compact": True, "margins_in": 0.4})

    def test_extracts_layout_config(self):
        """Test writer extracts layout config from template."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John Doe"})
        template = {"layout": {"type": "standard", "columns": 1}}
        writer = create_resume_writer(data, template)
        self.assertEqual(writer.layout_cfg, {"type": "standard", "columns": 1})


@mock_docx_modules
class TestResumeWriterBase(unittest.TestCase):
    """Tests for ResumeWriterBase methods."""

    def _get_writer(self):
        """Create a StandardResumeWriter for testing base methods."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({
            "name": "John Doe",
            "email": "john@example.com",
            "experience": [
                {"title": "Dev", "location": "Seattle, WA"},
                {"title": "Mgr", "location": "Portland, OR"},
                {"title": "Dir", "location": "Seattle, WA"},  # Duplicate
            ],
        })
        template = {"page": {}}
        return create_resume_writer(data, template)

    def test_extract_experience_locations_unique(self):
        """Test extracting unique locations from experience."""
        writer = self._get_writer()
        result = writer._extract_experience_locations()
        self.assertEqual(result, ["Seattle, WA", "Portland, OR"])

    def test_extract_experience_locations_empty(self):
        """Test extracting locations with no experience."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John"})
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._extract_experience_locations()
        self.assertEqual(result, [])

    def test_get_contact_field_top_level(self):
        """Test getting contact field from top level."""
        writer = self._get_writer()
        result = writer._get_contact_field("email")
        self.assertEqual(result, "john@example.com")

    def test_get_contact_field_nested(self):
        """Test getting contact field from nested contact dict."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John", "contact": {"phone": "555-1234"}})
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._get_contact_field("phone")
        self.assertEqual(result, "555-1234")

    def test_get_contact_field_prefers_top_level(self):
        """Test top level field is preferred over nested."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({
            "name": "John",
            "email": "top@example.com",
            "contact": {"email": "nested@example.com"},
        })
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._get_contact_field("email")
        self.assertEqual(result, "top@example.com")

    def test_get_contact_field_missing(self):
        """Test getting missing contact field returns empty string."""
        writer = self._get_writer()
        result = writer._get_contact_field("phone")
        self.assertEqual(result, "")

    def test_collect_link_extras_single_links(self):
        """Test collecting individual link fields."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({
            "name": "John",
            "website": "https://example.com",
            "linkedin": "https://linkedin.com/in/john",
            "github": "https://github.com/john",
        })
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._collect_link_extras()
        self.assertEqual(len(result), 3)

    def test_collect_link_extras_links_list(self):
        """Test collecting from links list."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({
            "name": "John",
            "links": ["https://blog.example.com", "https://portfolio.example.com"],
        })
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._collect_link_extras()
        self.assertEqual(len(result), 2)

    def test_collect_link_extras_empty(self):
        """Test collecting links with no links."""
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John"})
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        result = writer._collect_link_extras()
        self.assertEqual(result, [])


@mock_docx_modules
class TestIdentityFields(unittest.TestCase):
    """Tests for _identity_fields' nested-contact fallback."""

    def test_all_four_fields_fall_back_to_nested_contact(self):
        """A directly-built Resume resolves every field through contact.

        ``name`` regressed here: it was the only one of the four missing its
        ``contact.get()`` fallback, so a Resume constructed without going
        through ``from_dict``'s promotion lost its name entirely. Because
        ``set_document_metadata_on_doc`` gates ``cp.author`` on ``if name:``,
        the document then shipped with no author and raised nothing.
        """
        from resume.docx_base import _identity_fields
        from resume.schema import Resume
        resume = Resume(
            contact={
                "name": "Nested Name",
                "email": "nested@example.com",
                "phone": "555-0100",
                "location": "Springfield",
            }
        )
        self.assertEqual(
            _identity_fields(resume),
            ("Nested Name", "nested@example.com", "555-0100", "Springfield"),
        )

    def test_top_level_fields_win_over_nested_contact(self):
        """Top-level scalars take precedence over the nested contact dict."""
        from resume.docx_base import _identity_fields
        from resume.schema import Resume
        resume = Resume(
            name="Top Name",
            contact={"name": "Nested Name", "email": "nested@example.com"},
        )
        name, email, _phone, _location = _identity_fields(resume)
        self.assertEqual(name, "Top Name")
        self.assertEqual(email, "nested@example.com")

    def test_absent_everywhere_yields_empty_strings(self):
        """A Resume with neither source yields empty strings, not None."""
        from resume.docx_base import _identity_fields
        from resume.schema import Resume
        self.assertEqual(_identity_fields(Resume()), ("", "", "", ""))

    def test_author_is_set_from_nested_contact_name(self):
        """The nested-only name reaches cp.author, not just _identity_fields."""
        from resume.docx_base import set_document_metadata_on_doc
        from resume.schema import Resume
        doc = MagicMock()
        cp = doc.core_properties
        resume = Resume(contact={"name": "Nested Name"})
        set_document_metadata_on_doc(doc, resume, {})
        self.assertEqual(cp.author, "Nested Name")



@mock_docx_modules
class TestResumeWriterBaseWrite(unittest.TestCase):
    """Tests for ResumeWriterBase.write() method."""

    @patch("resume.docx_base.safe_import")
    def test_raises_when_docx_unavailable(self, mock_safe_import):
        """Test write raises when python-docx is not installed."""
        mock_safe_import.return_value = None
        from resume.docx_base import create_resume_writer
        data = Resume.from_dict({"name": "John"})
        template = {"page": {}}
        writer = create_resume_writer(data, template)
        with self.assertRaises(RuntimeError) as ctx:
            writer.write(test_path("test.docx"))  # nosec B108 - test fixture path
        self.assertIn("python-docx", str(ctx.exception))

    @patch("resume.docx_base.safe_import")
    def test_write_creates_and_saves_document(self, mock_safe_import):
        """Test write creates document and saves to path."""
        mock_docx = MagicMock()
        mock_doc = MagicMock()
        mock_section = MagicMock()
        mock_doc.sections = [mock_section]
        mock_paragraphs = []
        mock_doc.paragraphs = mock_paragraphs

        add_side_effect = make_docx_paragraph_side_effect(mock_paragraphs)
        mock_doc.add_heading.side_effect = add_side_effect
        mock_doc.add_paragraph.side_effect = add_side_effect
        mock_doc.styles = {
            "Normal": MagicMock(),
            "Heading 1": MagicMock(),
            "Title": MagicMock(),
        }
        mock_docx.Document.return_value = mock_doc
        mock_safe_import.return_value = mock_docx

        with patch.dict("sys.modules", {"docx": mock_docx}):
            from resume.docx_base import create_resume_writer
            data = Resume.from_dict({"name": "John Doe"})
            template = {"sections": [], "page": {"compact": False}}
            writer = create_resume_writer(data, template)
            writer.write(test_path("test.docx"))  # nosec B108 - test fixture path

        mock_doc.save.assert_called_once_with(test_path("test.docx"))  # nosec B108 - test fixture path


class TestNonDictContact(unittest.TestCase):
    """A non-dict ``Resume.contact`` must degrade, not crash the render.

    The schema types ``contact`` as ``dict[str, Any] | None`` but enforces it
    advisorily: ``Resume.from_dict`` logs a warning and stores the bad value
    uncoerced, and direct construction skips the check entirely. Both routes
    used to reach ``.get()`` on a non-mapping and raise ``AttributeError``.

    Sad-path methods use the test_rejects_* / test_invalid_* naming contract.
    """

    def test_invalid_contact_from_direct_construction_does_not_raise(self):
        """A directly built Resume with a string contact resolves to empty."""
        from resume.docx_base import get_contact_field
        from resume.schema import Resume

        resume = Resume(contact="not-a-dict")
        self.assertEqual(get_contact_field(resume, "email"), "")

    def test_invalid_contact_from_dict_does_not_raise(self):
        """from_dict warns but still stores the bad value; reads must survive.

        This is the path Copilot's report missed: advisory validation means a
        documented non-raising entry point led straight into an AttributeError.
        """
        from resume.docx_base import get_contact_field
        from resume.schema import Resume

        with self.assertLogs(level="WARNING"):
            resume = Resume.from_dict({"contact": "not-a-dict"})
        self.assertEqual(get_contact_field(resume, "email"), "")

    def test_rejects_shadowing_top_level_fields_with_bad_contact(self):
        """A bad contact must not suppress values present at the top level."""
        from resume.docx_base import get_contact_field
        from resume.schema import Resume

        with self.assertLogs(level="WARNING"):
            resume = Resume.from_dict(
                {"name": "Ada Example", "contact": "not-a-dict"}
            )
        self.assertEqual(get_contact_field(resume, "name"), "Ada Example")

    def test_invalid_contact_still_warns_on_from_dict(self):
        """Advisory validation is deliberate: the warning must still fire."""
        from resume.schema import Resume

        with self.assertLogs(level="WARNING") as captured:
            Resume.from_dict({"contact": "not-a-dict"})
        self.assertTrue(
            any("contact" in line and "expected dict" in line
                for line in captured.output),
            captured.output,
        )

    def test_invalid_contact_renders_identity_fields(self):
        """_identity_fields, the other consumer, must survive a bad contact."""
        from resume.docx_base import _identity_fields
        from resume.schema import Resume

        resume = Resume(name="Ada Example", contact=["not", "a", "dict"])
        name, email, phone, location = _identity_fields(resume)
        self.assertEqual(name, "Ada Example")
        self.assertEqual((email, phone, location), ("", "", ""))

    def test_dict_contact_still_resolves_nested_fields(self):
        """Regression guard: the normal dict path is unchanged."""
        from resume.docx_base import get_contact_field
        from resume.schema import Resume

        resume = Resume(contact={"email": "ada@example.com"})
        self.assertEqual(get_contact_field(resume, "email"), "ada@example.com")

    def test_none_contact_resolves_to_empty(self):
        """Regression guard: the default ``None`` contact still yields empty."""
        from resume.docx_base import get_contact_field
        from resume.schema import Resume

        self.assertEqual(get_contact_field(Resume(), "email"), "")


if __name__ == "__main__":
    unittest.main()
