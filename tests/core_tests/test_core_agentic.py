"""Tests for core/agentic.py uncovered branches."""

from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

from core.agentic import (
    read_text,
    section,
    build_capsule,
    build_cli_tree,
    cli_path_exists,
    list_subcommands,
)


class TestReadText(unittest.TestCase):
    def test_reads_existing_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            path.write_text("hello world", encoding="utf-8")
            result = read_text(path)
        self.assertEqual(result, "hello world")

    def test_returns_empty_for_missing_file(self):
        path = Path("/nonexistent/path/file.txt")
        result = read_text(path)
        self.assertEqual(result, "")

    def test_returns_empty_for_unreadable_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "test.txt"
            # Use a directory path to force a read error
            path.mkdir()
            result = read_text(path)
        self.assertEqual(result, "")


class TestSection(unittest.TestCase):
    def test_empty_body_returns_empty(self):
        result = section("Title", "")
        self.assertEqual(result, "")

    def test_whitespace_body_returns_empty(self):
        result = section("Title", "   \n  ")
        self.assertEqual(result, "")

    def test_none_body_returns_empty(self):
        result = section("Title", None)  # NOSONAR - intentional None test for defensive handling
        self.assertEqual(result, "")

    def test_non_empty_body_renders_section(self):
        result = section("Overview", "This is the body.")
        self.assertIn("== Overview ==", result)
        self.assertIn("This is the body.", result)

    def test_section_format(self):
        result = section("Commands", "list\ncreate")
        self.assertTrue(result.startswith("== Commands =="))


class TestBuildCapsule(unittest.TestCase):
    def test_basic_capsule(self):
        result = build_capsule(
            app_id="myapp",
            purpose="Do something useful",
            commands=["list", "create", "delete"],
            sections=[("Overview", "High-level description"), ("Notes", "Extra info")],
        )
        self.assertIn("agentic: myapp", result)
        self.assertIn("purpose: Do something useful", result)
        self.assertIn("  - list", result)
        self.assertIn("  - create", result)
        self.assertIn("  - delete", result)
        self.assertIn("== Overview ==", result)
        self.assertIn("High-level description", result)
        self.assertIn("== Notes ==", result)

    def test_empty_section_excluded(self):
        result = build_capsule(
            app_id="myapp",
            purpose="Test",
            commands=["list"],
            sections=[("EmptySection", ""), ("RealSection", "Content here")],
        )
        self.assertNotIn("== EmptySection ==", result)
        self.assertIn("== RealSection ==", result)

    def test_no_commands(self):
        result = build_capsule(
            app_id="myapp",
            purpose="Test",
            commands=[],
            sections=[],
        )
        self.assertIn("agentic: myapp", result)
        self.assertIn("purpose: Test", result)


class TestBuildCliTree(unittest.TestCase):
    def _make_parser_with_subs(self, sub_names):
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="cmd")
        for name in sub_names:
            subs.add_parser(name)
        return parser

    def test_none_parser_returns_empty(self):
        result = build_cli_tree(None)
        self.assertEqual(result, "")

    def test_parser_without_subparsers_returns_empty(self):
        parser = argparse.ArgumentParser()
        result = build_cli_tree(parser)
        self.assertEqual(result, "")

    def test_parser_with_subcommands(self):
        parser = self._make_parser_with_subs(["list", "create", "delete"])
        result = build_cli_tree(parser)
        self.assertIn("- list", result)
        self.assertIn("- create", result)
        self.assertIn("- delete", result)

    def test_parser_with_nested_subcommands(self):
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="cmd")
        sub = subs.add_parser("mail")
        sub_subs = sub.add_subparsers(dest="subcmd")
        sub_subs.add_parser("list")
        sub_subs.add_parser("send")

        result = build_cli_tree(parser, depth=2)
        self.assertIn("- mail", result)
        self.assertIn("list", result)
        self.assertIn("send", result)

    def test_depth_1_no_children(self):
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="cmd")
        sub = subs.add_parser("mail")
        sub_subs = sub.add_subparsers(dest="subcmd")
        sub_subs.add_parser("list")

        result = build_cli_tree(parser, depth=1)
        self.assertIn("- mail", result)
        # With depth=1, children not included inline
        self.assertNotIn("list", result)


class TestCliPathExists(unittest.TestCase):
    def _make_nested_parser(self):
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="cmd")
        mail = subs.add_parser("mail")
        mail_subs = mail.add_subparsers(dest="subcmd")
        mail_subs.add_parser("list")
        mail_subs.add_parser("send")
        subs.add_parser("calendar")
        return parser

    def test_none_parser_returns_false(self):
        self.assertFalse(cli_path_exists(None, ["mail"]))

    def test_top_level_path_exists(self):
        parser = self._make_nested_parser()
        self.assertTrue(cli_path_exists(parser, ["mail"]))

    def test_nested_path_exists(self):
        parser = self._make_nested_parser()
        self.assertTrue(cli_path_exists(parser, ["mail", "list"]))

    def test_missing_top_level(self):
        parser = self._make_nested_parser()
        self.assertFalse(cli_path_exists(parser, ["nonexistent"]))

    def test_missing_nested(self):
        parser = self._make_nested_parser()
        self.assertFalse(cli_path_exists(parser, ["mail", "nonexistent"]))

    def test_empty_path(self):
        parser = self._make_nested_parser()
        self.assertTrue(cli_path_exists(parser, []))

    def test_too_deep_path(self):
        parser = self._make_nested_parser()
        self.assertFalse(cli_path_exists(parser, ["mail", "list", "extra"]))

    def test_no_subparsers_on_intermediate(self):
        parser = self._make_nested_parser()
        # "calendar" has no subparsers
        self.assertFalse(cli_path_exists(parser, ["calendar", "list"]))


class TestListSubcommands(unittest.TestCase):
    def test_none_parser_returns_empty(self):
        result = list_subcommands(None)
        self.assertEqual(result, [])

    def test_parser_without_subparsers(self):
        parser = argparse.ArgumentParser()
        result = list_subcommands(parser)
        self.assertEqual(result, [])

    def test_returns_sorted_subcommands(self):
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers()
        subs.add_parser("zebra")
        subs.add_parser("apple")
        subs.add_parser("mango")
        result = list_subcommands(parser)
        self.assertEqual(result, ["apple", "mango", "zebra"])


if __name__ == "__main__":
    unittest.main()
