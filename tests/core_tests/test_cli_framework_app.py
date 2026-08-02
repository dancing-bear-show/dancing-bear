"""Tests for CLIApp, argument parsing, and CLI framework app components."""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from core.cli_errors import (
    CLIError,
    ExitCode,
)
from core.cli_framework import (
    CLIApp,
    _HelpfulArgumentParser,
    quick_cli,
)
from core.cli_args import (
    add_output_args,
    add_dry_run_args,
    add_date_range_args,
    add_profile_args,
    add_filter_args,
)


class TestCLIApp(unittest.TestCase):
    """Test CLI application framework."""

    def test_create_app(self):
        app = CLIApp("test-app", "A test application")
        self.assertEqual(app.name, "test-app")
        self.assertEqual(app.description, "A test application")

    def test_register_command(self):
        app = CLIApp("test", "Test")

        @app.command("greet", help="Say hello")
        def cmd_greet(args):
            return 0

        self.assertIn("greet", app._commands)
        self.assertEqual(app._commands["greet"].help, "Say hello")

    def test_register_command_with_argument(self):
        app = CLIApp("test", "Test")

        @app.command("greet", help="Say hello")
        @app.argument("--name", "-n", help="Name to greet")
        def cmd_greet(args):
            return 0

        cmd_def = app._commands["greet"]
        self.assertEqual(len(cmd_def.arguments), 1)
        self.assertEqual(cmd_def.arguments[0].name_or_flags, ("--name", "-n"))

    def test_run_command(self):
        app = CLIApp("test", "Test", add_common_args=False)

        @app.command("echo", help="Echo a message")
        @app.argument("message", help="Message to echo")
        def cmd_echo(args):
            return 0

        result = app.run(["echo", "hello"])
        self.assertEqual(result, ExitCode.SUCCESS)

    def test_run_without_command(self):
        app = CLIApp("test", "Test", add_common_args=False)

        @app.command("foo", help="Foo command")
        def cmd_foo(args):
            return 0

        with patch("sys.stdout", new_callable=io.StringIO):
            result = app.run([])
            self.assertEqual(result, ExitCode.USAGE)

    def test_run_without_command_uses_on_no_command_hook(self):
        """The on_no_command callback overrides the default help+USAGE
        behavior — used by CLIs preserving a legacy one-line usage message."""
        app = CLIApp("test", "Test", add_common_args=False)

        @app.command("foo", help="Foo command")
        def cmd_foo(args):
            return 0

        result = app.run([], on_no_command=lambda: 1)
        self.assertEqual(result, 1)

    def test_run_sets_output_writer_when_common_args_enabled(self):
        """add_common_args=True (the default) means --output is the
        framework's own format flag, so run() must attach _output."""
        app = CLIApp("test", "Test")  # add_common_args defaults to True

        @app.command("foo", help="Foo command")
        def cmd_foo(args):
            self.assertTrue(hasattr(args, "_output"))
            return 0

        result = app.run(["--output", "json", "foo"])
        self.assertEqual(result, ExitCode.SUCCESS)

    def test_run_does_not_crash_on_custom_output_flag(self):
        """Regression test: add_common_args=False lets a CLI define its own
        --output with non-format semantics (e.g. a file path). run() must
        not try to parse that value as an OutputFormat."""
        app = CLIApp("test", "Test", add_common_args=False)

        @app.command("render", help="Render command")
        @app.argument("--output", "-o", dest="output", required=True)
        def cmd_render(args):
            self.assertEqual(args.output, "out.svg")
            self.assertFalse(hasattr(args, "_output"))
            return 0

        result = app.run(["render", "--output", "out.svg"])
        self.assertEqual(result, ExitCode.SUCCESS)

    def test_command_with_parent(self):
        app = CLIApp("test", "Test", add_common_args=False)

        @app.command("outlook.add", help="Add outlook item")
        def cmd_outlook_add(args):
            return 0

        self.assertIn("outlook.add", app._commands)
        cmd_def = app._commands["outlook.add"]
        self.assertEqual(cmd_def.name, "add")
        self.assertEqual(cmd_def.parent, "outlook")

    def test_command_group(self):
        app = CLIApp("test", "Test", add_common_args=False)
        outlook = app.group("outlook", help="Outlook commands")

        @outlook.command("add", help="Add item")
        def cmd_add(args):
            return 42

        @outlook.command("list", help="List items")
        def cmd_list(args):
            return 0

        self.assertIn("outlook.add", app._commands)
        self.assertIn("outlook.list", app._commands)

    def test_error_handling(self):
        app = CLIApp("test", "Test", add_common_args=False)

        @app.command("fail", help="Always fails")
        def cmd_fail(args):
            raise CLIError("Intentional failure", ExitCode.CONFIG_ERROR)

        with patch("sys.stderr", new_callable=io.StringIO):
            result = app.run(["fail"])
            self.assertEqual(result, ExitCode.CONFIG_ERROR)

    def test_quick_cli(self):
        app = quick_cli("quick-test", "Quick test app")
        self.assertIsInstance(app, CLIApp)
        self.assertEqual(app.name, "quick-test")


class TestNormalizeArgv(unittest.TestCase):
    """Test CLIApp.normalize_argv() '--' separator handling."""

    def test_no_separator_unchanged(self):
        argv = ["search", "--contains", "test"]
        self.assertEqual(CLIApp.normalize_argv(argv), argv)

    def test_strips_first_bare_separator(self):
        argv = ["search", "--", "--contains", "test"]
        self.assertEqual(
            CLIApp.normalize_argv(argv), ["search", "--contains", "test"]
        )

    def test_trailing_separator_preserved(self):
        argv = ["search", "--contains", "test", "--"]
        self.assertEqual(CLIApp.normalize_argv(argv), argv)

    def test_only_first_separator_stripped_second_preserved(self):
        # The first '--' is the optional subcommand/flag separator; a second
        # '--' still guards a positional value that looks like a flag.
        argv = ["cmd", "--", "--opt", "--", "--literal-value"]
        self.assertEqual(
            CLIApp.normalize_argv(argv),
            ["cmd", "--opt", "--", "--literal-value"],
        )

    def test_empty_argv(self):
        self.assertEqual(CLIApp.normalize_argv([]), [])

    def test_single_trailing_separator_preserved(self):
        # A lone '--' with nothing after it carries no separator information
        # here and is left untouched, same as any other trailing '--'.
        self.assertEqual(CLIApp.normalize_argv(["--"]), ["--"])


class TestHelpfulArgumentParser(unittest.TestCase):
    """Test _HelpfulArgumentParser's 'did you mean' suggestions on error."""

    def _make_parser(self):
        parser = _HelpfulArgumentParser(prog="test-app", add_help=False)
        parser.add_argument(
            "--agentic-format", choices=["text", "yaml", "json"], default="text"
        )
        sub = parser.add_subparsers(dest="command")
        sub.add_parser("search")
        sub.add_parser("send")
        return parser

    def test_invalid_subcommand_suggests_closest_match(self):
        parser = self._make_parser()
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                parser.parse_args(["serch"])
        output = stderr.getvalue()
        self.assertIn("Did you mean: search", output)

    def test_invalid_subcommand_usage_not_duplicated(self):
        parser = self._make_parser()
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                parser.parse_args(["serch"])
        output = stderr.getvalue()
        self.assertEqual(output.count("usage:"), 1)

    def test_invalid_flag_choice_does_not_suggest_subcommands(self):
        # Regression: an invalid --agentic-format choice must not be compared
        # against subcommand names (they share the "invalid choice" message).
        parser = self._make_parser()
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                parser.parse_args(["--agentic-format", "xml"])
        output = stderr.getvalue()
        self.assertNotIn("Did you mean: search", output)
        self.assertNotIn("Did you mean: send", output)

    def test_unrecognized_flag_suggests_similar_flag(self):
        # A non-prefix typo (extra trailing 't') so argparse's own prefix
        # matching doesn't silently resolve it to --agentic-format first.
        parser = self._make_parser()
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                parser.parse_args(["search", "--agentic-formatt", "json"])
        output = stderr.getvalue()
        self.assertIn("Did you mean", output)
        self.assertIn("--agentic-format", output)


class TestArgumentHelpers(unittest.TestCase):
    """Test argument helper functions."""

    def test_add_output_args(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_output_args(parser)
        args = parser.parse_args(["--output", "json", "--verbose"])
        self.assertEqual(args.output, "json")
        self.assertTrue(args.verbose)

    def test_add_dry_run_args(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_dry_run_args(parser, include_force=True)
        args = parser.parse_args(["--dry-run", "--force"])
        self.assertTrue(args.dry_run)
        self.assertTrue(args.force)

    def test_add_date_range_args(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_date_range_args(parser)
        args = parser.parse_args(["--from-date", "2024-01-01", "--days-back", "60"])
        self.assertEqual(args.from_date, "2024-01-01")
        self.assertEqual(args.days_back, 60)

    def test_add_profile_args(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_profile_args(parser)
        args = parser.parse_args(["--profile", "work"])
        self.assertEqual(args.profile, "work")

    def test_add_filter_args(self):
        import argparse
        parser = argparse.ArgumentParser()
        add_filter_args(parser, include_offset=True)
        args = parser.parse_args(["--limit", "50", "--offset", "10"])
        self.assertEqual(args.limit, 50)
        self.assertEqual(args.offset, 10)


if __name__ == "__main__":
    unittest.main()
