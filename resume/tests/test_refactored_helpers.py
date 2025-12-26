"""Tests for refactored helper functions extracted during complexity reduction."""
import unittest
from pathlib import Path
import tempfile
import shutil

from resume import parsing
from resume.priority import _filter_items, _filter_skills_groups, _filter_experience
from resume.skills_filter import _extract_item_name
from resume.overlays import (
    _try_load_from_paths,
    _get_overlay_paths,
    _load_list_overlay,
    _apply_profile_config,
)


class TestSplitDateRange(unittest.TestCase):
    """Tests for _split_date_range helper in parsing.py."""

    def test_split_with_dash(self):
        start, end = parsing._split_date_range("2020 - 2023")
        self.assertEqual(start, "2020")
        self.assertEqual(end, "2023")

    def test_split_with_en_dash(self):
        start, end = parsing._split_date_range("Jan 2020 – Dec 2023")
        self.assertEqual(start, "Jan 2020")
        self.assertEqual(end, "Dec 2023")

    def test_split_with_present(self):
        start, end = parsing._split_date_range("2020 - Present")
        self.assertEqual(start, "2020")
        self.assertEqual(end, "Present")

    def test_no_separator_returns_empty(self):
        start, end = parsing._split_date_range("2020")
        self.assertEqual(start, "")
        self.assertEqual(end, "")

    def test_empty_string(self):
        start, end = parsing._split_date_range("")
        self.assertEqual(start, "")
        self.assertEqual(end, "")


class TestFilterSummaryLines(unittest.TestCase):
    """Tests for _filter_summary_lines helper in parsing.py."""

    def test_filters_email_lines(self):
        lines = ["Some intro", "contact@example.com", "More text"]
        result = parsing._filter_summary_lines(lines)
        self.assertEqual(result, ["Some intro", "More text"])

    def test_filters_phone_lines(self):
        lines = ["Some intro", "+1 (555) 123-4567", "More text"]
        result = parsing._filter_summary_lines(lines)
        self.assertEqual(result, ["Some intro", "More text"])

    def test_filters_bullet_lines(self):
        lines = ["Some intro", "• Bullet point", "More text"]
        result = parsing._filter_summary_lines(lines)
        self.assertEqual(result, ["Some intro", "More text"])

    def test_strips_profile_prefix(self):
        lines = ["Profile: Experienced engineer"]
        result = parsing._filter_summary_lines(lines)
        self.assertEqual(result, ["Experienced engineer"])

    def test_skips_empty_profile_line(self):
        lines = ["Profile:", "Next line"]
        result = parsing._filter_summary_lines(lines)
        self.assertEqual(result, ["Next line"])


class TestExtractItemName(unittest.TestCase):
    """Tests for _extract_item_name helper in skills_filter.py."""

    def test_extract_from_dict_with_skill(self):
        item = {"skill": "Python", "weight": 2}
        self.assertEqual(_extract_item_name(item), "Python")

    def test_extract_from_dict_with_name(self):
        item = {"name": "AWS", "category": "cloud"}
        self.assertEqual(_extract_item_name(item), "AWS")

    def test_extract_from_string(self):
        self.assertEqual(_extract_item_name("Docker"), "Docker")

    def test_returns_none_for_empty_dict(self):
        self.assertIsNone(_extract_item_name({}))

    def test_returns_none_for_none(self):
        self.assertIsNone(_extract_item_name(None))

    def test_returns_none_for_number(self):
        self.assertIsNone(_extract_item_name(123))


class TestFilterItems(unittest.TestCase):
    """Tests for _filter_items helper in priority.py."""

    def test_filters_by_priority(self):
        items = [
            {"name": "High", "priority": 0.9},
            {"name": "Low", "priority": 0.3},
            {"name": "Medium", "priority": 0.6},
        ]
        result = _filter_items(items, 0.5)
        names = [i["name"] for i in result]
        self.assertEqual(names, ["High", "Medium"])

    def test_uses_usefulness_as_fallback(self):
        items = [
            {"name": "High", "usefulness": 0.9},
            {"name": "Low", "usefulness": 0.3},
        ]
        result = _filter_items(items, 0.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "High")

    def test_strings_kept_at_default_cutoff(self):
        items = ["Python", "AWS"]
        result = _filter_items(items, 1.0)
        self.assertEqual(result, ["Python", "AWS"])

    def test_strings_filtered_above_default(self):
        items = ["Python", "AWS"]
        result = _filter_items(items, 1.5)
        self.assertEqual(result, [])

    def test_empty_list(self):
        self.assertEqual(_filter_items([], 0.5), [])

    def test_none_list(self):
        self.assertEqual(_filter_items(None, 0.5), [])


class TestFilterSkillsGroups(unittest.TestCase):
    """Tests for _filter_skills_groups helper in priority.py."""

    def test_filters_group_items(self):
        groups = [
            {
                "title": "Languages",
                "items": [
                    {"name": "Python", "priority": 0.9},
                    {"name": "COBOL", "priority": 0.2},
                ],
            }
        ]
        result = _filter_skills_groups(groups, 0.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(len(result[0]["items"]), 1)
        self.assertEqual(result[0]["items"][0]["name"], "Python")

    def test_removes_empty_groups(self):
        groups = [
            {"title": "Old", "items": [{"name": "COBOL", "priority": 0.1}]},
            {"title": "New", "items": [{"name": "Python", "priority": 0.9}]},
        ]
        result = _filter_skills_groups(groups, 0.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "New")

    def test_preserves_non_list_items(self):
        groups = [{"title": "Special", "items": "not a list"}]
        result = _filter_skills_groups(groups, 0.5)
        self.assertEqual(result, groups)


class TestFilterExperience(unittest.TestCase):
    """Tests for _filter_experience helper in priority.py."""

    def test_filters_roles_by_priority(self):
        exp = [
            {"title": "Senior", "priority": 0.9, "bullets": []},
            {"title": "Intern", "priority": 0.2, "bullets": []},
        ]
        result = _filter_experience(exp, 0.5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Senior")

    def test_filters_bullets_within_role(self):
        exp = [
            {
                "title": "Engineer",
                "bullets": [
                    {"text": "Important", "priority": 0.9},
                    {"text": "Minor", "priority": 0.2},
                ],
            }
        ]
        result = _filter_experience(exp, 0.5)
        self.assertEqual(len(result[0]["bullets"]), 1)

    def test_skips_non_dict_entries(self):
        exp = [{"title": "Valid"}, "invalid", None]
        result = _filter_experience(exp, 0.5)
        self.assertEqual(len(result), 1)


class TestOverlayHelpers(unittest.TestCase):
    """Tests for overlay helper functions."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_try_load_from_paths_first_exists(self):
        path1 = self.temp_dir / "first.yaml"
        path1.write_text("key: value1\n")
        path2 = self.temp_dir / "second.yaml"
        path2.write_text("key: value2\n")

        result = _try_load_from_paths((path1, path2))
        self.assertEqual(result, {"key": "value1"})

    def test_try_load_from_paths_second_exists(self):
        path1 = self.temp_dir / "missing.yaml"
        path2 = self.temp_dir / "exists.yaml"
        path2.write_text("key: found\n")

        result = _try_load_from_paths((path1, path2))
        self.assertEqual(result, {"key": "found"})

    def test_try_load_from_paths_none_exist(self):
        path1 = self.temp_dir / "missing1.yaml"
        path2 = self.temp_dir / "missing2.yaml"

        result = _try_load_from_paths((path1, path2))
        self.assertIsNone(result)

    def test_get_overlay_paths(self):
        prof_dir = Path("config/profiles/myprof")
        cfg_dir = Path("config")
        new_path, old_path = _get_overlay_paths(prof_dir, cfg_dir, "myprof", "skills")
        self.assertEqual(new_path, Path("config/profiles/myprof/skills.yaml"))
        self.assertEqual(old_path, Path("config/skills.myprof.yaml"))

    def test_load_list_overlay_dict_format(self):
        prof_dir = self.temp_dir / "profiles" / "test"
        prof_dir.mkdir(parents=True)
        (prof_dir / "interests.yaml").write_text("interests:\n  - Reading\n  - Coding\n")

        result = _load_list_overlay(prof_dir, self.temp_dir, "test", "interests")
        self.assertEqual(result, ["Reading", "Coding"])

    def test_load_list_overlay_list_format(self):
        prof_dir = self.temp_dir / "profiles" / "test"
        prof_dir.mkdir(parents=True)
        (prof_dir / "hobbies.yaml").write_text("- Gaming\n- Music\n")

        result = _load_list_overlay(prof_dir, self.temp_dir, "test", "hobbies")
        self.assertEqual(result, ["Gaming", "Music"])

    def test_load_list_overlay_not_found(self):
        prof_dir = self.temp_dir / "profiles" / "test"
        result = _load_list_overlay(prof_dir, self.temp_dir, "test", "missing")
        self.assertIsNone(result)


class TestApplyProfileConfig(unittest.TestCase):
    """Tests for _apply_profile_config helper in overlays.py."""

    def test_applies_top_level_fields(self):
        out = {}
        prof_data = {"name": "John Doe", "headline": "Engineer"}
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["name"], "John Doe")
        self.assertEqual(out["headline"], "Engineer")

    def test_applies_nested_contact(self):
        out = {}
        prof_data = {
            "contact": {
                "email": "john@example.com",
                "phone": "555-1234",
                "links": ["https://github.com/john"],
            }
        }
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["email"], "john@example.com")
        self.assertEqual(out["phone"], "555-1234")
        self.assertEqual(out["links"], ["https://github.com/john"])

    def test_does_not_override_existing_contact(self):
        out = {"email": "existing@example.com"}
        prof_data = {"contact": {"email": "new@example.com"}}
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["email"], "existing@example.com")

    def test_applies_lists(self):
        out = {}
        prof_data = {"interests": ["Reading", "Hiking"], "presentations": ["Talk 1"]}
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["interests"], ["Reading", "Hiking"])
        self.assertEqual(out["presentations"], ["Talk 1"])


class TestPdfHelpers(unittest.TestCase):
    """Tests for PDF parsing helper functions."""

    def test_pdf_extract_name_headline(self):
        lines = ["John Doe", "Senior Software Engineer", "john@example.com"]
        name, headline = parsing._pdf_extract_name_headline(lines)
        self.assertEqual(name, "John Doe")
        self.assertEqual(headline, "Senior Software Engineer")

    def test_pdf_extract_name_only(self):
        lines = ["John Doe"]
        name, headline = parsing._pdf_extract_name_headline(lines)
        self.assertEqual(name, "John Doe")
        self.assertEqual(headline, "")

    def test_pdf_extract_empty_lines(self):
        name, headline = parsing._pdf_extract_name_headline([])
        self.assertEqual(name, "")
        self.assertEqual(headline, "")

    def test_pdf_extract_skips_section_heading(self):
        lines = ["EXPERIENCE", "Some text"]
        name, headline = parsing._pdf_extract_name_headline(lines)
        self.assertEqual(name, "")

    def test_pdf_find_sections(self):
        lines = ["John Doe", "EXPERIENCE", "Role 1", "EDUCATION", "Degree"]
        indices, sorted_sections = parsing._pdf_find_sections(lines)
        self.assertIn("experience", indices)
        self.assertIn("education", indices)
        self.assertEqual(indices["experience"], 1)
        self.assertEqual(indices["education"], 3)

    def test_pdf_get_section_lines(self):
        lines = ["Intro", "SKILLS", "Python", "AWS", "EXPERIENCE", "Role"]
        indices, sorted_sections = parsing._pdf_find_sections(lines)
        skills = parsing._pdf_get_section_lines("skills", lines, indices, sorted_sections)
        self.assertEqual(skills, ["Python", "AWS"])

    def test_pdf_extract_experience(self):
        exp_lines = [
            "Staff Engineer | TechCorp | 2020 - Present",
            "- Built systems",
            "- Led team",
        ]
        result = parsing._pdf_extract_experience(exp_lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Staff Engineer")
        self.assertEqual(result[0]["company"], "TechCorp")
        self.assertEqual(result[0]["start"], "2020")
        self.assertEqual(len(result[0]["bullets"]), 2)

    def test_pdf_extract_education(self):
        edu_lines = [
            "B.S. Computer Science at MIT (2015)",
            "Some other text",
        ]
        result = parsing._pdf_extract_education(edu_lines)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["degree"], "B.S. Computer Science")


if __name__ == "__main__":
    unittest.main(verbosity=2)
