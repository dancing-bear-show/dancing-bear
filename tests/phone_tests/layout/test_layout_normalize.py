"""Tests for phone/layout_normalize.py — normalization helpers."""

from __future__ import annotations

import unittest

from phone.layout_normalize import (
    NormalizedLayout,
    _extract_bundle_id,
    _flatten_folder_iconlists,
    _get_app_id,
    _get_folder_apps,
    _get_folder_name,
    _is_app_item,
    _is_folder,
    _is_folder_item,
    normalize_iconstate,
    to_yaml_export,
)
from tests.phone_tests.fixtures import (
    APP_NO_ID,
    SAMPLE_APP,
    SAMPLE_FOLDER,
    UNNAMED_FOLDER,
    WIDGET_ITEM,
    make_app_item,
    make_folder_item,
    make_iconstate,
    make_iconstate_app,
    make_iconstate_folder,
    make_layout,
)


class TestExtractBundleId(unittest.TestCase):
    """Tests for _extract_bundle_id helper."""

    def test_dict_with_bundle_identifier(self):
        item = {"bundleIdentifier": "com.apple.Safari"}
        self.assertEqual(_extract_bundle_id(item), "com.apple.Safari")

    def test_dict_with_display_identifier(self):
        item = {"displayIdentifier": "com.example.app"}
        self.assertEqual(_extract_bundle_id(item), "com.example.app")

    def test_dict_prefers_bundle_identifier_over_display(self):
        item = {"bundleIdentifier": "com.first", "displayIdentifier": "com.second"}
        self.assertEqual(_extract_bundle_id(item), "com.first")

    def test_dict_with_empty_bundle_identifier(self):
        item = {"bundleIdentifier": "", "displayIdentifier": "com.fallback"}
        self.assertEqual(_extract_bundle_id(item), "com.fallback")

    def test_dict_with_no_identifiers(self):
        item = {"name": "Some App"}
        self.assertIsNone(_extract_bundle_id(item))

    def test_string_bundle_id(self):
        self.assertEqual(_extract_bundle_id("com.example.app"), "com.example.app")

    def test_string_with_whitespace(self):
        self.assertEqual(_extract_bundle_id("  com.example.app  "), "com.example.app")

    def test_string_without_dot_returns_none(self):
        self.assertIsNone(_extract_bundle_id("nodothere"))

    def test_string_with_slash_returns_none(self):
        self.assertIsNone(_extract_bundle_id("path/to/file.txt"))

    def test_non_dict_non_string_returns_none(self):
        self.assertIsNone(_extract_bundle_id(123))
        self.assertIsNone(_extract_bundle_id(None))
        self.assertIsNone(_extract_bundle_id([]))


class TestIsFolder(unittest.TestCase):
    """Tests for _is_folder helper."""

    def test_folder_with_iconlists_and_displayname(self):
        item = {"iconLists": [[]], "displayName": "Work"}
        self.assertTrue(_is_folder(item))

    def test_not_folder_missing_iconlists(self):
        item = {"displayName": "Work"}
        self.assertFalse(_is_folder(item))

    def test_not_folder_missing_displayname(self):
        item = {"iconLists": [[]]}
        self.assertFalse(_is_folder(item))

    def test_not_folder_if_not_dict(self):
        self.assertFalse(_is_folder("not a dict"))
        self.assertFalse(_is_folder(None))


class TestIsAppItem(unittest.TestCase):
    """Tests for _is_app_item helper."""

    def test_true_for_app(self):
        self.assertTrue(_is_app_item(SAMPLE_APP))

    def test_false_for_folder_empty_widget(self):
        self.assertFalse(_is_app_item(SAMPLE_FOLDER))
        self.assertFalse(_is_app_item({}))
        self.assertFalse(_is_app_item(WIDGET_ITEM))


class TestIsFolderItem(unittest.TestCase):
    """Tests for _is_folder_item helper."""

    def test_true_for_folder(self):
        self.assertTrue(_is_folder_item(SAMPLE_FOLDER))

    def test_false_for_app_empty_widget(self):
        self.assertFalse(_is_folder_item(SAMPLE_APP))
        self.assertFalse(_is_folder_item({}))
        self.assertFalse(_is_folder_item(WIDGET_ITEM))


class TestGetAppId(unittest.TestCase):
    """Tests for _get_app_id helper."""

    def test_returns_id_for_app(self):
        self.assertEqual(_get_app_id(SAMPLE_APP), "com.example.app")

    def test_returns_none_for_non_app(self):
        self.assertIsNone(_get_app_id(SAMPLE_FOLDER))
        self.assertIsNone(_get_app_id({}))
        self.assertIsNone(_get_app_id(APP_NO_ID))


class TestGetFolderApps(unittest.TestCase):
    """Tests for _get_folder_apps helper."""

    def test_returns_apps_for_folder(self):
        self.assertEqual(_get_folder_apps(SAMPLE_FOLDER), ["com.work.app1", "com.work.app2"])

    def test_returns_empty_for_non_folder(self):
        self.assertEqual(_get_folder_apps(SAMPLE_APP), [])
        self.assertEqual(_get_folder_apps({}), [])
        self.assertEqual(_get_folder_apps({"kind": "folder", "name": "X"}), [])


class TestGetFolderName(unittest.TestCase):
    """Tests for _get_folder_name helper."""

    def test_returns_name_for_folder(self):
        self.assertEqual(_get_folder_name(SAMPLE_FOLDER), "Work")

    def test_returns_empty_for_non_folder(self):
        self.assertEqual(_get_folder_name(SAMPLE_APP), "")
        self.assertEqual(_get_folder_name({}), "")

    def test_returns_default_for_unnamed(self):
        self.assertEqual(_get_folder_name(UNNAMED_FOLDER), "Folder")


class TestFlattenFolderIconlists(unittest.TestCase):
    """Tests for _flatten_folder_iconlists helper."""

    def test_single_page_folder(self):
        folder = make_iconstate_folder("Work", ["com.app1", "com.app2"])
        result = _flatten_folder_iconlists(folder)
        self.assertEqual(result, ["com.app1", "com.app2"])

    def test_multi_page_folder(self):
        folder = {
            "iconLists": [
                [make_iconstate_app("com.page1.app1")],
                [make_iconstate_app("com.page2.app1"), make_iconstate_app("com.page2.app2")],
            ]
        }
        result = _flatten_folder_iconlists(folder)
        self.assertEqual(result, ["com.page1.app1", "com.page2.app1", "com.page2.app2"])

    def test_empty_iconlists(self):
        folder = {"iconLists": []}
        self.assertEqual(_flatten_folder_iconlists(folder), [])

    def test_missing_iconlists(self):
        folder = {}
        self.assertEqual(_flatten_folder_iconlists(folder), [])

    def test_skips_non_list_pages(self):
        folder = {"iconLists": ["not a list", [make_iconstate_app("com.valid")]]}
        self.assertEqual(_flatten_folder_iconlists(folder), ["com.valid"])

    def test_skips_items_without_bundle_id(self):
        folder = {"iconLists": [[make_iconstate_app("com.valid"), {"name": "no id"}]]}
        self.assertEqual(_flatten_folder_iconlists(folder), ["com.valid"])


class TestNormalizeIconstate(unittest.TestCase):
    """Tests for normalize_iconstate function."""

    def test_basic_iconstate(self):
        data = make_iconstate(
            dock=["com.dock.app"],
            pages=[
                [make_iconstate_app("com.page1.app1"), make_iconstate_app("com.page1.app2")],
                [make_iconstate_app("com.page2.app1")],
            ],
        )
        layout = normalize_iconstate(data)

        self.assertEqual(layout.dock, ["com.dock.app"])
        self.assertEqual(len(layout.pages), 2)
        self.assertEqual(layout.pages[0], [
            make_app_item("com.page1.app1"),
            make_app_item("com.page1.app2"),
        ])
        self.assertEqual(layout.pages[1], [make_app_item("com.page2.app1")])

    def test_iconstate_with_folders(self):
        data = {
            "buttonBar": [],
            "iconLists": [[
                make_iconstate_app("com.standalone"),
                make_iconstate_folder("Work", ["com.work.app1"]),
            ]],
        }
        layout = normalize_iconstate(data)

        self.assertEqual(len(layout.pages), 1)
        self.assertEqual(layout.pages[0][0], make_app_item("com.standalone"))
        self.assertEqual(layout.pages[0][1], make_folder_item("Work", ["com.work.app1"]))

    def test_empty_iconstate(self):
        layout = normalize_iconstate({})
        self.assertEqual(layout.dock, [])
        self.assertEqual(layout.pages, [])

    def test_iconstate_with_string_bundle_ids(self):
        data = {
            "buttonBar": ["com.dock.string"],
            "iconLists": [["com.page.string"]],
        }
        layout = normalize_iconstate(data)
        self.assertEqual(layout.dock, ["com.dock.string"])
        self.assertEqual(layout.pages[0], [make_app_item("com.page.string")])


class TestToYamlExport(unittest.TestCase):
    """Tests for to_yaml_export function."""

    def test_basic_export(self):
        layout = make_layout(
            dock=["com.dock.app"],
            pages=[[make_app_item("com.app1"), make_app_item("com.app2")]],
        )
        export = to_yaml_export(layout)

        self.assertIn("#", export)
        self.assertEqual(export["dock"], ["com.dock.app"])
        self.assertEqual(len(export["pages"]), 1)
        self.assertEqual(export["pages"][0]["apps"], ["com.app1", "com.app2"])
        self.assertEqual(export["pages"][0]["folders"], [])

    def test_export_with_folders(self):
        layout = make_layout(
            pages=[[
                make_folder_item("Work", ["com.work1", "com.work2"]),
                make_app_item("com.standalone"),
            ]],
        )
        export = to_yaml_export(layout)

        self.assertEqual(export["pages"][0]["apps"], ["com.standalone"])
        self.assertEqual(export["pages"][0]["folders"], [
            {"name": "Work", "apps": ["com.work1", "com.work2"]}
        ])


class TestNormalizedLayoutDataclass(unittest.TestCase):
    """Tests for NormalizedLayout dataclass."""

    def test_creation(self):
        layout = NormalizedLayout(dock=["a"], pages=[[make_app_item("b")]])
        self.assertEqual(layout.dock, ["a"])
        self.assertEqual(layout.pages, [[make_app_item("b")]])

    def test_equality(self):
        l1 = NormalizedLayout(dock=["a"], pages=[])
        l2 = NormalizedLayout(dock=["a"], pages=[])
        self.assertEqual(l1, l2)

    def test_make_layout_helper(self):
        layout = make_layout(dock=["a"], pages=[[make_app_item("b")]])
        self.assertIsInstance(layout, NormalizedLayout)
        self.assertEqual(layout.dock, ["a"])


if __name__ == "__main__":
    unittest.main()
