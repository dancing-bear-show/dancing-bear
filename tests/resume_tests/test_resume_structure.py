"""Tests for resume/structure.py docx structure inference."""

import unittest
from unittest.mock import MagicMock, patch


class TestInferStructureFromDocx(unittest.TestCase):
    """Tests for infer_structure_from_docx function."""

    def _make_fake_paragraph(self, text: str, style_name: str = "Normal"):
        """Create a mock paragraph with text and style."""
        p = MagicMock()
        p.text = text
        p.style = MagicMock()
        p.style.name = style_name
        return p

    def test_infers_sections_from_headings(self):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            self._make_fake_paragraph("John Doe", "Normal"),
            self._make_fake_paragraph("Summary", "Heading 1"),
            self._make_fake_paragraph("Experienced engineer...", "Normal"),
            self._make_fake_paragraph("Experience", "Heading 1"),
            self._make_fake_paragraph("Senior Dev at TechCorp", "Normal"),
            self._make_fake_paragraph("Skills", "Heading 1"),
            self._make_fake_paragraph("Python, Java", "Normal"),
            self._make_fake_paragraph("Education", "Heading 1"),
            self._make_fake_paragraph("BS Computer Science", "Normal"),
        ]

        with patch("resume.structure.safe_import") as mock_import:
            mock_docx = MagicMock()
            mock_import.return_value = mock_docx

            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("docx.Document", return_value=mock_doc):
                    from resume.structure import infer_structure_from_docx

                    result = infer_structure_from_docx("/fake/path.docx")

                    self.assertEqual(result["order"], ["summary", "experience", "skills", "education"])
                    self.assertEqual(result["titles"]["summary"], "Summary")
                    self.assertEqual(result["titles"]["experience"], "Experience")

    def test_returns_default_order_when_no_headings(self):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            self._make_fake_paragraph("John Doe", "Normal"),
            self._make_fake_paragraph("Some content", "Normal"),
        ]

        with patch("resume.structure.safe_import") as mock_import:
            mock_docx = MagicMock()
            mock_import.return_value = mock_docx

            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("docx.Document", return_value=mock_doc):
                    from resume.structure import infer_structure_from_docx

                    result = infer_structure_from_docx("/fake/path.docx")

                    self.assertEqual(result["order"], ["summary", "skills", "experience", "education"])
                    self.assertEqual(result["titles"]["summary"], "Summary")

    def test_skips_non_heading_styles(self):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            self._make_fake_paragraph("Experience", "Normal"),  # Not a heading
            self._make_fake_paragraph("Skills", "Heading 2"),  # Is a heading
        ]

        with patch("resume.structure.safe_import") as mock_import:
            mock_docx = MagicMock()
            mock_import.return_value = mock_docx

            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("docx.Document", return_value=mock_doc):
                    from resume.structure import infer_structure_from_docx

                    result = infer_structure_from_docx("/fake/path.docx")

                    self.assertIn("skills", result["order"])
                    # "experience" shouldn't be in order since it's not a heading
                    self.assertNotIn("experience", result["order"])

    def test_handles_heading_2_style(self):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            self._make_fake_paragraph("Summary", "Heading 2"),
            self._make_fake_paragraph("Experience", "Heading 2"),
        ]

        with patch("resume.structure.safe_import") as mock_import:
            mock_docx = MagicMock()
            mock_import.return_value = mock_docx

            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("docx.Document", return_value=mock_doc):
                    from resume.structure import infer_structure_from_docx

                    result = infer_structure_from_docx("/fake/path.docx")

                    self.assertIn("summary", result["order"])
                    self.assertIn("experience", result["order"])

    def test_skips_empty_headings(self):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            self._make_fake_paragraph("", "Heading 1"),
            self._make_fake_paragraph("   ", "Heading 1"),
            self._make_fake_paragraph("Skills", "Heading 1"),
        ]

        with patch("resume.structure.safe_import") as mock_import:
            mock_docx = MagicMock()
            mock_import.return_value = mock_docx

            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("docx.Document", return_value=mock_doc):
                    from resume.structure import infer_structure_from_docx

                    result = infer_structure_from_docx("/fake/path.docx")

                    self.assertEqual(result["order"], ["skills"])

    def test_deduplicates_sections(self):
        mock_doc = MagicMock()
        mock_doc.paragraphs = [
            self._make_fake_paragraph("Summary", "Heading 1"),
            self._make_fake_paragraph("Summary", "Heading 1"),  # Duplicate
            self._make_fake_paragraph("Experience", "Heading 1"),
        ]

        with patch("resume.structure.safe_import") as mock_import:
            mock_docx = MagicMock()
            mock_import.return_value = mock_docx

            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("docx.Document", return_value=mock_doc):
                    from resume.structure import infer_structure_from_docx

                    result = infer_structure_from_docx("/fake/path.docx")

                    # Should only have one summary
                    self.assertEqual(result["order"].count("summary"), 1)

    def test_raises_when_docx_not_available(self):
        with patch("resume.structure.safe_import", return_value=None):
            from resume.structure import infer_structure_from_docx

            with self.assertRaises(RuntimeError) as ctx:
                infer_structure_from_docx("/fake/path.docx")

            self.assertIn("python-docx", str(ctx.exception))

    def test_handles_paragraph_without_style(self):
        mock_doc = MagicMock()
        p_no_style = MagicMock()
        p_no_style.text = "Summary"
        p_no_style.style = None  # No style

        mock_doc.paragraphs = [p_no_style]

        with patch("resume.structure.safe_import") as mock_import:
            mock_docx = MagicMock()
            mock_import.return_value = mock_docx

            with patch.dict("sys.modules", {"docx": MagicMock()}):
                with patch("docx.Document", return_value=mock_doc):
                    from resume.structure import infer_structure_from_docx

                    # Should not raise, returns default
                    result = infer_structure_from_docx("/fake/path.docx")
                    self.assertEqual(result["order"], ["summary", "skills", "experience", "education"])


if __name__ == "__main__":
    unittest.main()
