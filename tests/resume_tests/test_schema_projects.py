"""Tests for the Project schema dataclass and Resume.projects field.

Covers:
- Project.from_dict with bare-string bullets (list[str] path)
- Project.from_dict with dict bullets (list[{text, priority}] path)
- Resume.from_dict wires projects through _LIST_ITEM_TYPES
- Resume.to_dict round-trips projects verbatim
"""
from __future__ import annotations

import unittest

from resume.schema import PriorityItem, Project, Resume


class TestProjectFromDict(unittest.TestCase):
    """Project.from_dict handles all supported input shapes."""

    def test_bare_string_bullets_coerced_to_priority_items(self):
        """Bare strings in bullets are upgraded to PriorityItem instances."""
        proj = Project.from_dict({
            "name": "My Project",
            "bullets": ["Built X", "Deployed Y"],
        })
        self.assertEqual(proj.name, "My Project")
        self.assertEqual(len(proj.bullets), 2)
        self.assertIsInstance(proj.bullets[0], PriorityItem)
        self.assertEqual(proj.bullets[0].text, "Built X")
        self.assertEqual(proj.bullets[1].text, "Deployed Y")

    def test_dict_bullets_with_priority_coerced(self):
        """Dict bullets with text and priority are coerced correctly."""
        proj = Project.from_dict({
            "name": "Open Source Tool",
            "bullets": [
                {"text": "Built X", "priority": 1.0},
                {"text": "Wrote tests", "priority": 0.5},
            ],
        })
        self.assertEqual(len(proj.bullets), 2)
        self.assertIsInstance(proj.bullets[0], PriorityItem)
        self.assertEqual(proj.bullets[0].text, "Built X")
        self.assertAlmostEqual(proj.bullets[0].priority, 1.0)
        self.assertEqual(proj.bullets[1].text, "Wrote tests")
        self.assertAlmostEqual(proj.bullets[1].priority, 0.5)

    def test_full_project_shape(self):
        """All supported fields are populated correctly."""
        proj = Project.from_dict({
            "name": "Project Name",
            "desc": "one-line description",
            "bullets": ["Built X"],
            "tech": "Python, OpenTelemetry",
            "link": "https://github.com/example/project",
            "priority": 0.9,
        })
        self.assertEqual(proj.name, "Project Name")
        self.assertEqual(proj.desc, "one-line description")
        self.assertEqual(proj.tech, "Python, OpenTelemetry")
        self.assertEqual(proj.link, "https://github.com/example/project")
        self.assertAlmostEqual(proj.priority, 0.9)
        self.assertEqual(len(proj.bullets), 1)
        self.assertEqual(proj.bullets[0].text, "Built X")

    def test_name_only_project(self):
        """A project with only a name is valid."""
        proj = Project.from_dict({"name": "Minimal Project"})
        self.assertEqual(proj.name, "Minimal Project")
        self.assertEqual(proj.bullets, [])
        self.assertEqual(proj.desc, "")
        self.assertEqual(proj.tech, "")
        self.assertEqual(proj.link, "")

    def test_empty_bullets_list(self):
        """An explicit empty bullets list stays empty."""
        proj = Project.from_dict({"name": "No Bullets", "bullets": []})
        self.assertEqual(proj.bullets, [])

    def test_missing_bullets_defaults_to_empty_list(self):
        """Omitting bullets gives an empty list, not None."""
        proj = Project.from_dict({"name": "No Bullets Key"})
        self.assertIsInstance(proj.bullets, list)
        self.assertEqual(proj.bullets, [])


class TestResumeProjectsField(unittest.TestCase):
    """Resume.from_dict wires projects through _LIST_ITEM_TYPES."""

    def test_projects_list_parsed_into_typed_items(self):
        """Resume.from_dict converts raw project dicts to Project instances."""
        data = {
            "name": "Casey Synthetic",
            "projects": [
                {
                    "name": "Alpha",
                    "desc": "First project",
                    "bullets": ["Did A", "Did B"],
                    "tech": "Python",
                    "link": "https://example.com/alpha",
                },
                {
                    "name": "Beta",
                    "bullets": [{"text": "Did C", "priority": 1.0}],
                },
            ],
        }
        resume = Resume.from_dict(data)
        self.assertEqual(len(resume.projects), 2)

        alpha = resume.projects[0]
        self.assertIsInstance(alpha, Project)
        self.assertEqual(alpha.name, "Alpha")
        self.assertEqual(alpha.desc, "First project")
        self.assertEqual(alpha.tech, "Python")
        self.assertEqual(alpha.link, "https://example.com/alpha")
        self.assertEqual(len(alpha.bullets), 2)
        self.assertEqual(alpha.bullets[0].text, "Did A")

        beta = resume.projects[1]
        self.assertEqual(beta.name, "Beta")
        self.assertEqual(len(beta.bullets), 1)
        self.assertEqual(beta.bullets[0].text, "Did C")

    def test_empty_projects_list_stays_empty(self):
        """An explicit empty projects list normalizes to []."""
        resume = Resume.from_dict({"name": "Casey Synthetic", "projects": []})
        self.assertEqual(resume.projects, [])

    def test_missing_projects_defaults_to_empty_list(self):
        """Omitting projects from the input gives []."""
        resume = Resume.from_dict({"name": "Casey Synthetic"})
        self.assertEqual(resume.projects, [])

    def test_projects_round_trips_through_to_dict(self):
        """Resume.to_dict preserves project data verbatim."""
        raw = {
            "name": "Casey Synthetic",
            "projects": [
                {
                    "name": "Alpha",
                    "desc": "First",
                    "tech": "Go",
                    "link": "https://example.com",
                    "priority": 0.8,
                    "bullets": [{"text": "Did X", "priority": 1.0}],
                }
            ],
        }
        resume = Resume.from_dict(raw)
        out = resume.to_dict()
        self.assertIn("projects", out)
        self.assertEqual(len(out["projects"]), 1)
        proj_out = out["projects"][0]
        self.assertEqual(proj_out["name"], "Alpha")
        self.assertEqual(proj_out["desc"], "First")
        self.assertEqual(proj_out["tech"], "Go")
        self.assertEqual(proj_out["link"], "https://example.com")
        self.assertAlmostEqual(proj_out["priority"], 0.8)
        self.assertEqual(proj_out["bullets"][0]["text"], "Did X")


if __name__ == "__main__":
    unittest.main()
