"""Tests for telemetry/otel/cli/__init__.py dispatcher."""

from __future__ import annotations

import io
import unittest
from unittest.mock import MagicMock, patch

from telemetry.otel.cli import (
    _ALIASES,
    _REGISTRY,
    _SUBCOMMANDS,
    _check_infrastructure,
    _print_help,
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
        subcmd, _, show_help = _split_argv(["--help"])
        self.assertIsNone(subcmd)
        self.assertTrue(show_help)

    def test_h_flag(self):
        subcmd, _, show_help = _split_argv(["-h"])
        self.assertIsNone(subcmd)
        self.assertTrue(show_help)

    def test_empty_argv(self):
        subcmd, _, show_help = _split_argv([])
        self.assertIsNone(subcmd)
        self.assertFalse(show_help)

    def test_flag_with_value_before_subcommand_is_not_supported(self):
        # KNOWN LIMITATION, not desired behavior: _split_argv has no concept
        # of "flags that take a value", so a value-taking flag placed before
        # the subcommand (e.g. --format json) has its value ("json") mistaken
        # for the subcommand. This isn't a supported invocation per the
        # project's CLI conventions (flags always follow the subcommand,
        # e.g. "telemetry otel cost --breakdown session"), so this test only
        # pins the current parser's actual output for this unsupported input
        # to catch accidental behavior changes — it does not assert this is
        # correct or desired.
        subcmd, remaining, _ = _split_argv(["--format", "json", "cost"])
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

    def test_subcommands_derived_from_registry(self):
        self.assertEqual(
            _SUBCOMMANDS,
            {name: module for name, (module, _) in _REGISTRY.items()},
        )

    def test_every_subcommand_has_a_help_description(self):
        # The registry pairs module and description in one entry precisely so
        # these cannot drift; assert no entry carries a blank description.
        missing = [name for name, (_, desc) in _REGISTRY.items() if not desc.strip()]
        self.assertEqual(missing, [])

    def test_help_lists_every_subcommand_with_its_description(self):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            _print_help()
        out = buf.getvalue()
        for name, (_, desc) in _REGISTRY.items():
            self.assertIn(name, out)
            self.assertIn(desc, out)

    def test_infra_check_exit_with_none_code(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch.dict("sys.modules", {"telemetry.otel.cli.cost": fake_module}):
            with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=False):
                with patch("telemetry.otel.cli._check_infrastructure", side_effect=SystemExit(None)):
                    result = main(["cost"])
        self.assertEqual(result, 1)


class TestCheckInfrastructure(unittest.TestCase):
    """_check_infrastructure is mocked out everywhere else; cover its real body."""

    def test_returns_none_when_infrastructure_is_healthy(self):
        fake_health = MagicMock()
        with patch.dict("sys.modules", {"telemetry.otel.health": fake_health}):
            self.assertIsNone(_check_infrastructure())
        fake_health.require_otel_infrastructure.assert_called_once()

    def test_propagates_system_exit_from_health_check(self):
        # require_otel_infrastructure signals failure by raising SystemExit;
        # _check_infrastructure must not swallow it -- main() translates it.
        fake_health = MagicMock()
        fake_health.require_otel_infrastructure.side_effect = SystemExit(3)
        with patch.dict("sys.modules", {"telemetry.otel.health": fake_health}):
            with self.assertRaises(SystemExit) as ctx:
                _check_infrastructure()
        self.assertEqual(ctx.exception.code, 3)


class TestMainArgvDefaulting(unittest.TestCase):
    def test_none_argv_falls_back_to_sys_argv(self):
        buf = io.StringIO()
        with patch("sys.argv", ["telemetry-otel"]):
            with patch("sys.stdout", buf):
                result = main(None)
        self.assertEqual(result, 0)
        self.assertIn("usage", buf.getvalue())

    def test_none_argv_dispatches_subcommand_from_sys_argv(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch("sys.argv", ["telemetry-otel", "size"]):
            with patch.dict("sys.modules", {"telemetry.otel.cli.size": fake_module}):
                with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=True):
                    result = main(None)
        self.assertEqual(result, 0)
        fake_module.main.assert_called_once_with([])


class TestMainSadPaths(unittest.TestCase):
    def test_unknown_subcommand_lists_available_commands(self):
        buf = io.StringIO()
        with patch("sys.stderr", buf):
            result = main(["bogus"])
        self.assertEqual(result, 2)
        err = buf.getvalue()
        for name in _REGISTRY:
            self.assertIn(name, err)

    def test_alias_to_unknown_target_is_not_silently_accepted(self):
        # An alias pointing at a non-existent subcommand must fail loudly
        # rather than dispatch to a missing module.
        with patch.dict("telemetry.otel.cli._ALIASES", {"broken": "nope"}, clear=False):
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                result = main(["broken"])
        self.assertEqual(result, 2)
        self.assertIn("nope", buf.getvalue())

    def test_subcommand_nonzero_exit_is_propagated(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 7
        with patch.dict("sys.modules", {"telemetry.otel.cli.cost": fake_module}):
            with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=True):
                result = main(["cost"])
        self.assertEqual(result, 7)

    def test_subcommand_flags_are_forwarded_not_consumed(self):
        fake_module = MagicMock()
        fake_module.main.return_value = 0
        with patch.dict("sys.modules", {"telemetry.otel.cli.cost": fake_module}):
            with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=True):
                main(["cost", "--breakdown", "session"])
        fake_module.main.assert_called_once_with(["--breakdown", "session"])

    def test_import_error_on_registered_module_propagates(self):
        # A registry entry naming a module that cannot be imported is a real
        # defect; it must raise rather than be reported as a clean exit.
        with patch.dict("telemetry.otel.cli._SUBCOMMANDS", {"cost": "telemetry.otel.cli.does_not_exist"}, clear=False):
            with patch("telemetry.otel.cli._should_skip_infrastructure_check", return_value=True):
                with self.assertRaises(ModuleNotFoundError):
                    main(["cost"])


if __name__ == "__main__":
    unittest.main()
