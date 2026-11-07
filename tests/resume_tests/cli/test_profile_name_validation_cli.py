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


class TestTrailingSlashAndDotProfiles(TempDirMixin, unittest.TestCase):
    """Profile names with trailing slashes or leading dots are rejected."""

    def _make_data_file(self) -> Path:
        data_dir = Path(self.tmpdir) / "data"
        data_dir.mkdir(exist_ok=True)
        p = data_dir / "data.json"
        p.write_text(json.dumps({"name": "Test User"}))
        return p

    def _assert_rejected(self, profile: str, out_name: str) -> None:
        """render --profile <profile> exits non-zero; no directory created under out root."""
        from resume.cli.main import main

        data_file = self._make_data_file()
        out_root = Path(self.tmpdir) / "out_root"
        out_root.mkdir()
        stderr_buf = io.StringIO()

        with self.in_tmpdir():
            with mock.patch("sys.stderr", stderr_buf):
                exit_code = main([
                    "render",
                    "--data", str(data_file),
                    "--profile", profile,
                    "--out-dir", str(out_root),
                    "--out", str(Path(self.tmpdir) / out_name),
                ])

        self.assertNotEqual(exit_code, 0, f"Profile {profile!r} must not exit 0")
        err_output = stderr_buf.getvalue()
        self.assertNotIn("Traceback", err_output)
        # No subdirectory should have been created under the output root
        subdirs = [p for p in out_root.iterdir() if p.is_dir()]
        self.assertEqual(subdirs, [], f"No dir should be created for bad profile {profile!r}, got {subdirs}")

    def test_trailing_slash_rejected(self):
        """Profile 'foo/' (trailing slash) exits non-zero; normalised by Path but checked in raw string."""
        self._assert_rejected("foo/", "out_trailing.docx")

    def test_leading_dot_slash_rejected(self):
        """Profile './foo' (leading ./) is rejected."""
        self._assert_rejected("./foo", "out_dotslash.docx")

    def test_dot_component_rejected(self):
        """Profile 'a/.' is rejected."""
        self._assert_rejected("a/.", "out_dotcomp.docx")

    def test_extract_with_trailing_slash_rejected(self):
        """extract --profile 'foo/' exits non-zero without creating a directory."""
        from resume.cli.main import main

        out_root = Path(self.tmpdir) / "ext_out_root"
        out_root.mkdir()
        stderr_buf = io.StringIO()

        with self.in_tmpdir():
            with mock.patch("sys.stderr", stderr_buf):
                exit_code = main([
                    "extract",
                    "--profile", "foo/",
                    "--out-dir", str(out_root),
                    "--out", str(Path(self.tmpdir) / "ext_out.json"),
                ])

        self.assertNotEqual(exit_code, 0)
        self.assertNotIn("Traceback", stderr_buf.getvalue())
        subdirs = [p for p in out_root.iterdir() if p.is_dir()]
        self.assertEqual(subdirs, [])


if __name__ == "__main__":
    unittest.main()
