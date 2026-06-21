"""Tests for phone/validate.py — iOS icon layout JSON validation."""
from __future__ import annotations

import unittest

from phone.validate import ValidationIssue, validate_layout_json


def _make_valid_layout() -> list:
    """Return a minimal valid layout: dock + one page with a proper folder."""
    dock = ["com.apple.mobilesafari", "com.apple.mobilemail"]
    page1 = [
        "com.apple.weather",
        "com.apple.Maps",
        [
            "Work",
            ["com.microsoft.skype.teams", "com.google.Docs"],
            ["com.google.Drive", "com.slack.Slack"],
        ],
    ]
    return [dock, page1]


def _errors(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.level == "error"]


def _warnings(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.level == "warning"]


class TestValidLayoutPasses(unittest.TestCase):
    """A well-formed layout produces no issues."""

    def test_valid_layout_no_issues(self):
        layout = _make_valid_layout()
        issues = validate_layout_json(layout)
        self.assertEqual(issues, [])

    def test_valid_layout_with_multiple_pages(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps", "com.apple.weather"]
        page2 = [
            ["Finance", ["com.td.tdiphoneapp", "com.citigroup.citimobile"]],
        ]
        issues = validate_layout_json([dock, page1, page2])
        self.assertEqual(issues, [])


class TestFlatFolderFormatError(unittest.TestCase):
    """Folder items that are strings (not lists) must be flagged as errors."""

    def test_flat_folder_strings_raise_error(self):
        # Wrong format: ["FolderName", "app1", "app2"] instead of ["FolderName", [apps]]
        dock = ["com.apple.mobilesafari"]
        page1 = [
            [
                "Work",
                "com.microsoft.skype.teams",   # flat string — wrong format
                "com.google.Docs",
            ]
        ]
        issues = validate_layout_json([dock, page1])
        errors = _errors(issues)
        self.assertTrue(
            any("flat string" in i.message or "pages must be lists" in i.message for i in errors),
            f"Expected flat-folder error, got: {[i.message for i in errors]}",
        )

    def test_mixed_flat_and_list_folder_pages(self):
        dock = ["com.apple.mobilesafari"]
        page1 = [
            [
                "Hybrid",
                ["com.google.Docs"],          # correct
                "com.microsoft.skype.teams",  # wrong — flat string
            ]
        ]
        issues = validate_layout_json([dock, page1])
        self.assertTrue(any(i.level == "error" for i in issues))


class TestDockAppInFolderError(unittest.TestCase):
    """An app that appears in both dock and a folder is an error."""

    def test_dock_app_in_folder_raises_error(self):
        dock = ["com.apple.mobilesafari", "com.apple.mobilemail"]
        page1 = [
            [
                "Work",
                ["com.apple.mobilesafari", "com.google.Docs"],  # safari also in dock
            ]
        ]
        issues = validate_layout_json([dock, page1])
        errors = _errors(issues)
        self.assertTrue(
            any("dock" in i.message and "com.apple.mobilesafari" in i.message for i in errors),
            f"Expected dock-collision error, got: {[i.message for i in errors]}",
        )

    def test_dock_app_on_flat_page_raises_error(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.mobilesafari", "com.apple.Maps"]  # dupe from dock
        issues = validate_layout_json([dock, page1])
        errors = _errors(issues)
        self.assertTrue(
            any("dock" in i.message and "com.apple.mobilesafari" in i.message for i in errors),
            f"Expected dock-collision error, got: {[i.message for i in errors]}",
        )


class TestDuplicateAppWarning(unittest.TestCase):
    """An app appearing more than once across the layout should produce a warning."""

    def test_duplicate_bundle_id_warns(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps", "com.apple.weather"]
        page2 = ["com.apple.Maps"]  # duplicate
        issues = validate_layout_json([dock, page1, page2])
        warnings = _warnings(issues)
        self.assertTrue(
            any("duplicate" in i.message and "com.apple.Maps" in i.message for i in warnings),
            f"Expected duplicate warning, got: {[i.message for i in warnings]}",
        )

    def test_no_false_positive_for_unique_apps(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps", "com.apple.weather"]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("duplicate" in i.message for i in issues))


class TestFolderPageTooLargeWarning(unittest.TestCase):
    """A folder page with >9 apps should trigger a warning."""

    def test_folder_page_over_9_apps_warns(self):
        dock = ["com.apple.mobilesafari"]
        ten_apps = [f"com.example.app{i}" for i in range(10)]
        page1 = [["BigFolder", ten_apps]]
        issues = validate_layout_json([dock, page1])
        warnings = _warnings(issues)
        self.assertTrue(
            any("BigFolder" in i.message and "10" in i.message for i in warnings),
            f"Expected folder page size warning, got: {[i.message for i in warnings]}",
        )

    def test_folder_page_exactly_9_apps_ok(self):
        dock = ["com.apple.mobilesafari"]
        nine_apps = [f"com.example.app{i}" for i in range(9)]
        page1 = [["NineFolder", nine_apps]]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("NineFolder" in i.message and "apps" in i.message for i in _warnings(issues)))


class TestUnplacedDeviceAppWarning(unittest.TestCase):
    """Apps present on the device but absent from the layout should produce a warning."""

    def test_unplaced_device_app_warns(self):
        layout = _make_valid_layout()
        device_apps = ["com.example.unplaced", "com.apple.mobilesafari"]
        issues = validate_layout_json(layout, device_apps=device_apps)
        warnings = _warnings(issues)
        self.assertTrue(
            any("com.example.unplaced" in i.message for i in warnings),
            f"Expected unplaced-app warning, got: {[i.message for i in warnings]}",
        )

    def test_all_placed_device_apps_no_warning(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps"]
        layout = [dock, page1]
        device_apps = ["com.apple.mobilesafari", "com.apple.Maps"]
        issues = validate_layout_json(layout, device_apps=device_apps)
        self.assertFalse(any("not placed" in i.message for i in issues))

    def test_device_apps_none_skips_check(self):
        layout = _make_valid_layout()
        issues = validate_layout_json(layout, device_apps=None)
        self.assertFalse(any("not placed" in i.message for i in issues))


class TestLayoutStructuralErrors(unittest.TestCase):
    """Edge cases for top-level structural validation."""

    def test_not_a_list_returns_error(self):
        issues = validate_layout_json({"dock": [], "pages": []})
        self.assertTrue(any(i.level == "error" for i in issues))

    def test_empty_list_returns_error(self):
        issues = validate_layout_json([])
        self.assertTrue(any(i.level == "error" for i in issues))

    def test_only_dock_no_pages_returns_error(self):
        issues = validate_layout_json([["com.apple.mobilesafari"]])
        self.assertTrue(any(i.level == "error" for i in issues))

    def test_dock_over_4_items_returns_error(self):
        dock = [f"com.apple.app{i}" for i in range(5)]
        page1 = ["com.apple.Maps"]
        issues = validate_layout_json([dock, page1])
        errors = _errors(issues)
        self.assertTrue(any("dock" in i.message and "max" in i.message for i in errors))


if __name__ == "__main__":
    unittest.main()
