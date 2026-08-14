"""Tests for core/agentic.py uncovered branches."""

from __future__ import annotations

import argparse
import unittest

from core.agentic import (
    section,
    build_capsule,
    build_cli_tree,
    build_domain_map,
    cli_path_exists,
    list_subcommands,
    tree_and_flow_sections,
)


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


class TestTreeAndFlowSections(unittest.TestCase):
    def test_both_present_keeps_order(self):
        self.assertEqual(
            tree_and_flow_sections("- cmd", "- flow"),
            [("CLI Tree", "- cmd"), ("Flow Map", "- flow")],
        )

    def test_empty_tree_is_dropped(self):
        self.assertEqual(
            tree_and_flow_sections("", "- flow"),
            [("Flow Map", "- flow")],
        )

    def test_empty_flow_is_dropped(self):
        self.assertEqual(
            tree_and_flow_sections("- cmd", ""),
            [("CLI Tree", "- cmd")],
        )

    def test_both_empty_returns_empty_list(self):
        self.assertEqual(tree_and_flow_sections("", ""), [])


class TestTreeAndFlowSectionsSadPaths(unittest.TestCase):
    def test_whitespace_only_body_is_kept_here_but_dropped_by_section(self):
        # tree_and_flow_sections filters on falsiness, so "   " survives it;
        # section() is what strips it. Pinning the division of labour so a
        # future "optimization" cannot drop one of the two filters.
        pairs = tree_and_flow_sections("   ", "")
        self.assertEqual(pairs, [("CLI Tree", "   ")])
        self.assertEqual(section(*pairs[0]), "")

    def test_none_bodies_are_dropped(self):
        self.assertEqual(tree_and_flow_sections(None, None), [])  # NOSONAR - defensive None input

    def test_returns_a_fresh_list_each_call(self):
        # Callers append to the result (build_capsule consumes it); a shared
        # or cached list would accumulate sections across domains.
        first = tree_and_flow_sections("- cmd", "- flow")
        first.append(("Extra", "x"))
        second = tree_and_flow_sections("- cmd", "- flow")
        self.assertEqual(len(second), 2)


class TestBuildDomainMap(unittest.TestCase):
    def test_renders_top_level_and_both_sections(self):
        result = build_domain_map("Top-Level\n- a.py", "- cmd", "- flow")
        self.assertIn("Top-Level", result)
        self.assertIn("== CLI Tree ==", result)
        self.assertIn("== Flow Map ==", result)
        self.assertLess(result.index("CLI Tree"), result.index("Flow Map"))

    def test_omits_empty_sections(self):
        result = build_domain_map("Top-Level\n- a.py", "", "")
        self.assertEqual(result, "Top-Level\n- a.py")

    def test_top_level_only_with_flow(self):
        result = build_domain_map("Top-Level", "", "- flow")
        self.assertIn("== Flow Map ==", result)
        self.assertNotIn("CLI Tree", result)

    def test_matches_manual_section_composition(self):
        # The helper must stay equivalent to the hand-rolled shape it replaced.
        top, tree, flow = "Top-Level\n- a.py", "- cmd", "- flow"
        expected = "\n".join(
            s for s in [top, section("CLI Tree", tree), section("Flow Map", flow)] if s
        )
        self.assertEqual(build_domain_map(top, tree, flow), expected)

    def test_whitespace_only_sections_are_stripped(self):
        result = build_domain_map("Top-Level", "   ", "\n\t ")
        self.assertEqual(result, "Top-Level")

    def test_empty_top_level_still_renders_sections(self):
        result = build_domain_map("", "- cmd", "")
        self.assertIn("== CLI Tree ==", result)
        self.assertFalse(result.startswith("\n"))

    def test_whitespace_only_top_level_is_dropped(self):
        # Held to the same standard build_capsule applies to section bodies:
        # blank-or-whitespace contributes nothing rather than a leading blank
        # line. Pins the fix for the PR #215 review finding.
        self.assertEqual(build_domain_map("   ", "", ""), "")
        self.assertFalse(build_domain_map("  \n\t ", "- cmd", "").startswith("\n"))

    def test_none_top_level_is_tolerated(self):
        self.assertEqual(build_domain_map(None, "", ""), "")  # NOSONAR - defensive None input
        self.assertIn("== CLI Tree ==", build_domain_map(None, "- cmd", ""))  # NOSONAR

    def test_all_empty_returns_empty_string(self):
        self.assertEqual(build_domain_map("", "", ""), "")

    def test_multiline_bodies_are_preserved_verbatim(self):
        tree = "- a: x, y\n- b: z"
        result = build_domain_map("Top-Level", tree, "")
        self.assertIn(tree, result)


if __name__ == "__main__":
    unittest.main()
