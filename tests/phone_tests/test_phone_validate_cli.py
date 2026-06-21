"""Tests for the validate-layout subcommand.

Covers two layers:
1. In-process unit tests of ``cmd_validate_layout`` and ``_flatten_bundle_ids``
   (using MagicMock args + temp files) — these drive coverage on
   phone/cli/main.py lines 233-288.
2. Subprocess integration tests via ``./bin/phone-assistant validate-layout``
   that confirm end-to-end behaviour.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures import bin_path, repo_root, run


def _write_json(data: object, directory: str, filename: str = "layout.json") -> str:
    """Write JSON data to a temp file; return the path as a string."""
    p = Path(directory) / filename
    p.write_text(json.dumps(data))
    return str(p)


def _valid_layout() -> list:
    """Return a minimal valid layout suitable for JSON serialisation."""
    dock = ["com.apple.mobilesafari", "com.apple.mobilemail"]
    page1 = [
        "com.apple.weather",
        ["Work", ["com.microsoft.skype.teams", "com.google.Docs"]],
    ]
    return [dock, page1]


def _make_args(layout: str, device_layout: str | None = None) -> MagicMock:
    """Build a MagicMock args object for cmd_validate_layout."""
    args = MagicMock()
    args.layout = layout
    args.device_layout = device_layout
    return args


class TestCmdValidateLayoutUnit(unittest.TestCase):
    """In-process unit tests for phone.cli.main.cmd_validate_layout."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _layout_path(self, data: object, name: str = "layout.json") -> str:
        p = Path(self.tmpdir) / name
        p.write_text(json.dumps(data))
        return str(p)

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_valid_layout_returns_0(self):
        from phone.cli.main import cmd_validate_layout

        path = self._layout_path(_valid_layout())
        args = _make_args(path)
        with patch("sys.stdout", new_callable=StringIO):
            result = cmd_validate_layout(args)
        self.assertEqual(result, 0)

    def test_valid_layout_prints_ok(self):
        from phone.cli.main import cmd_validate_layout

        path = self._layout_path(_valid_layout())
        args = _make_args(path)
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            cmd_validate_layout(args)
            self.assertIn("OK", mock_out.getvalue())

    def test_warnings_only_returns_0(self):
        from phone.cli.main import cmd_validate_layout

        dock = ["com.apple.mobilesafari"]
        path = self._layout_path([dock, ["com.apple.Maps", "com.apple.Maps"]])
        args = _make_args(path)
        with patch("sys.stdout", new_callable=StringIO):
            result = cmd_validate_layout(args)
        self.assertEqual(result, 0)

    def test_errors_returns_1(self):
        from phone.cli.main import cmd_validate_layout

        dock = [f"com.apple.app{i}" for i in range(5)]
        path = self._layout_path([dock, ["com.apple.Maps"]])
        args = _make_args(path)
        with patch("sys.stdout", new_callable=StringIO):
            result = cmd_validate_layout(args)
        self.assertEqual(result, 1)

    def test_errors_prints_error_and_summary(self):
        from phone.cli.main import cmd_validate_layout

        dock = [f"com.apple.app{i}" for i in range(5)]
        path = self._layout_path([dock, ["com.apple.Maps"]])
        args = _make_args(path)
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            cmd_validate_layout(args)
            output = mock_out.getvalue()
        self.assertIn("ERROR", output)
        self.assertIn("error(s)", output)

    # ------------------------------------------------------------------
    # Error paths (file not found / bad JSON)
    # ------------------------------------------------------------------

    def test_layout_not_found_returns_2(self):
        from phone.cli.main import cmd_validate_layout

        args = _make_args("/nonexistent/layout.json")
        with patch("sys.stderr", new_callable=StringIO):
            result = cmd_validate_layout(args)
        self.assertEqual(result, 2)

    def test_layout_not_found_prints_to_stderr(self):
        from phone.cli.main import cmd_validate_layout

        args = _make_args("/nonexistent/layout.json")
        with patch("sys.stderr", new_callable=StringIO) as mock_err:
            cmd_validate_layout(args)
            self.assertIn("Error", mock_err.getvalue())

    def test_invalid_json_returns_2(self):
        from phone.cli.main import cmd_validate_layout

        bad = Path(self.tmpdir) / "bad.json"
        bad.write_text("{not json")
        args = _make_args(str(bad))
        with patch("sys.stderr", new_callable=StringIO):
            result = cmd_validate_layout(args)
        self.assertEqual(result, 2)

    def test_invalid_json_prints_to_stderr(self):
        from phone.cli.main import cmd_validate_layout

        bad = Path(self.tmpdir) / "bad.json"
        bad.write_text("{not json")
        args = _make_args(str(bad))
        with patch("sys.stderr", new_callable=StringIO) as mock_err:
            cmd_validate_layout(args)
            self.assertIn("Error", mock_err.getvalue())

    # ------------------------------------------------------------------
    # device-layout paths
    # ------------------------------------------------------------------

    def test_device_layout_not_found_returns_2(self):
        from phone.cli.main import cmd_validate_layout

        layout_path = self._layout_path(_valid_layout())
        args = _make_args(layout_path, device_layout="/nonexistent/device.json")
        with patch("sys.stderr", new_callable=StringIO):
            result = cmd_validate_layout(args)
        self.assertEqual(result, 2)

    def test_device_layout_invalid_json_returns_2(self):
        from phone.cli.main import cmd_validate_layout

        layout_path = self._layout_path(_valid_layout())
        bad_device = Path(self.tmpdir) / "device.json"
        bad_device.write_text("{bad")
        args = _make_args(layout_path, device_layout=str(bad_device))
        with patch("sys.stderr", new_callable=StringIO):
            result = cmd_validate_layout(args)
        self.assertEqual(result, 2)

    def test_device_layout_with_unplaced_app_warns(self):
        from phone.cli.main import cmd_validate_layout

        layout_path = self._layout_path(_valid_layout())
        device_layout = [["com.apple.mobilesafari"], ["com.example.unplaced"]]
        device_path = self._layout_path(device_layout, "device.json")
        args = _make_args(layout_path, device_layout=device_path)
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            result = cmd_validate_layout(args)
            output = mock_out.getvalue()
        # warnings → exit 0
        self.assertEqual(result, 0)
        self.assertIn("WARNING", output)

    def test_device_layout_all_placed_exits_ok(self):
        from phone.cli.main import cmd_validate_layout

        layout_path = self._layout_path(_valid_layout())
        # Device contains only apps that are in the layout
        device_layout = [["com.apple.mobilesafari"]]
        device_path = self._layout_path(device_layout, "device.json")
        args = _make_args(layout_path, device_layout=device_path)
        with patch("sys.stdout", new_callable=StringIO) as mock_out:
            result = cmd_validate_layout(args)
        self.assertEqual(result, 0)


class TestFlattenBundleIds(unittest.TestCase):
    """Unit tests for phone.cli.main._flatten_bundle_ids (lines 280-288)."""

    def test_flat_list_of_strings(self):
        from phone.cli.main import _flatten_bundle_ids

        result = _flatten_bundle_ids(["com.a.b", "com.c.d"])
        self.assertEqual(result, ["com.a.b", "com.c.d"])

    def test_bare_string_returns_single_item(self):
        from phone.cli.main import _flatten_bundle_ids

        result = _flatten_bundle_ids("com.a.b")
        self.assertEqual(result, ["com.a.b"])

    def test_nested_list_flattened(self):
        from phone.cli.main import _flatten_bundle_ids

        nested = [["com.a.b", "com.c.d"], ["com.e.f"]]
        result = _flatten_bundle_ids(nested)
        self.assertEqual(result, ["com.a.b", "com.c.d", "com.e.f"])

    def test_deeply_nested_list(self):
        from phone.cli.main import _flatten_bundle_ids

        deep = [[["com.deep.app"]]]
        result = _flatten_bundle_ids(deep)
        self.assertEqual(result, ["com.deep.app"])

    def test_empty_list_returns_empty(self):
        from phone.cli.main import _flatten_bundle_ids

        result = _flatten_bundle_ids([])
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 0)

    def test_integer_ignored(self):
        from phone.cli.main import _flatten_bundle_ids

        # Integers are neither str nor list — silently ignored
        result = _flatten_bundle_ids(42)
        self.assertEqual(result, [])

    def test_mixed_strings_and_lists(self):
        from phone.cli.main import _flatten_bundle_ids

        mixed = ["com.a.b", ["com.c.d", "com.e.f"]]
        result = _flatten_bundle_ids(mixed)
        self.assertEqual(result, ["com.a.b", "com.c.d", "com.e.f"])


class TestValidateLayoutCLI(unittest.TestCase):
    """Subprocess tests for the validate-layout CLI command."""

    def setUp(self):
        self.root = str(repo_root())
        self.wrapper = bin_path("phone-assistant")
        self.assertTrue(self.wrapper.exists(), "bin/phone-assistant not found")
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmpdir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _run(self, *extra_args: str):
        cmd = [sys.executable, str(self.wrapper), "validate-layout"] + list(extra_args)
        return run(cmd, cwd=self.root)

    # ------------------------------------------------------------------
    # Happy paths
    # ------------------------------------------------------------------

    def test_valid_layout_exits_zero(self):
        path = _write_json(_valid_layout(), self.tmpdir)
        proc = self._run("--layout", path)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_valid_layout_prints_ok(self):
        path = _write_json(_valid_layout(), self.tmpdir)
        proc = self._run("--layout", path)
        self.assertIn("OK", proc.stdout)

    def test_warnings_only_exits_zero(self):
        # A layout with a duplicate app → warning but no error → exit 0
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps", "com.apple.Maps"]  # duplicate
        path = _write_json([dock, page1], self.tmpdir)
        proc = self._run("--layout", path)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("WARNING", proc.stdout)

    def test_warnings_summary_line_printed(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps", "com.apple.Maps"]
        path = _write_json([dock, page1], self.tmpdir)
        proc = self._run("--layout", path)
        # summary line: "0 error(s), 1 warning(s)"
        self.assertIn("error(s)", proc.stdout)
        self.assertIn("warning(s)", proc.stdout)

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    def test_layout_file_not_found_exits_2(self):
        proc = self._run("--layout", "/nonexistent/layout.json")
        self.assertEqual(proc.returncode, 2, msg=proc.stdout)

    def test_layout_file_not_found_prints_error(self):
        proc = self._run("--layout", "/nonexistent/layout.json")
        self.assertIn("Error", proc.stderr)

    def test_invalid_json_exits_2(self):
        bad_json = Path(self.tmpdir) / "bad.json"
        bad_json.write_text("{not valid json")
        proc = self._run("--layout", str(bad_json))
        self.assertEqual(proc.returncode, 2, msg=proc.stdout)

    def test_invalid_json_prints_error(self):
        bad_json = Path(self.tmpdir) / "bad.json"
        bad_json.write_text("{not valid json")
        proc = self._run("--layout", str(bad_json))
        self.assertIn("Error", proc.stderr)

    def test_layout_with_errors_exits_1(self):
        # Dock has 5 items (over the max of 4) → error → exit 1
        dock = [f"com.apple.app{i}" for i in range(5)]
        page1 = ["com.apple.Maps"]
        path = _write_json([dock, page1], self.tmpdir)
        proc = self._run("--layout", path)
        self.assertEqual(proc.returncode, 1, msg=proc.stderr)

    def test_layout_with_errors_prints_error_lines(self):
        dock = [f"com.apple.app{i}" for i in range(5)]
        page1 = ["com.apple.Maps"]
        path = _write_json([dock, page1], self.tmpdir)
        proc = self._run("--layout", path)
        self.assertIn("ERROR", proc.stdout)

    def test_layout_not_a_list_exits_1(self):
        # JSON object at root is not a list → structural error → exit 1
        path = _write_json({"dock": [], "pages": []}, self.tmpdir)
        proc = self._run("--layout", path)
        self.assertEqual(proc.returncode, 1, msg=proc.stderr)

    # ------------------------------------------------------------------
    # device-layout flag
    # ------------------------------------------------------------------

    def test_device_layout_not_found_exits_2(self):
        layout_path = _write_json(_valid_layout(), self.tmpdir)
        proc = self._run("--layout", layout_path, "--device-layout", "/nonexistent/device.json")
        self.assertEqual(proc.returncode, 2, msg=proc.stdout)

    def test_device_layout_not_found_prints_error(self):
        layout_path = _write_json(_valid_layout(), self.tmpdir)
        proc = self._run("--layout", layout_path, "--device-layout", "/nonexistent/device.json")
        self.assertIn("Error", proc.stderr)

    def test_device_layout_invalid_json_exits_2(self):
        layout_path = _write_json(_valid_layout(), self.tmpdir)
        bad_device = Path(self.tmpdir) / "device.json"
        bad_device.write_text("{bad")
        proc = self._run("--layout", layout_path, "--device-layout", str(bad_device))
        self.assertEqual(proc.returncode, 2, msg=proc.stdout)

    def test_device_layout_unplaced_apps_warn(self):
        # Device has an app not present in the layout → WARNING
        layout_path = _write_json(_valid_layout(), self.tmpdir)
        # Device layout contains an extra app not in the layout
        device_layout = [["com.apple.mobilesafari"], ["com.example.unplaced"]]
        device_path = _write_json(device_layout, self.tmpdir, "device.json")
        proc = self._run("--layout", layout_path, "--device-layout", device_path)
        self.assertIn("WARNING", proc.stdout)
        self.assertIn("unplaced", proc.stdout)

    def test_device_layout_all_placed_no_warning(self):
        layout_path = _write_json(_valid_layout(), self.tmpdir)
        # Device layout contains only apps that ARE in the layout
        device_layout = [["com.apple.mobilesafari"]]
        device_path = _write_json(device_layout, self.tmpdir, "device.json")
        proc = self._run("--layout", layout_path, "--device-layout", device_path)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("OK", proc.stdout)

    def test_validate_layout_in_help_output(self):
        """validate-layout subcommand appears in the main --help output."""
        proc = run(
            [sys.executable, str(self.wrapper), "--help"],
            cwd=self.root,
        )
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("validate-layout", proc.stdout)


if __name__ == "__main__":
    unittest.main()
