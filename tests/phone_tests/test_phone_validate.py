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


class TestDockNotAList(unittest.TestCase):
    """Dock that is not a list should produce an error and return early."""

    def test_dock_is_dict_produces_error(self):
        # dock must be a list; passing a dict triggers the isinstance guard (lines 44-45)
        issues = validate_layout_json([{"app": "com.apple.safari"}, ["com.apple.Maps"]])
        errors = _errors(issues)
        self.assertTrue(
            any("dock" in i.message and "must be a list" in i.message for i in errors),
            f"Expected dock-not-a-list error, got: {[i.message for i in errors]}",
        )

    def test_dock_is_string_produces_error(self):
        issues = validate_layout_json(["com.apple.safari", ["com.apple.Maps"]])
        errors = _errors(issues)
        self.assertTrue(
            any("dock" in i.message and "must be a list" in i.message for i in errors),
            f"Expected dock-not-a-list error, got: {[i.message for i in errors]}",
        )


class TestDockNonStringItem(unittest.TestCase):
    """Non-string items inside the dock list should produce an error (line 49)."""

    def test_dock_contains_integer_produces_error(self):
        # Dock item is an int, not a string — triggers line 49
        dock = [42, "com.apple.mobilesafari"]
        page1 = ["com.apple.Maps"]
        issues = validate_layout_json([dock, page1])
        errors = _errors(issues)
        self.assertTrue(
            any("dock item must be a string" in i.message and "int" in i.message for i in errors),
            f"Expected dock non-string error, got: {[i.message for i in errors]}",
        )

    def test_valid_dock_all_strings_no_type_error(self):
        dock = ["com.apple.mobilesafari", "com.apple.Maps"]
        page1 = ["com.apple.weather"]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(
            any("dock item must be a string" in i.message for i in issues),
        )


class TestInvalidBundleIdWarning(unittest.TestCase):
    """Bundle IDs without a dot should produce a warning (line 67)."""

    def test_no_dot_bundle_id_warns(self):
        # A value without a dot fails the regex — triggers line 67
        dock = ["com.apple.mobilesafari"]
        page1 = ["nodothere"]
        issues = validate_layout_json([dock, page1])
        warnings = _warnings(issues)
        self.assertTrue(
            any("nodothere" in i.message and "does not look like a bundle ID" in i.message for i in warnings),
            f"Expected invalid bundle ID warning, got: {[i.message for i in warnings]}",
        )

    def test_valid_bundle_id_no_warning(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps"]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("does not look like a bundle ID" in i.message for i in issues))


class TestEmptyFolderPage(unittest.TestCase):
    """An empty folder page should produce a warning (line 88)."""

    def test_empty_folder_page_warns(self):
        dock = ["com.apple.mobilesafari"]
        page1 = [["EmptyFolder", []]]
        issues = validate_layout_json([dock, page1])
        warnings = _warnings(issues)
        self.assertTrue(
            any("EmptyFolder" in i.message and "empty" in i.message for i in warnings),
            f"Expected empty-folder-page warning, got: {[i.message for i in warnings]}",
        )

    def test_non_empty_folder_page_no_empty_warning(self):
        dock = ["com.apple.mobilesafari"]
        page1 = [["Folder", ["com.apple.Maps"]]]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("empty" in i.message for i in issues))


class TestFolderPageNonStringApp(unittest.TestCase):
    """Non-string items inside a folder page are silently skipped (branch 91->90)."""

    def test_integer_in_folder_page_is_skipped(self):
        # An int inside a folder page doesn't raise an error — it just isn't validated
        # (the isinstance(app, str) guard on line 91 skips non-strings)
        dock = ["com.apple.mobilesafari"]
        page1 = [["MyFolder", [42, "com.apple.Maps"]]]
        issues = validate_layout_json([dock, page1])
        # No crash; the integer is silently skipped — only valid apps count
        errors = _errors(issues)
        self.assertFalse(
            any("MyFolder" in i.message and "string" in i.message for i in errors),
        )


class TestFolderStructuralErrors(unittest.TestCase):
    """Structural errors inside folder elements (lines 103-104, 107-111)."""

    def test_folder_not_a_list_produces_error(self):
        # A non-list, non-string item on a page triggers _validate_folder with a non-list
        # (lines 103-104: folder must be a non-empty list)
        dock = ["com.apple.mobilesafari"]
        # Pass an empty list as a folder — []  triggers the len < 1 guard
        page1 = [[]]
        issues = validate_layout_json([dock, page1])
        errors = _errors(issues)
        self.assertTrue(
            any("folder must be a non-empty list" in i.message for i in errors),
            f"Expected empty-folder-list error, got: {[i.message for i in errors]}",
        )

    def test_folder_first_element_not_string_produces_error(self):
        # folder[0] is not a string — triggers lines 107-111
        dock = ["com.apple.mobilesafari"]
        page1 = [[42, ["com.apple.Maps"]]]
        issues = validate_layout_json([dock, page1])
        errors = _errors(issues)
        self.assertTrue(
            any("folder first element must be a string name" in i.message for i in errors),
            f"Expected folder-first-element error, got: {[i.message for i in errors]}",
        )

    def test_valid_folder_no_structural_error(self):
        dock = ["com.apple.mobilesafari"]
        page1 = [["Work", ["com.google.Docs"]]]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("folder must be a non-empty list" in i.message for i in issues))
        self.assertFalse(any("folder first element" in i.message for i in issues))


class TestFolderItemUnexpectedType(unittest.TestCase):
    """A folder item that is neither a string nor a list produces a warning (line 125)."""

    def test_folder_item_integer_warns(self):
        dock = ["com.apple.mobilesafari"]
        # folder item at index 1 is an int, not a str or list
        page1 = [["MyFolder", 99]]
        issues = validate_layout_json([dock, page1])
        warnings = _warnings(issues)
        self.assertTrue(
            any("MyFolder" in i.message and "unexpected type" in i.message for i in warnings),
            f"Expected unexpected-type warning, got: {[i.message for i in warnings]}",
        )

    def test_folder_item_list_or_string_no_unexpected_warning(self):
        dock = ["com.apple.mobilesafari"]
        page1 = [["MyFolder", ["com.apple.Maps"]]]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("unexpected type" in i.message for i in issues))


class TestPageItemUnexpectedType(unittest.TestCase):
    """Non-string, non-list items on a page produce a warning (line 144)."""

    def test_integer_on_page_warns(self):
        dock = ["com.apple.mobilesafari"]
        page1 = [42]
        issues = validate_layout_json([dock, page1])
        warnings = _warnings(issues)
        self.assertTrue(
            any("unexpected item type" in i.message for i in warnings),
            f"Expected unexpected-item-type warning, got: {[i.message for i in warnings]}",
        )

    def test_string_on_page_no_unexpected_warning(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps"]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("unexpected item type" in i.message for i in issues))


class TestPageAsString(unittest.TestCase):
    """A page that is a bare string (not a list) is treated as a single bundle ID (line 159)."""

    def test_page_as_string_validates_bundle_id(self):
        # A page can be a bare string — it's treated as a single app
        dock = ["com.apple.mobilesafari"]
        issues = validate_layout_json([dock, "com.apple.Maps"])
        # Valid bundle ID — no issues expected
        self.assertEqual(issues, [])

    def test_page_as_invalid_string_warns(self):
        dock = ["com.apple.mobilesafari"]
        # A bare string page with no dot triggers the bundle-ID warning
        issues = validate_layout_json([dock, "nodothere"])
        warnings = _warnings(issues)
        self.assertTrue(
            any("nodothere" in i.message and "does not look like" in i.message for i in warnings),
            f"Expected invalid-bundle-id warning for bare string page, got: {[i.message for i in warnings]}",
        )


class TestPageUnexpectedType(unittest.TestCase):
    """A page that is neither a string nor a list produces an error (line 164)."""

    def test_integer_page_produces_error(self):
        dock = ["com.apple.mobilesafari"]
        # An integer as a page triggers the else branch (line 164)
        issues = validate_layout_json([dock, 42])
        errors = _errors(issues)
        self.assertTrue(
            any("must be a string or list" in i.message for i in errors),
            f"Expected page-type error, got: {[i.message for i in errors]}",
        )

    def test_dict_page_produces_error(self):
        dock = ["com.apple.mobilesafari"]
        issues = validate_layout_json([dock, {"app": "com.apple.Maps"}])
        errors = _errors(issues)
        self.assertTrue(
            any("must be a string or list" in i.message for i in errors),
            f"Expected page-type error, got: {[i.message for i in errors]}",
        )

    def test_list_page_no_type_error(self):
        dock = ["com.apple.mobilesafari"]
        page1 = ["com.apple.Maps"]
        issues = validate_layout_json([dock, page1])
        self.assertFalse(any("must be a string or list" in i.message for i in issues))


if __name__ == "__main__":
    unittest.main()
