"""Tests for phone/layout.py layout parsing and manipulation."""

import unittest

from phone.layout import (
    NormalizedLayout,
    _flatten_folder_iconlists,
    _extract_bundle_id,
    _is_folder,
    normalize_iconstate,
    to_yaml_export,
    scaffold_plan,
    compute_location_map,
    list_all_apps,
    compute_folder_page_map,
    compute_root_app_page_map,
    analyze_layout,
    checklist_from_plan,
    rank_unused_candidates,
    distribute_folders_across_pages,
)


class TestNormalizedLayout(unittest.TestCase):
    """Tests for NormalizedLayout dataclass."""

    def test_create_empty_layout(self):
        layout = NormalizedLayout(dock=[], pages=[])
        self.assertEqual(layout.dock, [])
        self.assertEqual(layout.pages, [])

    def test_create_layout_with_data(self):
        dock = ["com.apple.mobilesafari", "com.apple.mobilemail"]
        pages = [[{"kind": "app", "id": "com.example.app"}]]
        layout = NormalizedLayout(dock=dock, pages=pages)
        self.assertEqual(layout.dock, dock)
        self.assertEqual(layout.pages, pages)


class TestExtractBundleId(unittest.TestCase):
    """Tests for _extract_bundle_id function."""

    def test_dict_with_bundleIdentifier(self):
        item = {"bundleIdentifier": "com.apple.mobilesafari"}
        result = _extract_bundle_id(item)
        self.assertEqual(result, "com.apple.mobilesafari")

    def test_dict_with_displayIdentifier(self):
        item = {"displayIdentifier": "com.example.app"}
        result = _extract_bundle_id(item)
        self.assertEqual(result, "com.example.app")

    def test_bundleIdentifier_takes_priority(self):
        item = {
            "bundleIdentifier": "com.apple.first",
            "displayIdentifier": "com.apple.second",
        }
        result = _extract_bundle_id(item)
        self.assertEqual(result, "com.apple.first")

    def test_string_bundle_id(self):
        result = _extract_bundle_id("com.example.myapp")
        self.assertEqual(result, "com.example.myapp")

    def test_string_with_whitespace(self):
        result = _extract_bundle_id("  com.example.app  ")
        self.assertEqual(result, "com.example.app")

    def test_string_without_dot_returns_none(self):
        result = _extract_bundle_id("notabundleid")
        self.assertIsNone(result)

    def test_string_with_slash_returns_none(self):
        result = _extract_bundle_id("path/to/something.app")
        self.assertIsNone(result)

    def test_empty_dict_returns_none(self):
        result = _extract_bundle_id({})
        self.assertIsNone(result)

    def test_none_returns_none(self):
        result = _extract_bundle_id(None)
        self.assertIsNone(result)

    def test_empty_string_key_returns_none(self):
        item = {"bundleIdentifier": ""}
        result = _extract_bundle_id(item)
        self.assertIsNone(result)


class TestIsFolder(unittest.TestCase):
    """Tests for _is_folder function."""

    def test_valid_folder(self):
        item = {"displayName": "Work", "iconLists": [[{"bundleIdentifier": "com.app"}]]}
        self.assertTrue(_is_folder(item))

    def test_missing_displayName(self):
        item = {"iconLists": [[]]}
        self.assertFalse(_is_folder(item))

    def test_missing_iconLists(self):
        item = {"displayName": "Work"}
        self.assertFalse(_is_folder(item))

    def test_app_item(self):
        item = {"bundleIdentifier": "com.example.app"}
        self.assertFalse(_is_folder(item))

    def test_non_dict_returns_false(self):
        self.assertFalse(_is_folder("string"))
        self.assertFalse(_is_folder(123))


class TestFlattenFolderIconlists(unittest.TestCase):
    """Tests for _flatten_folder_iconlists function."""

    def test_flatten_single_page(self):
        folder = {
            "displayName": "Work",
            "iconLists": [[
                {"bundleIdentifier": "com.app.one"},
                {"bundleIdentifier": "com.app.two"},
            ]]
        }
        result = _flatten_folder_iconlists(folder)
        self.assertEqual(result, ["com.app.one", "com.app.two"])

    def test_flatten_multiple_pages(self):
        folder = {
            "displayName": "Utilities",
            "iconLists": [
                [{"bundleIdentifier": "com.app.one"}],
                [{"bundleIdentifier": "com.app.two"}],
            ]
        }
        result = _flatten_folder_iconlists(folder)
        self.assertEqual(result, ["com.app.one", "com.app.two"])

    def test_empty_iconLists(self):
        folder = {"displayName": "Empty", "iconLists": []}
        result = _flatten_folder_iconlists(folder)
        self.assertEqual(result, [])

    def test_missing_iconLists(self):
        folder = {"displayName": "NoList"}
        result = _flatten_folder_iconlists(folder)
        self.assertEqual(result, [])

    def test_skips_invalid_items(self):
        folder = {
            "iconLists": [
                [
                    {"bundleIdentifier": "com.valid.app"},
                    {"other": "data"},
                    None,
                ]
            ]
        }
        result = _flatten_folder_iconlists(folder)
        self.assertEqual(result, ["com.valid.app"])


class TestNormalizeIconstate(unittest.TestCase):
    """Tests for normalize_iconstate function."""

    def test_normalize_basic_layout(self):
        data = {
            "buttonBar": [
                {"bundleIdentifier": "com.apple.mobilesafari"},
                {"bundleIdentifier": "com.apple.mobilemail"},
            ],
            "iconLists": [[
                {"bundleIdentifier": "com.example.app1"},
                {"bundleIdentifier": "com.example.app2"},
            ]]
        }
        result = normalize_iconstate(data)
        self.assertEqual(result.dock, ["com.apple.mobilesafari", "com.apple.mobilemail"])
        self.assertEqual(len(result.pages), 1)
        self.assertEqual(len(result.pages[0]), 2)
        self.assertEqual(result.pages[0][0]["kind"], "app")
        self.assertEqual(result.pages[0][0]["id"], "com.example.app1")

    def test_normalize_with_folders(self):
        data = {
            "buttonBar": [],
            "iconLists": [[
                {
                    "displayName": "Work",
                    "iconLists": [[{"bundleIdentifier": "com.work.app"}]],
                }
            ]]
        }
        result = normalize_iconstate(data)
        self.assertEqual(len(result.pages[0]), 1)
        item = result.pages[0][0]
        self.assertEqual(item["kind"], "folder")
        self.assertEqual(item["name"], "Work")
        self.assertEqual(item["apps"], ["com.work.app"])

    def test_normalize_empty_data(self):
        result = normalize_iconstate({})
        self.assertEqual(result.dock, [])
        self.assertEqual(result.pages, [])

    def test_normalize_multiple_pages(self):
        data = {
            "buttonBar": [],
            "iconLists": [
                [{"bundleIdentifier": "com.page1.app"}],
                [{"bundleIdentifier": "com.page2.app"}],
            ]
        }
        result = normalize_iconstate(data)
        self.assertEqual(len(result.pages), 2)

    def test_normalize_skips_invalid_items(self):
        data = {
            "buttonBar": [{"other": "data"}],
            "iconLists": [[{"invalid": "item"}]]
        }
        result = normalize_iconstate(data)
        self.assertEqual(result.dock, [])
        self.assertEqual(result.pages, [[]])


class TestToYamlExport(unittest.TestCase):
    """Tests for to_yaml_export function."""

    def test_export_basic_layout(self):
        layout = NormalizedLayout(
            dock=["com.apple.safari"],
            pages=[[{"kind": "app", "id": "com.example.app"}]]
        )
        result = to_yaml_export(layout)
        self.assertEqual(result["dock"], ["com.apple.safari"])
        self.assertIn("#", result)  # Comment header
        self.assertEqual(len(result["pages"]), 1)
        self.assertEqual(result["pages"][0]["apps"], ["com.example.app"])

    def test_export_with_folders(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[
                {"kind": "folder", "name": "Work", "apps": ["com.work.app1", "com.work.app2"]}
            ]]
        )
        result = to_yaml_export(layout)
        self.assertEqual(len(result["pages"][0]["folders"]), 1)
        self.assertEqual(result["pages"][0]["folders"][0]["name"], "Work")
        self.assertEqual(result["pages"][0]["folders"][0]["apps"], ["com.work.app1", "com.work.app2"])

    def test_export_empty_layout(self):
        layout = NormalizedLayout(dock=[], pages=[])
        result = to_yaml_export(layout)
        self.assertEqual(result["dock"], [])
        self.assertEqual(result["pages"], [])


class TestScaffoldPlan(unittest.TestCase):
    """Tests for scaffold_plan function."""

    def test_scaffold_basic_plan(self):
        layout = NormalizedLayout(
            dock=["com.apple.safari", "com.apple.mail"],
            pages=[[
                {"kind": "app", "id": "com.example.app1"},
                {"kind": "app", "id": "com.example.app2"},
            ]]
        )
        result = scaffold_plan(layout)
        self.assertIn("pins", result)
        self.assertIn("folders", result)
        self.assertIn("unassigned", result)
        # Dock apps should be in pins
        self.assertIn("com.apple.safari", result["pins"])
        self.assertIn("com.apple.mail", result["pins"])

    def test_scaffold_limits_pins_to_12(self):
        layout = NormalizedLayout(
            dock=["com.dock.1", "com.dock.2"],
            pages=[[{"kind": "app", "id": f"com.app.{i}"} for i in range(20)]]
        )
        result = scaffold_plan(layout)
        self.assertLessEqual(len(result["pins"]), 12)

    def test_scaffold_has_predefined_folders(self):
        layout = NormalizedLayout(dock=[], pages=[])
        result = scaffold_plan(layout)
        expected_folders = ["Work", "Finance", "Travel", "Health", "Media", "Shopping", "Social", "Utilities"]
        for folder in expected_folders:
            self.assertIn(folder, result["folders"])

    def test_scaffold_unassigned_excludes_pins(self):
        layout = NormalizedLayout(
            dock=["com.pinned.app"],
            pages=[[
                {"kind": "app", "id": "com.pinned.app"},
                {"kind": "app", "id": "com.unpinned.app"},
            ]]
        )
        result = scaffold_plan(layout)
        self.assertNotIn("com.pinned.app", result["unassigned"])


class TestComputeLocationMap(unittest.TestCase):
    """Tests for compute_location_map function."""

    def test_location_map_basic(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[
                [{"kind": "app", "id": "com.page1.app"}],
                [{"kind": "app", "id": "com.page2.app"}],
            ]
        )
        result = compute_location_map(layout)
        self.assertEqual(result["com.page1.app"], "Page 1")
        self.assertEqual(result["com.page2.app"], "Page 2")

    def test_location_map_with_folders(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[
                {"kind": "folder", "name": "Work", "apps": ["com.work.app"]}
            ]]
        )
        result = compute_location_map(layout)
        self.assertEqual(result["com.work.app"], "Page 1 > Work")

    def test_location_map_first_seen_wins(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[
                [{"kind": "app", "id": "com.dup.app"}],
                [{"kind": "app", "id": "com.dup.app"}],
            ]
        )
        result = compute_location_map(layout)
        self.assertEqual(result["com.dup.app"], "Page 1")


class TestListAllApps(unittest.TestCase):
    """Tests for list_all_apps function."""

    def test_list_all_apps_basic(self):
        layout = NormalizedLayout(
            dock=["com.dock.app"],
            pages=[[{"kind": "app", "id": "com.page.app"}]]
        )
        result = list_all_apps(layout)
        self.assertIn("com.dock.app", result)
        self.assertIn("com.page.app", result)

    def test_list_all_apps_includes_folder_apps(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[
                {"kind": "folder", "name": "Work", "apps": ["com.folder.app"]}
            ]]
        )
        result = list_all_apps(layout)
        self.assertIn("com.folder.app", result)

    def test_list_all_apps_deduplicates(self):
        layout = NormalizedLayout(
            dock=["com.dup.app"],
            pages=[[{"kind": "app", "id": "com.dup.app"}]]
        )
        result = list_all_apps(layout)
        self.assertEqual(result.count("com.dup.app"), 1)

    def test_list_all_apps_empty_layout(self):
        layout = NormalizedLayout(dock=[], pages=[])
        result = list_all_apps(layout)
        self.assertEqual(result, [])


class TestComputeFolderPageMap(unittest.TestCase):
    """Tests for compute_folder_page_map function."""

    def test_folder_page_map_basic(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[
                [{"kind": "folder", "name": "Work", "apps": []}],
                [{"kind": "folder", "name": "Personal", "apps": []}],
            ]
        )
        result = compute_folder_page_map(layout)
        self.assertEqual(result["Work"], 1)
        self.assertEqual(result["Personal"], 2)

    def test_folder_page_map_first_occurrence(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[
                [{"kind": "folder", "name": "Work", "apps": []}],
                [{"kind": "folder", "name": "Work", "apps": []}],
            ]
        )
        result = compute_folder_page_map(layout)
        self.assertEqual(result["Work"], 1)

    def test_folder_page_map_empty(self):
        layout = NormalizedLayout(dock=[], pages=[[{"kind": "app", "id": "com.app"}]])
        result = compute_folder_page_map(layout)
        self.assertEqual(result, {})


class TestComputeRootAppPageMap(unittest.TestCase):
    """Tests for compute_root_app_page_map function."""

    def test_root_app_page_map_basic(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[
                [{"kind": "app", "id": "com.page1.app"}],
                [{"kind": "app", "id": "com.page2.app"}],
            ]
        )
        result = compute_root_app_page_map(layout)
        self.assertEqual(result["com.page1.app"], 1)
        self.assertEqual(result["com.page2.app"], 2)

    def test_root_app_page_map_excludes_folder_apps(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[
                {"kind": "folder", "name": "Work", "apps": ["com.folder.app"]}
            ]]
        )
        result = compute_root_app_page_map(layout)
        self.assertNotIn("com.folder.app", result)


class TestAnalyzeLayout(unittest.TestCase):
    """Tests for analyze_layout function."""

    def test_analyze_basic_layout(self):
        layout = NormalizedLayout(
            dock=["com.apple.safari"],
            pages=[[
                {"kind": "app", "id": "com.app.one"},
                {"kind": "folder", "name": "Work", "apps": ["com.work.app"]},
            ]]
        )
        result = analyze_layout(layout)
        self.assertEqual(result["dock"], ["com.apple.safari"])
        self.assertEqual(result["dock_count"], 1)
        self.assertEqual(result["pages_count"], 1)
        self.assertIn("folders", result)
        self.assertIn("totals", result)

    def test_analyze_detects_duplicates(self):
        layout = NormalizedLayout(
            dock=["com.dup.app"],
            pages=[[{"kind": "app", "id": "com.dup.app"}]]
        )
        result = analyze_layout(layout)
        self.assertIn("com.dup.app", result["duplicates"])

    def test_analyze_generates_observations(self):
        # Layout with small dock triggers observation
        layout = NormalizedLayout(
            dock=["com.single.app"],
            pages=[[{"kind": "app", "id": "com.app"}]]
        )
        result = analyze_layout(layout)
        # Should have observation about dock size
        observations = result["observations"]
        self.assertTrue(any("Dock" in obs for obs in observations))

    def test_analyze_with_plan(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[{"kind": "app", "id": "com.existing.app"}]]
        )
        plan = {
            "pins": ["com.missing.app"],
            "folders": {"Empty": []},
        }
        result = analyze_layout(layout, plan)
        # Should note missing pins and empty folders
        observations = result["observations"]
        self.assertTrue(any("pins not found" in obs for obs in observations))
        self.assertTrue(any("without assigned apps" in obs for obs in observations))


class TestChecklistFromPlan(unittest.TestCase):
    """Tests for checklist_from_plan function."""

    def test_checklist_basic(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[{"kind": "app", "id": "com.app.tomove"}]]
        )
        plan = {
            "pins": [],
            "folders": {"Work": ["com.app.tomove"]},
        }
        result = checklist_from_plan(layout, plan)
        self.assertTrue(any("Work" in line for line in result))
        self.assertTrue(any("com.app.tomove" in line for line in result))

    def test_checklist_missing_app(self):
        layout = NormalizedLayout(dock=[], pages=[])
        plan = {
            "pins": [],
            "folders": {"Work": ["com.missing.app"]},
        }
        result = checklist_from_plan(layout, plan)
        self.assertTrue(any("Install" in line for line in result))

    def test_checklist_empty_folders_skipped(self):
        layout = NormalizedLayout(dock=[], pages=[])
        plan = {
            "pins": [],
            "folders": {"Empty": []},
        }
        result = checklist_from_plan(layout, plan)
        self.assertFalse(any("Empty" in line for line in result))


class TestRankUnusedCandidates(unittest.TestCase):
    """Tests for rank_unused_candidates function."""

    def test_rank_dock_apps_lower(self):
        layout = NormalizedLayout(
            dock=["com.dock.app"],
            pages=[[{"kind": "app", "id": "com.page.app"}]]
        )
        result = rank_unused_candidates(layout)
        scores = {app: score for app, score, _ in result}
        # Dock apps should have lower score (less likely unused)
        self.assertLess(scores["com.dock.app"], scores["com.page.app"])

    def test_rank_with_keep_list(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[{"kind": "app", "id": "com.keep.app"}]]
        )
        result = rank_unused_candidates(layout, keep_ids=["com.keep.app"])
        scores = {app: score for app, score, _ in result}
        # Keep apps get -99 penalty
        self.assertLess(scores["com.keep.app"], -90)

    def test_rank_with_recent_list(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[
                [{"kind": "app", "id": "com.recent.app"}],
                [{"kind": "app", "id": "com.old.app"}],
            ]
        )
        result = rank_unused_candidates(layout, recent_ids=["com.recent.app"])
        scores = {app: score for app, score, _ in result}
        # Recent apps should score lower
        self.assertLess(scores["com.recent.app"], scores["com.old.app"])

    def test_rank_folder_apps_higher(self):
        layout = NormalizedLayout(
            dock=[],
            pages=[[
                {"kind": "app", "id": "com.root.app"},
                {"kind": "folder", "name": "Folder", "apps": ["com.folder.app"]},
            ]]
        )
        result = rank_unused_candidates(layout)
        scores = {app: score for app, score, _ in result}
        # Folder apps get +1.0 penalty (more likely unused)
        self.assertGreater(scores["com.folder.app"], scores["com.root.app"])


class TestDistributeFoldersAcrossPages(unittest.TestCase):
    """Tests for distribute_folders_across_pages function."""

    def test_distribute_basic(self):
        folders = ["Work", "Personal", "Media"]
        result = distribute_folders_across_pages(folders, per_page=2, start_page=2)
        self.assertEqual(result[2]["folders"], ["Work", "Personal"])
        self.assertEqual(result[3]["folders"], ["Media"])

    def test_distribute_all_on_one_page(self):
        folders = ["A", "B", "C"]
        result = distribute_folders_across_pages(folders, per_page=10, start_page=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[1]["folders"], ["A", "B", "C"])

    def test_distribute_empty(self):
        result = distribute_folders_across_pages([], per_page=5, start_page=2)
        self.assertEqual(result, {})

    def test_distribute_apps_always_empty(self):
        folders = ["Work"]
        result = distribute_folders_across_pages(folders, per_page=5, start_page=1)
        self.assertEqual(result[1]["apps"], [])


if __name__ == "__main__":
    unittest.main()
