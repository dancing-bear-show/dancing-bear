"""Coverage tests for phone/cli/cmd_layout.py.

Targets:
  - _flatten_bundle_ids (previously untested)
  - _load_optional_device_apps (previously untested)
  - _report_layout_issues (previously untested)
  - cmd_validate_layout (previously untested)
  - _update_plan_with_folders non-integer page key branch
  - cmd_auto_folders LayoutLoadError path
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures import TempDirMixin
from tests.phone_tests.cli.fixtures import make_auto_folders_args, make_args


class TestFlattenBundleIds(unittest.TestCase):
    """Tests for _flatten_bundle_ids."""

    def setUp(self):
        from phone.cli.cmd_layout import _flatten_bundle_ids

        self._fn = _flatten_bundle_ids

    def test_single_string_returns_list_with_one_element(self):
        self.assertEqual(self._fn("com.apple.safari"), ["com.apple.safari"])

    def test_flat_list_of_strings(self):
        self.assertEqual(
            self._fn(["com.apple.safari", "com.google.chrome"]),
            ["com.apple.safari", "com.google.chrome"],
        )

    def test_nested_list_flattens_recursively(self):
        result = self._fn(["com.apple.safari", ["com.google.chrome", "com.microsoft.word"]])
        self.assertEqual(result, ["com.apple.safari", "com.google.chrome", "com.microsoft.word"])

    def test_empty_list_returns_empty(self):
        self.assertEqual(self._fn([]), [])

    def test_non_string_non_list_returns_empty(self):
        self.assertEqual(self._fn(42), [])

    def test_none_returns_empty(self):
        self.assertEqual(self._fn(None), [])

    def test_deeply_nested_list(self):
        result = self._fn([["com.apple.safari", ["com.google.chrome"]]])
        self.assertEqual(result, ["com.apple.safari", "com.google.chrome"])


class TestLoadOptionalDeviceApps(unittest.TestCase):
    """Tests for _load_optional_device_apps."""

    def setUp(self):
        from phone.cli.cmd_layout import _load_optional_device_apps

        self._fn = _load_optional_device_apps

    def test_none_arg_returns_none_none(self):
        apps, err = self._fn(None)
        self.assertIsNone(apps)
        self.assertIsNone(err)

    def test_empty_string_returns_none_none(self):
        apps, err = self._fn("")
        self.assertIsNone(apps)
        self.assertIsNone(err)

    def test_missing_file_returns_none_and_error_code_2(self):
        buf = io.StringIO()
        with redirect_stderr(buf):
            apps, err = self._fn("/nonexistent/path/layout.json")
        self.assertIsNone(apps)
        self.assertEqual(err, 2)
        self.assertIn("not found", buf.getvalue())

    def test_invalid_json_returns_none_and_error_code_2(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            path = f.name
        try:
            buf = io.StringIO()
            with redirect_stderr(buf):
                apps, err = self._fn(path)
            self.assertIsNone(apps)
            self.assertEqual(err, 2)
            self.assertIn("invalid JSON", buf.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_valid_flat_list_returns_bundle_ids(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(["com.apple.safari", "com.google.chrome"], f)
            path = f.name
        try:
            apps, err = self._fn(path)
            self.assertIsNone(err)
            self.assertEqual(apps, ["com.apple.safari", "com.google.chrome"])
        finally:
            Path(path).unlink(missing_ok=True)

    def test_valid_nested_list_flattens_bundle_ids(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([["com.apple.safari"], "com.google.chrome"], f)
            path = f.name
        try:
            apps, err = self._fn(path)
            self.assertIsNone(err)
            self.assertIn("com.apple.safari", apps)
            self.assertIn("com.google.chrome", apps)
        finally:
            Path(path).unlink(missing_ok=True)


class TestReportLayoutIssues(unittest.TestCase):
    """Tests for _report_layout_issues."""

    def setUp(self):
        from phone.cli.cmd_layout import _report_layout_issues
        from phone.validate import ValidationIssue

        self._fn = _report_layout_issues
        self._Issue = ValidationIssue

    def test_no_issues_returns_zero(self):
        self.assertEqual(self._fn([]), 0)

    def test_warnings_only_returns_zero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = self._fn([self._Issue("warning", "some warning")])
        self.assertEqual(result, 0)
        self.assertIn("WARNING", buf.getvalue())

    def test_errors_returns_one(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = self._fn([self._Issue("error", "some error")])
        self.assertEqual(result, 1)
        self.assertIn("ERROR", buf.getvalue())

    def test_mixed_errors_and_warnings_returns_one(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = self._fn([self._Issue("error", "bad"), self._Issue("warning", "minor")])
        self.assertEqual(result, 1)

    def test_summary_line_counts_are_correct(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            self._fn([self._Issue("error", "e1"), self._Issue("warning", "w1")])
        output = buf.getvalue()
        self.assertIn("1 error(s)", output)
        self.assertIn("1 warning(s)", output)


class TestCmdValidateLayout(unittest.TestCase):
    """Tests for cmd_validate_layout."""

    def _make_args(self, layout: str, device_layout: str | None = None) -> MagicMock:
        return make_args(layout=layout, device_layout=device_layout)

    def test_missing_layout_file_returns_2(self):
        from phone.cli.cmd_layout import cmd_validate_layout

        buf = io.StringIO()
        with redirect_stderr(buf):
            result = cmd_validate_layout(self._make_args("/nonexistent/layout.json"))
        self.assertEqual(result, 2)
        self.assertIn("not found", buf.getvalue())

    def test_malformed_json_returns_2(self):
        from phone.cli.cmd_layout import cmd_validate_layout

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json")
            path = f.name
        try:
            buf = io.StringIO()
            with redirect_stderr(buf):
                result = cmd_validate_layout(self._make_args(path))
            self.assertEqual(result, 2)
            self.assertIn("invalid JSON", buf.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_structurally_invalid_layout_returns_1(self):
        from phone.cli.cmd_layout import cmd_validate_layout

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump("just a string", f)
            path = f.name
        try:
            result = cmd_validate_layout(self._make_args(path))
            self.assertEqual(result, 1)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_valid_layout_returns_0(self):
        from phone.cli.cmd_layout import cmd_validate_layout

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([["com.apple.safari"], ["com.apple.maps"]], f)
            path = f.name
        try:
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = cmd_validate_layout(self._make_args(path))
            self.assertEqual(result, 0)
            self.assertIn("no issues found", buf.getvalue())
        finally:
            Path(path).unlink(missing_ok=True)

    def test_device_layout_missing_file_returns_2(self):
        from phone.cli.cmd_layout import cmd_validate_layout

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump([["com.apple.safari"], ["com.apple.maps"]], f)
            layout_path = f.name
        try:
            result = cmd_validate_layout(
                self._make_args(layout_path, device_layout="/nonexistent/device.json")
            )
            self.assertEqual(result, 2)
        finally:
            Path(layout_path).unlink(missing_ok=True)

    def test_device_layout_valid_passes_apps_to_validator(self):
        from phone.cli.cmd_layout import cmd_validate_layout

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as layout_f:
            json.dump([["com.apple.safari"], ["com.apple.maps"]], layout_f)
            layout_path = layout_f.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as device_f:
            json.dump(["com.apple.safari", "com.apple.maps"], device_f)
            device_path = device_f.name
        try:
            result = cmd_validate_layout(
                self._make_args(layout_path, device_layout=device_path)
            )
            self.assertEqual(result, 0)
        finally:
            Path(layout_path).unlink(missing_ok=True)
            Path(device_path).unlink(missing_ok=True)


class TestUpdatePlanWithFolders(unittest.TestCase):
    """Tests for _update_plan_with_folders."""

    def setUp(self):
        from phone.cli.cmd_layout import _update_plan_with_folders

        self._fn = _update_plan_with_folders

    def test_non_integer_page_keys_are_skipped_not_deleted(self):
        plan = {"pins": [], "folders": {}, "pages": {"1": ["x"], "bad_key": ["y"], "2": ["z"]}}
        result = self._fn(plan, {}, start_page=2, per_page=12)
        self.assertIn("bad_key", result["pages"])
        self.assertIn("1", result["pages"])
        self.assertNotIn("2", result["pages"])

    def test_folders_stored_in_result(self):
        plan = {"pins": [], "folders": {}, "pages": {}}
        folders = {"Work": ["com.work1"], "Games": ["com.game1"]}
        result = self._fn(plan, folders, start_page=2, per_page=12)
        self.assertEqual(result["folders"], folders)

    def test_pages_before_start_page_preserved(self):
        plan = {"pins": [], "folders": {}, "pages": {"1": ["a"], "2": ["b"], "3": ["c"]}}
        result = self._fn(plan, {}, start_page=2, per_page=12)
        self.assertIn("1", result["pages"])
        self.assertNotIn("2", result["pages"])
        self.assertNotIn("3", result["pages"])

    def test_returns_same_plan_object_mutated_in_place(self):
        plan = {"pins": [], "folders": {}, "pages": {}}
        result = self._fn(plan, {}, start_page=2, per_page=12)
        self.assertIs(result, plan)

    def test_none_pages_treated_as_empty_dict(self):
        plan = {"pins": [], "folders": {}, "pages": None}
        result = self._fn(plan, {}, start_page=2, per_page=12)
        self.assertIsInstance(result["pages"], dict)


class TestCmdAutoFolders(TempDirMixin, unittest.TestCase):
    """Tests for cmd_auto_folders."""

    def test_layout_load_error_code_1_returned(self):
        from phone.helpers import LayoutLoadError
        from phone.cli.cmd_layout import cmd_auto_folders

        with patch("phone.cli.cmd_layout.load_layout", side_effect=LayoutLoadError(1, "no layout")):
            args = make_auto_folders_args(
                layout=None,
                backup=None,
                plan=str(Path(self.tmpdir) / "plan.yaml"),
            )
            buf = io.StringIO()
            with redirect_stderr(buf):
                result = cmd_auto_folders(args)
        self.assertEqual(result, 1)

    def test_layout_load_error_code_2_returned(self):
        from phone.helpers import LayoutLoadError
        from phone.cli.cmd_layout import cmd_auto_folders

        with patch("phone.cli.cmd_layout.load_layout", side_effect=LayoutLoadError(2, "no backup")):
            args = make_auto_folders_args(
                layout=None,
                backup=None,
                plan=str(Path(self.tmpdir) / "plan.yaml"),
            )
            buf = io.StringIO()
            with redirect_stderr(buf):
                result = cmd_auto_folders(args)
        self.assertEqual(result, 2)

    def test_success_writes_plan_and_returns_0(self):
        from phone.cli.cmd_layout import cmd_auto_folders
        from tests.phone_tests.fixtures import make_layout, make_app_item

        layout = make_layout(
            dock=["com.apple.safari"],
            pages=[[make_app_item("com.app1"), make_app_item("com.app2")]],
        )
        plan_path = Path(self.tmpdir) / "test.plan.yaml"

        with patch("phone.cli.cmd_layout.load_layout", return_value=layout):
            args = make_auto_folders_args(
                layout="fake.yaml",
                backup=None,
                plan=str(plan_path),
                keep="",
                place_folders_from_page=2,
                folders_per_page=12,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                result = cmd_auto_folders(args)
        self.assertEqual(result, 0)
        self.assertTrue(plan_path.exists())


if __name__ == "__main__":
    unittest.main()
