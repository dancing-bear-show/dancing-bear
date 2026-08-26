"""Tests for CLI framework components."""
from __future__ import annotations

import io
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from core.cli_errors import (
    CLIError,
    ConfigError,
    AuthError,
    NetworkError,
    NotFoundError,
    UsageError,
    ExitCode,
    handle_error,
)
from core.cli_output import (
    OutputConfig,
    OutputFormat,
    OutputWriter,
)
from core.cli_framework import CLIApp
from core.cli_framework_group import quick_cli
from core.cli_framework_parser import _HelpfulArgumentParser
from core.cli_args import (
    add_output_args,
    add_dry_run_args,
    add_date_range_args,
    add_profile_args,
    add_filter_args,
)


class TestExitCodes(unittest.TestCase):
    """Test exit code definitions."""

    def test_exit_codes_are_integers(self):
        self.assertEqual(ExitCode.SUCCESS, 0)
        self.assertEqual(ExitCode.ERROR, 1)
        self.assertEqual(ExitCode.USAGE, 2)
        self.assertEqual(ExitCode.INTERRUPTED, 130)

    def test_error_types_have_correct_codes(self):
        self.assertEqual(ConfigError("test").code, ExitCode.CONFIG_ERROR)
        self.assertEqual(AuthError("test").code, ExitCode.AUTH_ERROR)
        self.assertEqual(NetworkError("test").code, ExitCode.NETWORK_ERROR)
        self.assertEqual(NotFoundError("test").code, ExitCode.NOT_FOUND)
        self.assertEqual(UsageError("test").code, ExitCode.USAGE)


class TestCLIError(unittest.TestCase):
    """Test CLIError class."""

    def test_error_message(self):
        err = CLIError("Something went wrong")
        self.assertEqual(str(err), "Something went wrong")

    def test_error_with_hint(self):
        err = CLIError("Failed", hint="Try again")
        self.assertEqual(err.message, "Failed")
        self.assertEqual(err.hint, "Try again")

    def test_error_default_code(self):
        err = CLIError("Error")
        self.assertEqual(err.code, ExitCode.ERROR)


class TestHandleError(unittest.TestCase):
    """Test error handling."""

    def test_handle_cli_error(self):
        err = CLIError("Test error", ExitCode.CONFIG_ERROR)
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            code = handle_error(err)
            self.assertEqual(code, ExitCode.CONFIG_ERROR)
            self.assertIn("Test error", mock_stderr.getvalue())

    def test_handle_cli_error_with_hint(self):
        err = CLIError("Test error", hint="Check config")
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            handle_error(err)
            output = mock_stderr.getvalue()
            self.assertIn("Test error", output)
            self.assertIn("Check config", output)

    def test_handle_keyboard_interrupt(self):
        with patch("sys.stderr", new_callable=io.StringIO):
            code = handle_error(KeyboardInterrupt())
            self.assertEqual(code, ExitCode.INTERRUPTED)

    def test_handle_unexpected_error(self):
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            code = handle_error(ValueError("Unexpected"))
            self.assertEqual(code, ExitCode.ERROR)
            self.assertIn("Unexpected", mock_stderr.getvalue())


class TestOutputWriter(unittest.TestCase):
    """Test output formatting."""

    def test_print_basic(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print("Hello")
        self.assertEqual(output.getvalue(), "Hello\n")

    def test_print_quiet_mode(self):
        output = io.StringIO()
        config = OutputConfig(file=output, quiet=True)
        writer = OutputWriter(config)
        writer.print("Hello")
        self.assertEqual(output.getvalue(), "")

    def test_print_verbose(self):
        output = io.StringIO()
        config = OutputConfig(file=output, verbose=True)
        writer = OutputWriter(config)
        writer.print_verbose("Debug info")
        self.assertEqual(output.getvalue(), "Debug info\n")

    def test_print_verbose_when_disabled(self):
        output = io.StringIO()
        config = OutputConfig(file=output, verbose=False)
        writer = OutputWriter(config)
        writer.print_verbose("Debug info")
        self.assertEqual(output.getvalue(), "")

    def test_print_dry_run(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print_dry_run("Would delete file")
        self.assertIn("[dry-run]", output.getvalue())

    def test_print_json(self):
        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.JSON)
        writer = OutputWriter(config)
        writer.print_data({"key": "value"})
        self.assertIn('"key"', output.getvalue())
        self.assertIn('"value"', output.getvalue())

    def test_print_list(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print_list(["a", "b", "c"])
        out = output.getvalue()
        self.assertIn("- a", out)
        self.assertIn("- b", out)
        self.assertIn("- c", out)

    def test_print_dict(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print_dict({"name": "test", "value": 42})
        out = output.getvalue()
        self.assertIn("name: test", out)
        self.assertIn("value: 42", out)

    def test_print_table(self):
        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.TABLE)
        writer = OutputWriter(config)
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        writer.print_data(data)
        out = output.getvalue()
        self.assertIn("name", out)
        self.assertIn("Alice", out)
        self.assertIn("Bob", out)


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

    def _make_parser_with_global_flag(self):
        parser = _HelpfulArgumentParser(prog="test-app", add_help=False)
        parser.add_argument("--profile")
        parser.add_argument("--verbose", action="store_true")
        sub = parser.add_subparsers(dest="command")
        sub.add_parser("auth")
        return parser

    def _parse_and_capture_stderr(self, parser, argv: list[str]) -> str:
        """Run parser.parse_args(argv), which must SystemExit, and return stderr."""
        with patch("sys.stderr", new_callable=io.StringIO) as stderr:
            with self.assertRaises(SystemExit):
                parser.parse_args(argv)
        return stderr.getvalue()

    def test_misplaced_no_arg_flag_example_omits_value_placeholder(self):
        """A store_true flag takes no argument, so the example must not add one.

        "test-app --verbose <value> <command>" is itself an invalid invocation;
        a hint that suggests one is no better than the bug it replaced.
        """
        parser = self._make_parser_with_global_flag()
        output = self._parse_and_capture_stderr(parser, ["auth", "--verbose"])

        self.assertIn("test-app --verbose <command>", output)
        self.assertNotIn("--verbose <value>", output)

    def test_misplaced_global_flag_explains_position_not_spelling(self):
        """A real global flag used after the subcommand must not be echoed back.

        Regression: `mail auth --profile personal` produced "Unknown flag
        '--profile'. Did you mean: --profile?" — the suggester found the flag on
        the top-level parser and proposed the identical spelling, naming neither
        the cause (wrong position) nor the fix.
        """
        parser = self._make_parser_with_global_flag()
        output = self._parse_and_capture_stderr(parser, ["auth", "--profile", "personal"])

        self.assertIn("must come before the subcommand", output)
        self.assertNotIn("Did you mean: --profile", output)

    def test_genuinely_misspelled_flag_still_suggests_correction(self):
        """The position hint must not swallow real did-you-mean suggestions."""
        parser = self._make_parser_with_global_flag()
        output = self._parse_and_capture_stderr(parser, ["auth", "--porfile", "personal"])

        self.assertIn("Did you mean: --profile", output)
        self.assertNotIn("must come before the subcommand", output)

    def test_invalid_subcommand_suggests_closest_match(self):
        parser = self._make_parser()
        output = self._parse_and_capture_stderr(parser, ["serch"])
        self.assertIn("Did you mean: search", output)

    def test_invalid_subcommand_usage_not_duplicated(self):
        parser = self._make_parser()
        output = self._parse_and_capture_stderr(parser, ["serch"])
        self.assertEqual(output.count("usage:"), 1)

    def test_invalid_flag_choice_does_not_suggest_subcommands(self):
        # Regression: an invalid --agentic-format choice must not be compared
        # against subcommand names (they share the "invalid choice" message).
        parser = self._make_parser()
        output = self._parse_and_capture_stderr(parser, ["--agentic-format", "xml"])
        self.assertNotIn("Did you mean: search", output)
        self.assertNotIn("Did you mean: send", output)

    def test_unrecognized_flag_suggests_similar_flag(self):
        # A non-prefix typo (extra trailing 't') so argparse's own prefix
        # matching doesn't silently resolve it to --agentic-format first.
        parser = self._make_parser()
        output = self._parse_and_capture_stderr(parser, ["search", "--agentic-formatt", "json"])
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


class TestOutputWriterHelperFunctions(unittest.TestCase):
    """Test OutputWriter helper functions extracted during refactoring."""

    def setUp(self):
        """Set up test fixtures."""
        self.output = io.StringIO()
        self.config = OutputConfig(file=self.output)
        self.writer = OutputWriter(self.config)

    def test_row_to_strings_with_dict_and_headers(self):
        """Test _row_to_strings converts dict with headers correctly."""
        row = {"name": "Alice", "age": 30, "city": "NYC"}
        headers = ["name", "age"]
        result = self.writer._row_to_strings(row, headers)
        self.assertEqual(result, ["Alice", "30"])

    def test_row_to_strings_with_dict_no_headers(self):
        """Test _row_to_strings converts dict without headers."""
        row = {"name": "Bob", "age": 25}
        result = self.writer._row_to_strings(row)
        self.assertEqual(len(result), 2)
        self.assertIn("Bob", result)
        self.assertIn("25", result)

    def test_row_to_strings_with_list(self):
        """Test _row_to_strings converts list."""
        row = ["Alice", 30, "NYC"]
        result = self.writer._row_to_strings(row)
        self.assertEqual(result, ["Alice", "30", "NYC"])

    def test_row_to_strings_with_tuple(self):
        """Test _row_to_strings converts tuple."""
        row = ("Bob", 25)
        result = self.writer._row_to_strings(row)
        self.assertEqual(result, ["Bob", "25"])

    def test_row_to_strings_with_other_type(self):
        """Test _row_to_strings converts other types to single-item list."""
        result = self.writer._row_to_strings(42)
        self.assertEqual(result, ["42"])

    def test_row_to_strings_handles_missing_keys(self):
        """Test _row_to_strings handles missing dict keys."""
        row = {"name": "Alice"}
        headers = ["name", "age", "city"]
        result = self.writer._row_to_strings(row, headers)
        self.assertEqual(result, ["Alice", "", ""])

    def test_calculate_column_widths_basic(self):
        """Test _calculate_column_widths calculates correct widths."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", "30"], ["Bob", "25"]]
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [5, 3])  # max("Name"=4, "Alice"=5), max("Age"=3, "30"=2, "25"=2)

    def test_calculate_column_widths_with_long_data(self):
        """Test _calculate_column_widths handles data wider than headers."""
        headers = ["ID", "Name"]
        str_rows = [["123456", "Alexander"], ["7", "Bo"]]
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [6, 9])  # max(2,6), max(4,9)

    def test_calculate_column_widths_empty_rows(self):
        """Test _calculate_column_widths with empty rows."""
        headers = ["Name", "Age"]
        str_rows = []
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [4, 3])  # Just header lengths

    def test_calculate_column_widths_with_extra_columns(self):
        """Test _calculate_column_widths ignores columns beyond headers."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", "30", "Extra", "Data"]]
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [5, 3])  # Only first 2 columns considered

    def test_print_table_with_headers_basic(self):
        """Test _print_table_with_headers prints formatted table."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", "30"], ["Bob", "25"]]
        self.writer._print_table_with_headers(headers, str_rows)

        output = self.output.getvalue()
        self.assertIn("Name", output)
        self.assertIn("Age", output)
        self.assertIn("Alice", output)
        self.assertIn("Bob", output)
        self.assertIn("|", output)  # Column separator
        self.assertIn("-", output)  # Header separator

    def test_print_table_with_headers_alignment(self):
        """Test _print_table_with_headers aligns columns properly."""
        headers = ["ID", "Name"]
        str_rows = [["1", "Alice"], ["123", "Bo"]]
        self.writer._print_table_with_headers(headers, str_rows)

        output = self.output.getvalue()
        lines = output.strip().split("\n")
        # Check that we have header, separator, and data rows
        self.assertEqual(len(lines), 4)  # header + separator + 2 data rows
        # Check that separator line uses dashes
        self.assertTrue(all(c in "-" for c in lines[1]))
        # Check that data lines contain the expected values
        data_lines = [line for line in lines if "Alice" in line or "Bo" in line]
        self.assertEqual(len(data_lines), 2)

    def test_print_table_with_headers_empty_values(self):
        """Test _print_table_with_headers handles empty values."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", ""], ["", "25"]]
        self.writer._print_table_with_headers(headers, str_rows)

        output = self.output.getvalue()
        self.assertIn("Alice", output)
        self.assertIn("25", output)


class TestDataclassOutput(unittest.TestCase):
    """Test output with dataclasses."""

    def test_print_dataclass_as_json(self):
        @dataclass
        class Person:
            name: str
            age: int

        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.JSON)
        writer = OutputWriter(config)
        writer.print_data(Person("Alice", 30))
        out = output.getvalue()
        self.assertIn('"name"', out)
        self.assertIn('"Alice"', out)
        self.assertIn('"age"', out)
        self.assertIn("30", out)

    def test_print_dataclass_as_text(self):
        @dataclass
        class Person:
            name: str
            age: int

        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.TEXT)
        writer = OutputWriter(config)
        writer.print_data(Person("Bob", 25))
        out = output.getvalue()
        self.assertIn("name", out)
        self.assertIn("Bob", out)


class TestCommandGroupRegister(unittest.TestCase):
    """CommandGroup.register() must match the @command/@argument decorator form.

    register() appends to CLIApp._pending_arguments directly, in reverse, because
    command() applies list(reversed(...)) to undo the bottom-up order that stacked
    decorators produce. That double reversal is easy to break silently: getting it
    wrong reorders every flag on a registered subcommand without failing anything
    else, so these tests pin the ordering explicitly.
    """

    @staticmethod
    def _flags(app, full_name):
        return [a.name_or_flags for a in app._commands[full_name].arguments]

    def _decorator_app(self):
        app = CLIApp("t")
        group = app.group("g", help="g")

        @group.command("cmd", help="C")
        @group.argument("--first", help="f")
        @group.argument("--second", help="s")
        @group.argument("--third", help="t")
        def _handler(args) -> int:
            return 0

        return app

    def _register_app(self):
        app = CLIApp("t")
        group = app.group("g", help="g")

        def _handler(args) -> int:
            return 0

        group.register("cmd", "C", _handler, [
            (("--first",), {"help": "f"}),
            (("--second",), {"help": "s"}),
            (("--third",), {"help": "t"}),
        ])
        return app

    def test_preserves_source_order(self):
        self.assertEqual(
            self._flags(self._register_app(), "g.cmd"),
            [("--first",), ("--second",), ("--third",)],
        )

    def test_matches_decorator_form(self):
        self.assertEqual(
            self._flags(self._register_app(), "g.cmd"),
            self._flags(self._decorator_app(), "g.cmd"),
        )

    def test_kwargs_survive_registration(self):
        app = CLIApp("t")
        group = app.group("g", help="g")

        def _handler(args) -> int:
            return 0

        group.register("cmd", "C", _handler, [
            (("--count",), {"type": int, "default": 7, "help": "n"}),
            (("--flag",), {"action": "store_true", "help": "b"}),
            (("--name",), {"required": True, "dest": "who", "help": "w"}),
        ])
        by_flag = {a.name_or_flags[0]: a.kwargs for a in app._commands["g.cmd"].arguments}
        self.assertEqual(by_flag["--count"]["type"], int)
        self.assertEqual(by_flag["--count"]["default"], 7)
        self.assertEqual(by_flag["--flag"]["action"], "store_true")
        self.assertTrue(by_flag["--name"]["required"])
        self.assertEqual(by_flag["--name"]["dest"], "who")

    def test_parser_accepts_registered_arguments(self):
        args = self._register_app().build_parser().parse_args(
            ["g", "cmd", "--first", "a", "--second", "b", "--third", "c"]
        )
        self.assertEqual((args.first, args.second, args.third), ("a", "b", "c"))

    def test_shared_kwargs_dict_reused_across_commands(self):
        """A kwargs dict reused by two commands must not be mutated by the first."""
        shared = {"help": "shared flag"}
        app = CLIApp("t")
        group = app.group("g", help="g")

        def _handler(args) -> int:
            return 0

        group.register("one", "1", _handler, [(("--shared",), shared)])
        group.register("two", "2", _handler, [(("--shared",), shared)])

        self.assertEqual(shared, {"help": "shared flag"})
        for name in ("g.one", "g.two"):
            self.assertEqual(self._flags(app, name), [("--shared",)])

    def test_empty_argument_list(self):
        app = CLIApp("t")
        group = app.group("g", help="g")

        def _handler(args) -> int:
            return 0

        group.register("bare", "B", _handler, [])
        self.assertEqual(self._flags(app, "g.bare"), [])
        self.assertIs(app._commands["g.bare"].func, _handler)

    def test_does_not_leak_pending_arguments(self):
        app = CLIApp("t")
        group = app.group("g", help="g")

        def _handler(args) -> int:
            return 0

        group.register("one", "1", _handler, [(("--a",), {"help": "a"})])
        self.assertEqual(app._pending_arguments, [])
        group.register("two", "2", _handler, [(("--b",), {"help": "b"})])
        self.assertEqual(self._flags(app, "g.two"), [("--b",)])


if __name__ == "__main__":
    unittest.main()
