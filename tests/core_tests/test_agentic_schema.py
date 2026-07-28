"""Tests for core/agentic_schema.py — auto-derived CLI schema engine."""
from __future__ import annotations

import argparse
import json
import unittest

from core.agentic_schema import (
    build_schema_json,
    build_schema_yaml,
    _extract_options,
    _hoist_inherited_options,
    _yaml_scalar,
    _needs_quoting,
)


def _make_parser_with_subs() -> argparse.ArgumentParser:
    """Build a small 2-level parser for tests."""
    parser = argparse.ArgumentParser(prog="test-cli", description="Test CLI")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    subs = parser.add_subparsers(dest="command", metavar="<command>")

    labels_p = subs.add_parser("labels", help="Label commands")
    labels_subs = labels_p.add_subparsers(dest="labels_cmd")
    export_p = labels_subs.add_parser("export", help="Export labels")
    export_p.add_argument("--out", help="Output file")
    export_p.add_argument("--format", choices=["yaml", "json"], default="yaml")
    sync_p = labels_subs.add_parser("sync", help="Sync labels")
    sync_p.add_argument("--dry-run", action="store_true", help="Preview changes")
    sync_p.add_argument("--format", choices=["yaml", "json"], default="yaml")

    subs.add_parser("status", help="Show status")

    return parser


class TestExtractOptions(unittest.TestCase):
    def test_extracts_flag_options(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--verbose", "-v", action="store_true", help="Be verbose")
        parser.add_argument("--output", choices=["text", "json"])
        opts = _extract_options(parser)
        names = [o["name"] for o in opts]
        self.assertIn("verbose", names)
        self.assertIn("output", names)

    def test_skips_help_action(self):
        parser = argparse.ArgumentParser()
        opts = _extract_options(parser)
        names = [o["name"] for o in opts]
        self.assertNotIn("help", names)

    def test_skips_positional(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("filename")
        opts = _extract_options(parser)
        names = [o["name"] for o in opts]
        self.assertNotIn("filename", names)

    def test_type_name_extraction(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--count", type=int, help="Count")
        opts = _extract_options(parser)
        count_opt = next(o for o in opts if o["name"] == "count")
        self.assertEqual(count_opt["type"], "int")

    def test_choices_included(self):
        parser = argparse.ArgumentParser()
        parser.add_argument("--fmt", choices=["yaml", "json"])
        opts = _extract_options(parser)
        fmt_opt = next(o for o in opts if o["name"] == "fmt")
        self.assertEqual(sorted(fmt_opt["choices"]), ["json", "yaml"])


class TestBuildSchemaJson(unittest.TestCase):
    def setUp(self):
        self.parser = _make_parser_with_subs()

    def test_returns_dict(self):
        schema = build_schema_json(self.parser)
        self.assertIsInstance(schema, dict)

    def test_prog_present(self):
        schema = build_schema_json(self.parser)
        self.assertEqual(schema["prog"], "test-cli")

    def test_description_present(self):
        schema = build_schema_json(self.parser)
        self.assertIn("description", schema)

    def test_top_level_options_present(self):
        schema = build_schema_json(self.parser)
        names = [o["name"] for o in schema["options"]]
        self.assertIn("verbose", names)

    def test_subcommands_present(self):
        schema = build_schema_json(self.parser)
        subcmd_names = [s["name"] for s in schema["subcommands"]]
        self.assertIn("labels", subcmd_names)
        self.assertIn("status", subcmd_names)

    def test_nested_subcommands(self):
        schema = build_schema_json(self.parser)
        labels = next(s for s in schema["subcommands"] if s["name"] == "labels")
        child_names = [s["name"] for s in labels["subcommands"]]
        self.assertIn("export", child_names)
        self.assertIn("sync", child_names)

    def test_leaf_options_present(self):
        schema = build_schema_json(self.parser)
        labels = next(s for s in schema["subcommands"] if s["name"] == "labels")
        export = next(s for s in labels["subcommands"] if s["name"] == "export")
        names = [o["name"] for o in export["options"]]
        self.assertIn("out", names)
        self.assertIn("format", names)

    def test_compact_strips_help(self):
        schema = build_schema_json(self.parser, compact=True)
        # help field should be absent from options
        for opt in schema["options"]:
            self.assertNotIn("help", opt)

    def test_compact_strips_usage_epilog(self):
        schema = build_schema_json(self.parser, compact=True)
        self.assertNotIn("usage", schema)
        self.assertNotIn("epilog", schema)

    def test_compact_hoists_common_options(self):
        # Build a parser where ALL leaves share a common option
        # (the _make_parser_with_subs includes 'status' with no options, so intersection is empty)
        parser = argparse.ArgumentParser(prog="mini", description="Mini")
        subs = parser.add_subparsers(dest="cmd")
        for name in ("a", "b"):
            sub = subs.add_parser(name)
            sub.add_argument("--format", choices=["yaml", "json"])
        schema = build_schema_json(parser, compact=True)
        self.assertIn("inherited_options", schema)
        self.assertIn("format", schema["inherited_options"])

    def test_domain_filter(self):
        schema = build_schema_json(self.parser, domain="labels")
        subcmd_names = [s["name"] for s in schema["subcommands"]]
        self.assertIn("labels", subcmd_names)
        self.assertNotIn("status", subcmd_names)

    def test_domain_filter_no_match(self):
        schema = build_schema_json(self.parser, domain="nonexistent")
        self.assertEqual(schema["subcommands"], [])

    def test_ultra_remaps_keys(self):
        schema = build_schema_json(self.parser, ultra=True)
        # ultra mode maps "prog" -> "p"
        self.assertIn("p", schema)
        self.assertNotIn("prog", schema)

    def test_json_serializable(self):
        schema = build_schema_json(self.parser)
        # Should not raise
        result = json.dumps(schema)
        self.assertIsInstance(result, str)


class TestBuildSchemaYaml(unittest.TestCase):
    def setUp(self):
        self.parser = _make_parser_with_subs()

    def test_returns_string(self):
        result = build_schema_yaml(self.parser)
        self.assertIsInstance(result, str)

    def test_contains_prog(self):
        result = build_schema_yaml(self.parser)
        self.assertIn("test-cli", result)

    def test_contains_subcommand_names(self):
        result = build_schema_yaml(self.parser)
        self.assertIn("labels", result)
        self.assertIn("status", result)

    def test_compact_yaml(self):
        result = build_schema_yaml(self.parser, compact=True)
        self.assertIsInstance(result, str)
        self.assertIn("labels", result)


class TestYamlEmitter(unittest.TestCase):
    def test_scalar_none(self):
        self.assertEqual(_yaml_scalar(None), "null")

    def test_scalar_bool_true(self):
        self.assertEqual(_yaml_scalar(True), "true")

    def test_scalar_bool_false(self):
        self.assertEqual(_yaml_scalar(False), "false")

    def test_scalar_int(self):
        self.assertEqual(_yaml_scalar(42), "42")

    def test_scalar_plain_string(self):
        self.assertEqual(_yaml_scalar("hello"), "hello")

    def test_scalar_reserved_word(self):
        result = _yaml_scalar("true")
        self.assertTrue(result.startswith("'"))

    def test_scalar_empty_string(self):
        result = _yaml_scalar("")
        self.assertTrue(result.startswith("'"))

    def test_needs_quoting_colon(self):
        self.assertTrue(_needs_quoting("key: value"))

    def test_needs_quoting_hash(self):
        self.assertTrue(_needs_quoting("abc # comment"))

    def test_no_quoting_needed_plain(self):
        self.assertFalse(_needs_quoting("hello"))

    def test_needs_quoting_leading_space(self):
        self.assertTrue(_needs_quoting(" leading"))


class TestHoistInheritedOptions(unittest.TestCase):
    def test_hoists_common_leaf_options(self):
        node = {
            "prog": "root",
            "options": [],
            "subcommands": [
                {
                    "name": "a",
                    "prog": "root a",
                    "options": [
                        {"name": "fmt", "flags": ["--format"]},
                        {"name": "x", "flags": ["--x"]},
                    ],
                    "subcommands": [],
                },
                {
                    "name": "b",
                    "prog": "root b",
                    "options": [
                        {"name": "fmt", "flags": ["--format"]},
                    ],
                    "subcommands": [],
                },
            ],
        }
        hoisted = _hoist_inherited_options(node)
        self.assertIn("fmt", hoisted)
        # Should be removed from leaves
        a_opts = [o["name"] for o in node["subcommands"][0]["options"]]
        self.assertNotIn("fmt", a_opts)
        # x is not common — stays
        self.assertIn("x", a_opts)

    def test_no_common_options_returns_empty(self):
        node = {
            "prog": "root",
            "options": [],
            "subcommands": [
                {"name": "a", "prog": "a", "options": [{"name": "x", "flags": []}], "subcommands": []},
                {"name": "b", "prog": "b", "options": [{"name": "y", "flags": []}], "subcommands": []},
            ],
        }
        hoisted = _hoist_inherited_options(node)
        self.assertEqual(hoisted, [])


if __name__ == "__main__":
    unittest.main()
