"""Section-specific docx renderer tests: Summary, Skills, Experience, Education, Technologies."""
from __future__ import annotations
import unittest

from resume.schema import ExperienceEntry, Resume
from tests.resume_tests.fixtures import make_fake_renderer, mock_docx_modules


def _entry(raw: dict) -> ExperienceEntry:
    """Build one typed experience entry from its raw dict form."""
    return ExperienceEntry.from_dict(raw)


def _bullets(raw: list) -> list:
    """Build typed bullets from their raw dict/string forms.

    Goes through ``ExperienceEntry`` rather than constructing items directly,
    so the bullets are normalized by exactly the path production uses.
    """
    return ExperienceEntry.from_dict({"bullets": raw}).bullets


@mock_docx_modules
class TestSummarySectionRenderer(unittest.TestCase):
    """Tests for SummarySectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections_skills import SummarySectionRenderer
        return make_fake_renderer(SummarySectionRenderer)

    def test_render_string_summary(self):
        """Test rendering string summary."""
        renderer, doc = self._get_renderer()
        data = {"summary": "Experienced software engineer with 10 years of experience."}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(len(doc.paragraphs), 1)

    def test_render_list_summary(self):
        """Test rendering list summary."""
        renderer, doc = self._get_renderer()
        data = {"summary": ["Point 1", "Point 2", "Point 3"]}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_bulleted_string(self):
        """Test rendering bulleted string summary."""
        renderer, doc = self._get_renderer()
        data = {"summary": "First point. Second point. Third point."}
        renderer.render(Resume.from_dict(data), sec={"bulleted": True})
        self.assertEqual(len(doc.paragraphs), 3)

    def test_render_with_keywords(self):
        """Test rendering with keyword highlighting."""
        renderer, doc = self._get_renderer()
        data = {"summary": "Expert in Python and JavaScript development."}
        renderer.render(Resume.from_dict(data), keywords=["Python", "JavaScript"])
        self.assertEqual(len(doc.paragraphs), 1)

    def test_normalize_list_items_dicts(self):
        """The 'line' alias and the 'desc' fallback both yield display text."""
        renderer, _ = self._get_renderer()
        items = Resume.from_dict(
            {"summary": [{"text": "Item 1"}, {"line": "Item 2"}, {"desc": "Item 3"}]}
        ).summary
        result = renderer._normalize_list_items(items)
        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])

    def test_normalize_list_items_strings(self):
        """Bare-string summary entries are upgraded to items carrying `text`."""
        renderer, _ = self._get_renderer()
        items = Resume.from_dict({"summary": ["Item 1", "Item 2", "Item 3"]}).summary
        result = renderer._normalize_list_items(items)
        self.assertEqual(result, ["Item 1", "Item 2", "Item 3"])

    def test_normalize_list_items_skips_empty(self):
        """Items with no text in any readable field are dropped."""
        renderer, _ = self._get_renderer()
        items = Resume.from_dict({"summary": ["Valid", "", {"text": ""}]}).summary
        result = renderer._normalize_list_items(items)
        self.assertEqual(result, ["Valid"])

    def test_render_bulleted_string_with_max_sentences(self):
        """sec={"bulleted": True, "max_sentences": N} truncates the sentence split."""
        renderer, doc = self._get_renderer()
        data = {"summary": "One. Two. Three. Four. Five."}
        renderer.render(Resume.from_dict(data), sec={"bulleted": True, "max_sentences": 2})
        self.assertEqual(len(doc.paragraphs), 2)

    def test_render_falls_back_to_headline_when_no_summary(self):
        """render() falls back to data["headline"] when summary is absent."""
        renderer, doc = self._get_renderer()
        data = {"headline": "Software Engineer at Tech Co"}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(len(doc.paragraphs), 1)


@mock_docx_modules
class TestSkillsSectionRenderer(unittest.TestCase):
    """Tests for SkillsSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections_skills import SkillsSectionRenderer
        return make_fake_renderer(SkillsSectionRenderer)

    def test_render_flat_skills(self):
        """Test rendering flat skills list."""
        renderer, doc = self._get_renderer()
        data = {"skills": ["Python", "JavaScript", "Go"]}
        renderer.render(Resume.from_dict(data))
        self.assertGreater(len(doc.paragraphs), 0)

    def test_render_skills_groups(self):
        """Test rendering skills groups."""
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Languages", "items": ["Python", "Go"]},
            {"title": "Frameworks", "items": ["Django", "Flask"]},
        ]}
        renderer.render(Resume.from_dict(data))
        self.assertGreater(len(doc.paragraphs), 0)

    def test_normalize_group_items_strings(self):
        """A bare string becomes an item whose whole text is its name."""
        renderer, _ = self._get_renderer()
        items = ["Python", "JavaScript", "Go"]
        result = renderer._normalize_group_items(items, False, " — ")
        self.assertEqual([it.text for it in result], ["Python", "JavaScript", "Go"])
        self.assertEqual([it.name for it in result], ["Python", "JavaScript", "Go"])
        self.assertEqual([it.desc for it in result], ["", "", ""])

    def test_normalize_group_items_dicts(self):
        """The 'title' name alias and the 'description' desc alias both resolve.

        Also pins that the name/desc boundary survives normalization: the
        renderer bolds the name half, so a normalized item that kept only the
        joined string would leave it nothing to bold.
        """
        renderer, _ = self._get_renderer()
        items = Resume.from_dict(
            {
                "skills_groups": [
                    {
                        "title": "Group",
                        "items": [
                            {"name": "Python", "desc": "Expert"},
                            {"title": "Go", "description": "Intermediate"},
                        ],
                    }
                ]
            }
        ).skills_groups[0].items
        result = renderer._normalize_group_items(items, True, " — ")
        self.assertEqual(len(result), 2)
        self.assertEqual(
            [it.text for it in result], ["Python — Expert", "Go — Intermediate"]
        )
        self.assertEqual([it.name for it in result], ["Python", "Go"])
        self.assertEqual([it.desc for it in result], ["Expert", "Intermediate"])

    def test_render_skills_groups_respects_max_groups(self):
        """sec={"max_groups": N} caps the number of groups rendered.

        Asserted on which groups appear rather than on a paragraph count. The
        count was a proxy that only held while every group collapsed into a
        single joined paragraph; now that each item gets its own paragraph the
        count tracks items too, so it no longer isolates the cap.
        """
        renderer, doc = self._get_renderer()
        data = {"skills_groups": [
            {"title": "Group 1", "items": ["A", "B"]},
            {"title": "Group 2", "items": ["X", "Y"]},
            {"title": "Group 3", "items": ["1", "2"]},
        ]}
        renderer.render(Resume.from_dict(data), sec={"max_groups": 2})

        rendered = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("Group 1", rendered)
        self.assertIn("Group 2", rendered)
        self.assertNotIn("Group 3", rendered)


@mock_docx_modules
class TestExperienceSectionRenderer(unittest.TestCase):
    """Tests for ExperienceSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections_exp import ExperienceSectionRenderer
        return make_fake_renderer(ExperienceSectionRenderer)

    def test_render_experience(self):
        """Test rendering experience entries."""
        renderer, doc = self._get_renderer()
        data = {"experience": [
            {
                "title": "Senior Engineer",
                "company": "Tech Corp",
                "start": "2020",
                "end": "Present",
                "bullets": ["Led team of 5", "Shipped product"],
            }
        ]}
        renderer.render(Resume.from_dict(data))
        self.assertGreater(len(doc.paragraphs), 0)

    def test_format_date_span_start_end(self):
        """Test formatting date span with start and end."""
        renderer, _ = self._get_renderer()
        e = _entry({"start": "2020", "end": "2024"})
        result = renderer._format_date_span(e)
        self.assertEqual(result, "2020 – 2024")

    def test_format_date_span_start_only(self):
        """Test formatting date span with start only."""
        renderer, _ = self._get_renderer()
        e = _entry({"start": "2020"})
        result = renderer._format_date_span(e)
        self.assertEqual(result, "2020 – Present")

    def test_format_date_span_end_only(self):
        """Test formatting date span with end only."""
        renderer, _ = self._get_renderer()
        e = _entry({"end": "2024"})
        result = renderer._format_date_span(e)
        self.assertEqual(result, "2024")

    def test_format_date_span_no_dates(self):
        """No start or end yields an empty string."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer._format_date_span(_entry({})), "")

    def test_normalize_present(self):
        """Test normalizing present variants."""
        renderer, _ = self._get_renderer()
        self.assertEqual(renderer._normalize_present("present"), "Present")
        self.assertEqual(renderer._normalize_present("current"), "Present")
        self.assertEqual(renderer._normalize_present("now"), "Present")
        self.assertEqual(renderer._normalize_present("2024"), "2024")

    def test_calculate_bullet_limit_no_recency(self):
        """Test bullet limit without recency rules."""
        renderer, _ = self._get_renderer()
        result = renderer._calculate_bullet_limit(0, 10, 0, 5, 3)
        self.assertEqual(result, 10)

    def test_calculate_bullet_limit_recent_role(self):
        """Test bullet limit for recent roles."""
        renderer, _ = self._get_renderer()
        result = renderer._calculate_bullet_limit(0, 10, 2, 5, 3)
        self.assertEqual(result, 5)

    def test_calculate_bullet_limit_prior_role(self):
        """Test bullet limit for prior roles."""
        renderer, _ = self._get_renderer()
        result = renderer._calculate_bullet_limit(2, 10, 2, 5, 3)
        self.assertEqual(result, 3)

    def test_normalize_bullets_strings(self):
        """Test normalizing bullet strings."""
        renderer, _ = self._get_renderer()
        bullets = _bullets(["Point 1", "Point 2", "Point 3"])
        result = renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 3)

    def test_normalize_bullets_dicts(self):
        """Test normalizing bullet dicts."""
        renderer, _ = self._get_renderer()
        bullets = _bullets([{"text": "Point 1"}, {"line": "Point 2"}, {"name": "Point 3"}])
        result = renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 3)

    def test_normalize_bullets_limit(self):
        """Test bullet limit enforcement."""
        renderer, _ = self._get_renderer()
        bullets = _bullets(["Point 1", "Point 2", "Point 3", "Point 4", "Point 5"])
        result = renderer._normalize_bullets(bullets, 3)
        self.assertEqual(len(result), 3)

    def test_normalize_bullets_skips_empty(self):
        """Blank strings and empty-text dict bullets are dropped."""
        renderer, _ = self._get_renderer()
        bullets = _bullets(["Valid", "", {"text": ""}])
        result = renderer._normalize_bullets(bullets, 10)
        self.assertEqual(len(result), 1)


@mock_docx_modules
class TestEducationSectionRenderer(unittest.TestCase):
    """Tests for EducationSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections_exp import EducationSectionRenderer
        return make_fake_renderer(EducationSectionRenderer)

    def test_render_education(self):
        """Test rendering education entries."""
        renderer, doc = self._get_renderer()
        data = {"education": [
            {
                "degree": "B.S. Computer Science",
                "institution": "MIT",
                "year": "2020",
            },
            {
                "degree": "M.S. Data Science",
                "institution": "Stanford",
                "year": "2022",
            },
        ]}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(len(doc.paragraphs), 2)

    def test_render_education_empty(self):
        """Test rendering with no education."""
        renderer, doc = self._get_renderer()
        data = {"education": []}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(len(doc.paragraphs), 0)

    def test_render_education_partial_data(self):
        """An entry with only an institution (no degree/year) still renders."""
        renderer, doc = self._get_renderer()
        data = {"education": [{"institution": "Harvard"}]}
        renderer.render(Resume.from_dict(data))
        self.assertEqual(len(doc.paragraphs), 1)


@mock_docx_modules
class TestTechnologiesSectionRenderer(unittest.TestCase):
    """Tests for TechnologiesSectionRenderer."""

    def _get_renderer(self):
        from resume.docx_sections_skills import TechnologiesSectionRenderer
        return make_fake_renderer(TechnologiesSectionRenderer)

    def test_render_technologies(self):
        """Test rendering technologies."""
        renderer, doc = self._get_renderer()
        data = {"technologies": ["Docker", "Kubernetes", "AWS"]}
        renderer.render(Resume.from_dict(data))
        self.assertGreater(len(doc.paragraphs), 0)

    def test_collect_tech_items_list(self):
        """Test collecting tech items from list."""
        renderer, _ = self._get_renderer()
        data = {"technologies": ["Docker", "K8s"]}
        result = renderer._collect_tech_items(Resume.from_dict(data), None)
        self.assertEqual([it.text for it in result], ["Docker", "K8s"])

    def test_collect_tech_items_dicts(self):
        """Test collecting tech items from dicts."""
        renderer, _ = self._get_renderer()
        data = {"technologies": [
            {"name": "Docker"},
            {"title": "Kubernetes"},
        ]}
        result = renderer._collect_tech_items(Resume.from_dict(data), None)
        self.assertEqual(len(result), 2)

    def test_fallback_to_skills_groups(self):
        """Test fallback to skills_groups for tech items."""
        renderer, _ = self._get_renderer()
        data = {
            "technologies": [],
            "skills_groups": [
                {"title": "Technologies", "items": ["Docker", "K8s"]},
            ],
        }
        result = renderer._collect_tech_items(Resume.from_dict(data), None)
        self.assertEqual([it.text for it in result], ["Docker", "K8s"])

    def test_render_technologies_with_description(self):
        """sec={"show_desc": True} includes each item's desc in the rendered text.

        Technologies default show_desc=False (unlike skills groups, which default
        to True) so this behavior is otherwise untested.
        """
        renderer, doc = self._get_renderer()
        data = {"technologies": [{"name": "Docker", "desc": "Container platform"}]}
        renderer.render(Resume.from_dict(data), sec={"show_desc": True})
        texts = [r.text for p in doc.paragraphs for r in p.runs]
        self.assertTrue(any("Container platform" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
