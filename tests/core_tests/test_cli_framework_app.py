"""Tests for CLIApp — unique tests not covered by test_cli_framework.py."""
from __future__ import annotations

import unittest

from core.cli_errors import ExitCode
from core.cli_framework import CLIApp


class TestCLIApp(unittest.TestCase):
    """Test CLI application framework — unique behaviors."""

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

if __name__ == "__main__":
    unittest.main()
