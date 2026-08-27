"""End-to-end tests for the write_resume_docx path via docx_writer.py.

These tests render a real DOCX via write_resume_docx (the ACTIVE CLI path)
and inspect the zip contents to confirm mailto: hyperlinks are present.

Mirrors the assertion style in tests/resume_tests/docx_tests/test_docx_links.py.
"""
from __future__ import annotations

import io
import os
import tempfile
import unittest
import zipfile


def _docx_available() -> bool:
    """Check if python-docx is installed."""
    try:
        import docx  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_docx_available(), "python-docx not installed")
class TestWriteResumeDocxMailtoHyperlink(unittest.TestCase):
    """Integration tests: render a DOCX via write_resume_docx, inspect zip contents.

    Tests run against the ACTIVE code path used by the CLI (docx_writer.py).
    """

    def _render(self, data: dict, template: dict) -> bytes:
        """Render a resume via write_resume_docx and return DOCX bytes.

        Cases are authored as dicts; the writer takes a typed ``Resume``, so
        the lift happens here rather than in every test.
        """
        from resume.docx_writer import write_resume_docx
        from resume.schema import Resume
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            path = f.name
        try:
            write_resume_docx(Resume.from_dict(data), template, path)
            with open(path, "rb") as f:
                return f.read()
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def _zip_member(self, docx_bytes: bytes, name: str) -> str:
        """Extract and decode a zip member from DOCX bytes."""
        with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
            return z.read(name).decode("utf-8")

    # -------------------------------------------------------------------------
    # mailto: hyperlink via docx_writer.py
    # -------------------------------------------------------------------------

    def test_email_produces_mailto_relationship_via_docx_writer(self):
        """Email in contact produces a mailto: external relationship (docx_writer path)."""
        data = {"name": "Fixture Test", "email": "fixture@example.com"}
        template = {"sections": [], "page": {"compact": False}}

        docx_bytes = self._render(data, template)
        rels_xml = self._zip_member(docx_bytes, "word/_rels/document.xml.rels")

        self.assertIn("mailto:fixture@example.com", rels_xml)
        self.assertIn('TargetMode="External"', rels_xml)

    def test_email_produces_w_hyperlink_element_via_docx_writer(self):
        """Email in contact produces a w:hyperlink element in document.xml (docx_writer path)."""
        data = {"name": "Fixture Test", "email": "fixture@example.com"}
        template = {"sections": [], "page": {"compact": False}}

        docx_bytes = self._render(data, template)
        doc_xml = self._zip_member(docx_bytes, "word/document.xml")

        self.assertIn("w:hyperlink", doc_xml)

    def test_website_produces_external_relationship_via_docx_writer(self):
        """Website URL in contact produces an https: external relationship (docx_writer path)."""
        data = {"name": "Link Test", "website": "https://example.dev"}
        template = {"sections": [], "page": {"compact": False}}

        docx_bytes = self._render(data, template)
        rels_xml = self._zip_member(docx_bytes, "word/_rels/document.xml.rels")

        self.assertIn("https://example.dev", rels_xml)
        self.assertIn('TargetMode="External"', rels_xml)

    def test_phone_and_location_remain_plain_text(self):
        """Phone and location render as plain text, not hyperlinks (docx_writer path)."""
        data = {
            "name": "Plain Test",
            "email": "plain@example.com",
            "phone": "555-9999",
            "location": "Portland, OR",
        }
        template = {"sections": [], "page": {"compact": False}}

        docx_bytes = self._render(data, template)
        doc_xml = self._zip_member(docx_bytes, "word/document.xml")
        rels_xml = self._zip_member(docx_bytes, "word/_rels/document.xml.rels")

        # Email is a hyperlink
        self.assertIn("mailto:plain@example.com", rels_xml)
        # Phone number does NOT appear as a relationship target
        self.assertNotIn("555-9999", rels_xml)
        # Document has the name
        self.assertIn("Plain Test", doc_xml)

    def test_no_email_renders_cleanly_without_mailto(self):
        """Resume with no email renders cleanly with no mailto: relationship (docx_writer path)."""
        data = {"name": "No Email", "phone": "555-0000", "location": "Seattle, WA"}
        template = {"sections": [], "page": {"compact": False}}

        docx_bytes = self._render(data, template)
        rels_xml = self._zip_member(docx_bytes, "word/_rels/document.xml.rels")

        self.assertNotIn("mailto:", rels_xml)
        doc_xml = self._zip_member(docx_bytes, "word/document.xml")
        self.assertIn("No Email", doc_xml)

    def test_github_extra_produces_external_relationship_via_docx_writer(self):
        """GitHub URL in contact extras produces an external https: relationship (docx_writer path)."""
        data = {
            "name": "Github Test",
            "email": "gh@example.com",
            "github": "github.com/ghtest",
        }
        template = {"sections": [], "page": {"compact": False}}

        docx_bytes = self._render(data, template)
        rels_xml = self._zip_member(docx_bytes, "word/_rels/document.xml.rels")

        self.assertIn("github.com/ghtest", rels_xml)
        self.assertIn('TargetMode="External"', rels_xml)


if __name__ == "__main__":
    unittest.main()
