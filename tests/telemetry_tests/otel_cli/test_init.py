"""Tests for telemetry/otel/cli/__init__.py dispatcher."""

from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from telemetry.otel.cli import (
    _ALIASES,
    _SUBCOMMANDS,
    _should_skip_infrastructure_check,
    _split_argv,
    main,
)


# ---------------------------------------------------------------------------
# _split_argv
# ---------------------------------------------------------------------------


class TestSplitArgv(unittest.TestCase):
    def test_simple_subcommand(self):
        subcmd, remaining, show_help = _split_argv(["cost"])
        self.assertEqual(subcmd, "cost")
        self.assertEqual(remaining, [])
        self.assertFalse(show_help)

    def test_subcommand_with_flags(self):
        subcmd, remaining, show_help = _split_argv(["cost", "--breakdown", "session"])
        self.assertEqual(subcmd, "cost")
        self.assertEqual(remaining, ["--breakdown", "session"])
        self.assertFalse(show_help)

    def test_help_only(self):
        subcmd, remaining, show_help = _split_argv(["--help"])
        self.assertIsNone(subcmd)
        self.assertTrue(show_help)

    def test_h_flag(self):
        subcmd, remaining, show_help = _split_argv(["-h"])
        self.assertIsNone(subcmd)
        self.assertTrue(show_help)

    def test_empty_argv(self):
        subcmd, remaining, show_help = _split_argv([])
        self.assertIsNone(subcmd)
        self.assertFalse(show_help)

    def test_flag_before_subcommand_goes_to_remaining(self):
        # Flags before subcommand are treated as remaining
        subcmd, remaining, show_help = _split_argv(["--format", "json", "cost"])
        # First non-flag positional is "json" (since "--format" starts with "-")
        # Actually "json" is the first non-flag, so it becomes subcmd
        self.assertEqual(subcmd, "json")
        self.assertIn("cost", remaining)


# ---------------------------------------------------------------------------
# _should_skip_infrastructure_check
# ---------------------------------------------------------------------------


class TestShouldSkipInfraCheck(unittest.TestCase):
    def test_help_flag_skips(self):
        self.assertTrue(_should_skip_infrastructure_check(["--help"]))

    def test_h_flag_skips(self):
        self.assertTrue(_should_skip_infrastructure_check(["-h"]))

    def test_health_subcommand_skips(self):
        self.assertTrue(_should_skip_infrastructure_check(["health"]))

    def test_agentic_flag_skips(self):
        self.assertTrue(_should_skip_infrastructure_check(["--agentic"]))

    def test_regular_subcommand_does_not_skip(self):
        self.assertFalse(_should_skip_infrastructure_check(["cost"]))

    def test_empty_argv_does_not_skip(self):
        self.assertFalse(_should_skip_infrastructure_check([]))


# ---------------------------------------------------------------------------
# main dispatcher
# ---------------------------------------------------------------------------


class TestMainDispatcher(unittest.TestCase):
    def test_no_args_prints_help_and_returns_0(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            result = main([])
        self.assertEqual(result, 0)
        self.assertIn("usage", buf.getvalue())

    def test_help_flag_returns_0(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            result = main(["--help"])
        self.assertEqual(result, 0)

    def test_unknown_subcommand_returns_2(self):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            result = main(["nonexistent_subcmd"])
        self.assertEqual(result, 2)
        self.assertIn("nonexistent_subcmd", buf.getvalue())

    def test_alias_resolves_to_real_subcommand(self):
        # "metrics" -> "query"
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch.dict("sys.modules", {"telemetry.otel.cli.query": fake_module}):
            with patch("telemetry.otel.cli._check_infrastructure", return_value=None):
                with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=False):
                    result = main(["metrics"])
        self.assertEqual(result, 0)
        fake_module.main.assert_called_once()

    def test_health_subcommand_skips_infra_check(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch.dict("sys.modules", {"telemetry.otel.cli.health": fake_module}):
            result = main(["health"])
        self.assertEqual(result, 0)
        fake_module.main.assert_called_once()

    def test_infra_check_failure_returns_exit_code(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch.dict("sys.modules", {"telemetry.otel.cli.cost": fake_module}):
            with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=False):
                with patch("telemetry.otel.cli._check_infrastructure", side_effect=SystemExit(1)):
                    result = main(["cost"])
        self.assertEqual(result, 1)

    def test_valid_subcommand_calls_module_main(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch.dict("sys.modules", {"telemetry.otel.cli.size": fake_module}):
            with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=True):
                result = main(["size"])
        fake_module.main.assert_called_once()
        self.assertEqual(result, 0)

    def test_known_aliases(self):
        self.assertEqual(_ALIASES["metrics"], "query")
        self.assertEqual(_ALIASES["events"], "inspect")
        self.assertEqual(_ALIASES["du"], "size")
        self.assertEqual(_ALIASES["rm"], "prune")
        self.assertEqual(_ALIASES["delete"], "clear")

    def test_all_subcommands_registered(self):
        expected = {
            "health", "size", "inspect", "query", "stats", "cost",
            "sessions", "prune", "clear", "events-search", "compare",
            "tools", "prompts", "anomalies", "clusters",
            "otel-summary", "workflow-cost",
        }
        self.assertEqual(set(_SUBCOMMANDS.keys()), expected)

    def test_infra_check_exit_with_none_code(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch.dict("sys.modules", {"telemetry.otel.cli.cost": fake_module}):
            with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=False):
                with patch("telemetry.otel.cli._check_infrastructure", side_effect=SystemExit(None)):
                    result = main(["cost"])
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
