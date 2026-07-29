"""Tests for GhCLI initialization and ensure_available()."""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.gh_cli import GhCLI


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Minimal stand-in for a completed subprocess result."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestGhCLIInit(unittest.TestCase):
    """Test GhCLI initialization."""

    def test_init_default_run_func(self):
        """Test that default run function is subprocess.run."""
        cli = GhCLI()
        self.assertIs(cli._run, subprocess.run)

    def test_init_custom_run_func(self):
        """Test that custom run function is used."""
        mock_run = MagicMock()
        cli = GhCLI(run_func=mock_run)
        self.assertEqual(cli._run, mock_run)


class TestGhCLIEnsureAvailable(unittest.TestCase):
    """Test ensure_available() method."""

    @patch('shutil.which')
    def test_ensure_available_gh_found(self, mock_which):
        """Test when gh is available in PATH."""
        mock_which.return_value = "/usr/local/bin/gh"
        cli = GhCLI()
        # Should not raise
        cli.ensure_available()
        mock_which.assert_called_once_with("gh")

    @patch('shutil.which')
    def test_ensure_available_gh_not_found(self, mock_which):
        """Test when gh is not available in PATH."""
        mock_which.return_value = None
        cli = GhCLI()
        with self.assertRaises(SystemExit) as ctx:
            cli.ensure_available()
        self.assertIn("gh CLI not found", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
