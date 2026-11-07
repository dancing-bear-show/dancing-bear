"""Tests that unsafe profile names produce a clean CLI error.

Covers:
- render --profile ../evil → CLIError with ExitCode.USAGE, non-zero exit, no traceback
- experience export --profile a/b → non-zero exit, clean message
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import TempDirMixin


class TestUnsafeProfileNameViaCLI(TempDirMixin, unittest.TestCase):
    """Unsafe profile names via CLI produce a one-line error, non-zero exit."""

    def _make_data_file(self) -> Path:
        data_dir = Path(self.tmpdir) / "data"
        data_dir.mkdir(exist_ok=True)
        p = data_dir / "data.json"
        p.write_text(json.dumps({"name": "Test User"}))
        return p

    def test_render_with_path_traversal_profile_exits_nonzero(self):
        """render --profile ../evil exits non-zero with a CLIError, not a traceback."""
        from resume.cli.main import main

        data_file = self._make_data_file()
        stderr_buf = io.StringIO()

        with self.in_tmpdir():
            with mock.patch("sys.stderr", stderr_buf):
                exit_code = main([
                    "render",
                    "--data", str(data_file),
                    "--profile", "../evil",
                    "--out", str(Path(self.tmpdir) / "out.docx"),
                ])

        self.assertNotEqual(exit_code, 0, "Unsafe profile name must not exit 0")
        # The error message must name the bad profile
        err_output = stderr_buf.getvalue()
        self.assertIn("../evil", err_output)
        # Must not contain a Python traceback
        self.assertNotIn("Traceback", err_output)

    def test_render_with_slash_in_profile_exits_nonzero(self):
        """render --profile a/b exits non-zero with a clean error."""
        from resume.cli.main import main

        data_file = self._make_data_file()
        stderr_buf = io.StringIO()

        with self.in_tmpdir():
            with mock.patch("sys.stderr", stderr_buf):
                exit_code = main([
                    "render",
                    "--data", str(data_file),
                    "--profile", "a/b",
                    "--out", str(Path(self.tmpdir) / "out.docx"),
                ])

        self.assertNotEqual(exit_code, 0)
        err_output = stderr_buf.getvalue()
        self.assertIn("a/b", err_output)
        self.assertNotIn("Traceback", err_output)

    def test_experience_export_with_unsafe_profile_exits_nonzero(self):
        """experience export --profile ../x exits non-zero with a clean error."""
        from resume.cli.main import main

        data_file = self._make_data_file()
        stderr_buf = io.StringIO()

        with self.in_tmpdir():
            with mock.patch("sys.stderr", stderr_buf):
                exit_code = main([
                    "experience", "export",
                    "--data", str(data_file),
                    "--profile", "../x",
                    "--out", str(Path(self.tmpdir) / "out.yaml"),
                ])

        self.assertNotEqual(exit_code, 0)
        err_output = stderr_buf.getvalue()
        self.assertIn("../x", err_output)
        self.assertNotIn("Traceback", err_output)


if __name__ == "__main__":
    unittest.main()
