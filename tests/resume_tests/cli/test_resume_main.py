"""Tests for resume/__main__.py module."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import repo_root, run


class TestResumeMain(unittest.TestCase):
    """Test resume/__main__.py module entry point."""

    def test_main_import_exists(self):
        """Test that main function can be imported from __main__."""
        from resume.__main__ import main

        self.assertIsNotNone(main)
        self.assertTrue(callable(main))

    def test_module_invocation_help(self):
        """Test that python -m resume --help works."""
        root = repo_root()
        proc = run([sys.executable, "-m", "resume", "--help"], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("resume", proc.stdout.lower())

    def test_main_returns_zero_with_help(self):
        """Test that main returns 0 when showing help."""
        from resume.__main__ import main

        # Help exits with 0
        with self.assertRaises(SystemExit) as ctx:
            main(["--help"])
        self.assertEqual(ctx.exception.code, 0)


class TestResumeCliMain(unittest.TestCase):
    """Test resume/cli/main.py main() function."""

    def test_main_returns_zero_for_agentic(self):
        """Test main() returns 0 for agentic output."""
        from resume.cli.main import main

        result = main(["--agentic"])
        self.assertEqual(result, 0)

    def test_main_no_command_shows_help(self):
        """Test main() shows help when no command provided."""
        from resume.cli.main import main

        result = main([])
        self.assertEqual(result, 0)

    @patch('resume.cli.main.app')
    def test_main_handles_keyboard_interrupt(self, mock_app):
        """Test main() returns 2 on KeyboardInterrupt."""
        from resume.cli.main import main

        # Create a mock command function that raises KeyboardInterrupt
        mock_cmd = MagicMock(side_effect=KeyboardInterrupt)
        mock_parser = MagicMock()
        mock_args = MagicMock()
        mock_args._cmd_func = mock_cmd
        mock_args.agentic = False
        mock_parser.parse_args.return_value = mock_args
        mock_app.build_parser.return_value = mock_parser

        result = main(["dummy"])
        self.assertEqual(result, 2)

    @patch('resume.cli.main.app')
    def test_main_handles_general_exception(self, mock_app):
        """Test main() returns 1 on general exception."""
        from resume.cli.main import main

        # Create a mock command function that raises an exception
        mock_cmd = MagicMock(side_effect=RuntimeError("Test error"))
        mock_parser = MagicMock()
        mock_args = MagicMock()
        mock_args._cmd_func = mock_cmd
        mock_args.agentic = False
        mock_parser.parse_args.return_value = mock_args
        mock_app.build_parser.return_value = mock_parser

        result = main(["dummy"])
        self.assertEqual(result, 1)

    def test_emit_agentic_function(self):
        """Test _emit_agentic() loads agentic emit function."""
        from resume.cli.main import _emit_agentic

        result = _emit_agentic("yaml", compact=True)
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
