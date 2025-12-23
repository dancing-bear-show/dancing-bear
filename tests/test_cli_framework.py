"""Tests for CLI framework components."""
from __future__ import annotations

import io
import sys
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
    die,
)
from core.cli_output import (
    OutputConfig,
    OutputFormat,
    OutputWriter,
    output,
    output_json,
)
from core.cli_framework import (
    CLIApp,
    CommandGroup,
    Argument,
    CommandDef,
    quick_cli,
)
from core.cli_args import (
    add_output_args,
    add_dry_run_args,
    add_date_range_args,
    add_profile_args,
    add_filter_args,
    ArgumentGroup,
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


if __name__ == "__main__":
    unittest.main()
