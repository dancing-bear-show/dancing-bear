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

    def test_agentic_flag(self):
        """Test --agentic flag works via module."""
        proc = run([sys.executable, "-m", "resume", "--agentic"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("agentic: resume", proc.stdout)


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

    def test_emit_agentic_function(self):
        """Test _emit_agentic() loads agentic emit function."""
        from resume.cli.main import _emit_agentic

        result = _emit_agentic("yaml", compact=True)
        self.assertEqual(result, 0)


class TestResumeCommandHelpers(unittest.TestCase):
    """Test resume command helper functions."""

    def test_resolve_out_with_explicit_out(self):
        """Test _resolve_out uses explicit --out path."""
        from resume.cli.main import _resolve_out
        from pathlib import Path

        args = MagicMock()
        args.out = "custom/path.json"
        args.profile = None
        args.out_dir = "out"

        result = _resolve_out(args, ".json", kind="data")
        self.assertEqual(result, Path("custom/path.json"))

    def test_resolve_out_with_profile(self):
        """Test _resolve_out generates path from profile."""
        from resume.cli.main import _resolve_out
        from pathlib import Path

        args = MagicMock()
        args.out = None
        args.profile = "test_profile"
        args.out_dir = "out"

        result = _resolve_out(args, ".json", kind="data")
        self.assertEqual(result, Path("out/test_profile/data.json"))

    def test_resolve_out_default(self):
        """Test _resolve_out uses DEFAULT_PROFILE when no profile."""
        from resume.cli.main import _resolve_out, DEFAULT_PROFILE
        from pathlib import Path

        args = MagicMock()
        args.out = None
        args.profile = None
        args.out_dir = "out"

        result = _resolve_out(args, ".json", kind="data")
        self.assertEqual(result, Path(f"out/{DEFAULT_PROFILE}/data.json"))

    def test_extend_seed_with_style_no_profile(self):
        """Test _extend_seed_with_style returns seed unchanged when no style profile."""
        from resume.cli.main import _extend_seed_with_style

        seed = {"keywords": ["python", "testing"]}
        result = _extend_seed_with_style(seed, None)
        self.assertEqual(result, seed)

    @patch('resume.cli.main.read_yaml_or_json')
    @patch('resume.style.extract_style_keywords')
    def test_extend_seed_with_style_adds_keywords(self, mock_extract, mock_read):
        """Test _extend_seed_with_style adds style keywords to seed."""
        from resume.cli.main import _extend_seed_with_style

        mock_read.return_value = {"style": "data"}
        mock_extract.return_value = ["leadership", "management"]

        seed = {"keywords": ["python"]}
        result = _extend_seed_with_style(seed, "style.json")

        # Should have original + new keywords
        self.assertIn("python", result["keywords"])
        self.assertIn("leadership", result["keywords"])
        self.assertIn("management", result["keywords"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
