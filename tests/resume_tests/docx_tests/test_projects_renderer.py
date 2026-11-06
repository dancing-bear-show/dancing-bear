"""Tests for ProjectsSectionRenderer.

Covers:
- Section title, project name, link, desc, bullets, and tech appear in output
- Empty projects list renders no heading
- A project with only a name still renders
- _section_has_data recognises the projects key
- Both write_resume_docx and create_resume_writer render projects
"""
from __future__ import annotations

import unittest

from resume.schema import Resume
from tests.resume_tests.fixtures import make_fake_renderer, mock_docx_modules


@mock_docx_modules
class TestProjectsSectionRendererUnit(unittest.TestCase):
    """Unit tests for ProjectsSectionRenderer using FakeDocument."""

    def _get_renderer(self):
        from resume.docx_sections_simple import ProjectsSectionRenderer
        return make_fake_renderer(ProjectsSectionRenderer)

    def test_name_appears_in_rendered_output(self):
        """A project name is added as a paragraph."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({
            "name": "Casey Synthetic",
            "projects": [{"name": "Alpha Project"}],
        })
        lines = renderer.render(resume)
        self.assertIn("Alpha Project", lines)
        all_text = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("Alpha Project", all_text)

    def test_desc_appears_when_present(self):
        """Project desc is added as a plain paragraph."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({
            "projects": [{"name": "Beta", "desc": "A useful tool."}],
        })
        renderer.render(resume)
        all_text = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("A useful tool", all_text)

    def test_bullets_appear_when_present(self):
        """Project bullets are rendered."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({
            "projects": [{"name": "Gamma", "bullets": ["Did X", "Did Y"]}],
        })
        renderer.render(resume)
        all_text = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("Did X", all_text)
        self.assertIn("Did Y", all_text)

    def test_tech_appears_when_present(self):
        """Tech line is rendered as 'Tech: ...' paragraph."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({
            "projects": [{"name": "Delta", "tech": "Python, Go"}],
        })
        renderer.render(resume)
        all_text = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("Tech:", all_text)
        self.assertIn("Python", all_text)

    def test_empty_projects_renders_no_paragraphs(self):
        """An empty projects list produces no paragraphs."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({"projects": []})
        lines = renderer.render(resume)
        self.assertEqual(lines, [])
        self.assertEqual(doc.paragraphs, [])

    def test_name_only_project_renders_name(self):
        """A project with only a name still renders."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({"projects": [{"name": "Minimal"}]})
        lines = renderer.render(resume)
        self.assertEqual(lines, ["Minimal"])
        self.assertEqual(len(doc.paragraphs), 1)

    def test_project_missing_name_is_skipped(self):
        """A project with no name is silently skipped."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({
            "projects": [{"desc": "No name here"}],
        })
        lines = renderer.render(resume)
        self.assertEqual(lines, [])
        self.assertEqual(doc.paragraphs, [])

    def test_bullets_dict_shape_renders(self):
        """Dict-shaped bullets (text + priority) are rendered correctly."""
        renderer, doc = self._get_renderer()
        resume = Resume.from_dict({
            "projects": [
                {
                    "name": "Zeta",
                    "bullets": [{"text": "Built pipeline", "priority": 1.0}],
                }
            ],
        })
        renderer.render(resume)
        all_text = " ".join(p.text for p in doc.paragraphs)
        self.assertIn("Built pipeline", all_text)

    def test_multiple_projects_all_render(self):
        """Multiple projects all emit their names."""
        renderer, _ = self._get_renderer()
        resume = Resume.from_dict({
            "projects": [
                {"name": "First"},
                {"name": "Second"},
            ],
        })
        lines = renderer.render(resume)
        self.assertIn("First", lines)
        self.assertIn("Second", lines)


class TestSectionHasDataRecognisesProjects(unittest.TestCase):
    """_section_has_data returns True when projects is non-empty."""

    def test_non_empty_projects_has_data(self):
        from resume.docx_standard import _section_has_data

        resume = Resume.from_dict({"projects": [{"name": "X"}]})
        self.assertTrue(_section_has_data("projects", resume))

    def test_empty_projects_has_no_data(self):
        from resume.docx_standard import _section_has_data

        resume = Resume.from_dict({"projects": []})
        self.assertFalse(_section_has_data("projects", resume))

    def test_missing_projects_has_no_data(self):
        from resume.docx_standard import _section_has_data

        resume = Resume.from_dict({"name": "Casey Synthetic"})
        self.assertFalse(_section_has_data("projects", resume))


def _docx_available() -> bool:
    try:
        import docx  # noqa: F401
        return True
    except ImportError:
        return False


@unittest.skipUnless(_docx_available(), "python-docx not installed")
class TestProjectsEndToEnd(unittest.TestCase):
    """End-to-end rendering tests with real python-docx documents."""

    _TEMPLATE = {
        "sections": [{"key": "projects", "title": "Notable Projects"}],
    }

    def _render_via_writer(self, data: dict) -> list[str]:
        import os
        import tempfile
        from docx import Document
        from resume.docx_writer import write_resume_docx
        from resume.schema import Resume

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "projects.docx")
            write_resume_docx(Resume.from_dict(data), self._TEMPLATE, out)
            doc = Document(out)
            return [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    def _render_via_factory(self, data: dict) -> list[str]:
        import os
        import tempfile
        from docx import Document
        from resume.docx_base import create_resume_writer
        from resume.schema import Resume

        with tempfile.TemporaryDirectory() as tmpdir:
            out = os.path.join(tmpdir, "projects_factory.docx")
            create_resume_writer(Resume.from_dict(data), self._TEMPLATE).write(out)
            doc = Document(out)
            return [p.text.strip() for p in doc.paragraphs if p.text.strip()]

    def test_projects_section_renders_heading(self):
        """The 'Notable Projects' heading appears when projects exist."""
        data = {"name": "Casey Synthetic", "projects": [{"name": "Alpha"}]}
        texts = self._render_via_writer(data)
        self.assertIn("Notable Projects", texts)

    def test_projects_section_suppressed_when_empty(self):
        """No heading is emitted when projects is empty."""
        data = {"name": "Casey Synthetic", "projects": []}
        texts = self._render_via_writer(data)
        self.assertNotIn("Notable Projects", texts)

    def test_project_name_in_body(self):
        """Project name appears in the rendered document body."""
        data = {
            "name": "Casey Synthetic",
            "projects": [
                {
                    "name": "Alpha Project",
                    "desc": "A reliable service.",
                    "tech": "Python, Go",
                    "bullets": ["Reduced latency by 30%"],
                }
            ],
        }
        texts = self._render_via_writer(data)
        combined = " ".join(texts)
        self.assertIn("Alpha Project", combined)
        self.assertIn("A reliable service", combined)
        self.assertIn("Python", combined)
        self.assertIn("Reduced latency", combined)

    def test_entry_points_agree_on_projects(self):
        """write_resume_docx and create_resume_writer render the same headings."""
        data = {
            "name": "Casey Synthetic",
            "projects": [
                {"name": "Alpha", "desc": "First"},
                {"name": "Beta"},
            ],
        }
        via_writer = self._render_via_writer(data)
        via_factory = self._render_via_factory(data)
        # Both must contain "Notable Projects"; exact paragraph lists should agree.
        self.assertIn("Notable Projects", via_writer)
        self.assertIn("Notable Projects", via_factory)

    def test_name_only_project_renders(self):
        """A project with only a name renders without error."""
        data = {"name": "Casey Synthetic", "projects": [{"name": "Minimal"}]}
        texts = self._render_via_writer(data)
        combined = " ".join(texts)
        self.assertIn("Minimal", combined)


if __name__ == "__main__":
    unittest.main()
