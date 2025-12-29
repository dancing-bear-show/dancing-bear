"""Tests for resume/__main__.py module."""

from __future__ import annotations

import sys
import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
