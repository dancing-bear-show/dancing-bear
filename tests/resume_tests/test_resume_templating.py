"""Tests for resume/templating.py template loading and seed criteria parsing."""

import json
import os
import tempfile
import unittest

from resume.templating import (
    DEFAULT_TEMPLATE,
    load_template,
    parse_seed_criteria,
)


class TestDefaultTemplate(unittest.TestCase):
    """Tests for DEFAULT_TEMPLATE constant."""

    def test_default_template_has_sections(self):
        self.assertIn("sections", DEFAULT_TEMPLATE)
        self.assertIsInstance(DEFAULT_TEMPLATE["sections"], list)

    def test_default_template_sections_have_keys(self):
        for section in DEFAULT_TEMPLATE["sections"]:
            self.assertIn("key", section)
            self.assertIn("title", section)

    def test_default_template_includes_common_sections(self):
        keys = [s["key"] for s in DEFAULT_TEMPLATE["sections"]]
        self.assertIn("summary", keys)
        self.assertIn("skills", keys)
        self.assertIn("experience", keys)
        self.assertIn("education", keys)


class TestLoadTemplate(unittest.TestCase):
    """Tests for load_template function."""

    def test_load_template_returns_default_when_path_is_none(self):
        result = load_template(None)
        self.assertEqual(result, DEFAULT_TEMPLATE)

    def test_load_template_returns_default_when_path_is_empty(self):
        result = load_template("")
        self.assertEqual(result, DEFAULT_TEMPLATE)

    def test_load_template_from_yaml_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("sections:\n  - key: custom\n    title: Custom Section\n")
            f.flush()
            try:
                result = load_template(f.name)
                self.assertEqual(result["sections"][0]["key"], "custom")
                self.assertEqual(result["sections"][0]["title"], "Custom Section")
            finally:
                os.unlink(f.name)

    def test_load_template_from_json_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"sections": [{"key": "json_section", "title": "JSON"}]}, f)
            f.flush()
            try:
                result = load_template(f.name)
                self.assertEqual(result["sections"][0]["key"], "json_section")
            finally:
                os.unlink(f.name)


class TestParseSeedCriteria(unittest.TestCase):
    """Tests for parse_seed_criteria function."""

    def test_returns_empty_dict_when_seed_is_none(self):
        result = parse_seed_criteria(None)
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_seed_is_empty(self):
        result = parse_seed_criteria("")
        self.assertEqual(result, {})

    def test_returns_empty_dict_when_seed_is_whitespace(self):
        result = parse_seed_criteria("   ")
        self.assertEqual(result, {})

    def test_parses_json_object(self):
        seed = '{"role": "engineer", "level": "senior"}'
        result = parse_seed_criteria(seed)
        self.assertEqual(result["role"], "engineer")
        self.assertEqual(result["level"], "senior")

    def test_parses_json_with_whitespace(self):
        seed = '  {"role": "manager"}  '
        result = parse_seed_criteria(seed)
        self.assertEqual(result["role"], "manager")

    def test_returns_empty_dict_for_invalid_json(self):
        seed = '{invalid json}'
        result = parse_seed_criteria(seed)
        self.assertEqual(result, {})

    def test_parses_key_value_pairs(self):
        seed = "role=engineer, company=TechCorp"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["role"], "engineer")
        self.assertEqual(result["company"], "TechCorp")

    def test_parses_single_key_value(self):
        seed = "role=developer"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["role"], "developer")

    def test_trims_whitespace_in_key_value_pairs(self):
        seed = "  role = engineer , company = Corp  "
        result = parse_seed_criteria(seed)
        self.assertEqual(result["role"], "engineer")
        self.assertEqual(result["company"], "Corp")

    def test_skips_parts_without_equals(self):
        seed = "role=engineer, invalid, company=Corp"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["role"], "engineer")
        self.assertEqual(result["company"], "Corp")
        self.assertNotIn("invalid", result)

    def test_skips_empty_parts(self):
        seed = "role=engineer,, company=Corp"
        result = parse_seed_criteria(seed)
        self.assertEqual(len(result), 2)

    def test_parses_keywords_with_semicolon_separator(self):
        seed = "keywords=python;java;sql"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["keywords"], ["python", "java", "sql"])

    def test_parses_keywords_with_space_separator(self):
        seed = "keywords=python java sql"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["keywords"], ["python", "java", "sql"])

    def test_parses_keywords_strips_whitespace(self):
        seed = "keywords= python ; java ; sql "
        result = parse_seed_criteria(seed)
        self.assertEqual(result["keywords"], ["python", "java", "sql"])

    def test_parses_keywords_skips_empty_items(self):
        seed = "keywords=python;;java"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["keywords"], ["python", "java"])

    def test_mixed_criteria(self):
        seed = "role=engineer, keywords=python;aws, level=senior"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["role"], "engineer")
        self.assertEqual(result["level"], "senior")
        self.assertEqual(result["keywords"], ["python", "aws"])

    def test_handles_equals_in_value(self):
        # split("=", 1) preserves the rest of the string after the first "="
        seed = "query=x=y"
        result = parse_seed_criteria(seed)
        self.assertEqual(result["query"], "x=y")


if __name__ == "__main__":
    unittest.main()
