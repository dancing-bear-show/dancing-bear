"""Tests for desk/agentic.py capsule builders."""

import unittest
from unittest.mock import patch

from tests.fixtures import capture_stdout


class TestEmitAgenticContext(unittest.TestCase):
    def test_returns_0(self):
        from desk.agentic import emit_agentic_context
        with capture_stdout():
            rc = emit_agentic_context()
        self.assertEqual(rc, 0)

    def test_compact_returns_0(self):
        from desk.agentic import emit_agentic_context
        with capture_stdout():
            rc = emit_agentic_context("text", True)
        self.assertEqual(rc, 0)

    def test_accepts_fmt_and_compact_positionally(self):
        """Signature must match the (fmt, compact) contract CLIApp calls with.

        Previously desk/maker took (compact) only, so callers relied on
        BaseAssistant's blind `except TypeError: emit_func()` retry.
        """
        from desk.agentic import emit_agentic_context
        for fmt in ("text", "yaml", "json"):
            with capture_stdout():
                self.assertEqual(emit_agentic_context(fmt, False), 0)

    def test_prints_agentic_content(self):
        from desk.agentic import emit_agentic_context
        with capture_stdout() as buf:
            emit_agentic_context()
        output = buf.getvalue()
        self.assertIn("agentic: desk", output)


class TestBuildAgenticCapsule(unittest.TestCase):
    def test_contains_app_id(self):
        from desk.agentic import build_agentic_capsule
        result = build_agentic_capsule()
        self.assertIn("agentic: desk", result)

    def test_contains_commands(self):
        from desk.agentic import build_agentic_capsule
        result = build_agentic_capsule()
        self.assertIn("scan", result)
        self.assertIn("plan", result)
        self.assertIn("apply", result)

    def test_contains_purpose(self):
        from desk.agentic import build_agentic_capsule
        result = build_agentic_capsule()
        self.assertIn("macOS", result)

    def test_includes_commands_in_output(self):
        from desk.agentic import build_agentic_capsule
        result = build_agentic_capsule()
        # Commands are always included regardless of CLI parser availability.
        # desk ships no bin/ wrapper — `./bin/desk-assistant` never existed, so
        # the capsule advertises the form that actually runs.
        self.assertIn("python3 -m desk", result)


class TestBuildDomainMap(unittest.TestCase):
    def test_returns_string(self):
        from desk.agentic import build_domain_map
        result = build_domain_map()
        self.assertIsInstance(result, str)

    def test_contains_top_level_files(self):
        from desk.agentic import build_domain_map
        result = build_domain_map()
        self.assertIn("desk/scan.py", result)
        self.assertIn("desk/planner.py", result)

    def test_contains_expected_top_level_entries(self):
        from desk.agentic import build_domain_map
        result = build_domain_map()
        # Top-level section is always present
        self.assertIn("Top-Level", result)


class TestFlowMap(unittest.TestCase):
    def test_flow_map_returns_string(self):
        from desk.agentic import _flow_map
        result = _flow_map()
        self.assertIsInstance(result, str)

    def test_flow_map_empty_when_parser_none(self):
        # desk.cli has no build_parser(), so _get_parser() returns None and
        # _cli_path_exists always returns False → flow map is empty by default
        from desk.agentic import _flow_map
        with patch("desk.agentic._cli_path_exists", return_value=False):
            result = _flow_map()
        self.assertEqual(result, "")

    def test_flow_map_includes_scan_when_path_exists(self):
        from desk.agentic import _flow_map

        def path_check(path):
            return path == ["scan"]

        with patch("desk.agentic._cli_path_exists", side_effect=path_check):
            result = _flow_map()
        self.assertIn("scan", result)

    def test_flow_map_includes_all_commands_when_all_paths_exist(self):
        from desk.agentic import _flow_map

        with patch("desk.agentic._cli_path_exists", return_value=True):
            result = _flow_map()
        self.assertIn("scan", result)
        self.assertIn("plan", result)
        self.assertIn("apply", result)
        self.assertIn("rules", result)


class TestCliTree(unittest.TestCase):
    def test_cli_tree_returns_string(self):
        from desk.agentic import _cli_tree
        result = _cli_tree()
        self.assertIsInstance(result, str)

    def test_cli_tree_renders_from_the_live_parser(self):
        # Was: "returns empty because desk.cli has no build_parser()" -- an
        # assertion that the capsule ships WITHOUT its CLI Tree. The empty
        # string was the symptom of a swallowed AttributeError, not a contract.
        from desk.agentic import _cli_tree
        self.assertIn("scan", _cli_tree())

    def test_cli_tree_is_empty_when_parser_is_none(self):
        # The genuine None-handling contract, which the test above was
        # accidentally standing in for.
        from desk.agentic import _cli_tree
        with patch("desk.agentic._get_parser", return_value=None):
            self.assertEqual(_cli_tree(), "")

    def test_cli_tree_non_empty_when_parser_provided(self):
        import argparse
        from desk.agentic import _cli_tree
        fake_parser = argparse.ArgumentParser(prog="desk-assistant")
        fake_parser.add_subparsers().add_parser("scan")
        with patch("desk.agentic._get_parser", return_value=fake_parser):
            result = _cli_tree()
        self.assertIsInstance(result, str)


class TestCliPathExists(unittest.TestCase):
    def test_finds_real_subcommand_in_the_live_parser(self):
        # Was: "returns False -- default behavior since desk.cli has no
        # build_parser()". That encoded a BUG as expected behavior. The loader
        # imported a name that does not exist, cached_parser_loader swallowed
        # the AttributeError, and _get_parser() returned None -- so every path
        # check failed and the capsule silently shipped without its CLI Tree
        # and Flow Map. `scan` is a real desk subcommand and must be found.
        from desk.agentic import _cli_path_exists
        self.assertTrue(_cli_path_exists(["scan"]))

    def test_returns_false_for_unknown_subcommand(self):
        from desk.agentic import _cli_path_exists
        self.assertFalse(_cli_path_exists(["definitely-not-a-command"]))

    def test_returns_false_with_explicit_none_parser(self):
        from desk.agentic import _cli_path_exists
        with patch("desk.agentic._get_parser", return_value=None):
            result = _cli_path_exists(["scan"])
        self.assertFalse(result)

    def test_returns_true_when_path_found_in_parser(self):
        import argparse
        from desk.agentic import _cli_path_exists
        parser = argparse.ArgumentParser()
        parser.add_subparsers().add_parser("scan")
        with patch("desk.agentic._get_parser", return_value=parser):
            # core.agentic.cli_path_exists checks the parser for the path
            with patch("desk.agentic._core_cli_path_exists", return_value=True):
                result = _cli_path_exists(["scan"])
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
