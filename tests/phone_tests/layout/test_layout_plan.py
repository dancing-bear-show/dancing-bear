"""Tests for phone/layout_plan.py — planning, analysis, and ranking helpers."""

from __future__ import annotations

import unittest

from phone.layout import (
    analyze_layout,
    auto_folderize,
    checklist_from_plan,
    compute_folder_page_map,
    compute_location_map,
    compute_root_app_page_map,
    distribute_folders_across_pages,
    list_all_apps,
    rank_unused_candidates,
    scaffold_plan,
)
from tests.phone_tests.fixtures import (
    make_app_item,
    make_folder_item,
    make_layout,
)


class TestScaffoldPlan(unittest.TestCase):
    """Tests for scaffold_plan function."""

    def test_basic_scaffold(self):
        layout = make_layout(
            dock=["com.dock1", "com.dock2"],
            pages=[[make_app_item("com.page1.app1")]],
        )
        plan = scaffold_plan(layout)

        self.assertIn("#", plan)
        self.assertIn("pins", plan)
        self.assertIn("folders", plan)
        self.assertIn("unassigned", plan)
        self.assertIn("com.dock1", plan["pins"])
        self.assertIn("com.dock2", plan["pins"])

    def test_pins_include_page1_apps_up_to_12(self):
        layout = make_layout(
            dock=["com.dock1"],
            pages=[[make_app_item(f"com.app{i}") for i in range(20)]],
        )
        plan = scaffold_plan(layout)

        # dock (1) + page1 apps (11 more) = 12 total
        self.assertEqual(len(plan["pins"]), 12)

    def test_unassigned_excludes_pins(self):
        # Page 1 apps get added to pins (up to 12), so use page 2 for unassigned test
        layout = make_layout(
            dock=["com.dock1"],
            pages=[
                [make_app_item("com.page1")],
                [make_app_item("com.page2")],
            ],
        )
        plan = scaffold_plan(layout)

        # Page 2 app should be unassigned (not pinned)
        self.assertIn("com.page2", plan["unassigned"])
        # Dock and page 1 apps are pinned
        self.assertIn("com.dock1", plan["pins"])
        self.assertIn("com.page1", plan["pins"])
        # Pins and unassigned should be disjoint
        pins_set = set(plan["pins"])
        unassigned_set = set(plan["unassigned"])
        self.assertTrue(pins_set.isdisjoint(unassigned_set))

    def test_default_folders_present(self):
        layout = make_layout()
        plan = scaffold_plan(layout)

        expected_folders = {"Work", "Finance", "Travel", "Health", "Media", "Shopping", "Social", "Utilities"}
        self.assertEqual(set(plan["folders"].keys()), expected_folders)


class TestComputeLocationMap(unittest.TestCase):
    """Tests for compute_location_map function."""

    def test_root_apps(self):
        layout = make_layout(pages=[
            [make_app_item("com.page1")],
            [make_app_item("com.page2")],
        ])
        loc = compute_location_map(layout)

        self.assertEqual(loc["com.page1"], "Page 1")
        self.assertEqual(loc["com.page2"], "Page 2")

    def test_folder_apps(self):
        layout = make_layout(pages=[
            [make_folder_item("Work", ["com.work1", "com.work2"])],
        ])
        loc = compute_location_map(layout)

        self.assertEqual(loc["com.work1"], "Page 1 > Work")
        self.assertEqual(loc["com.work2"], "Page 1 > Work")

    def test_first_location_wins_for_duplicates(self):
        layout = make_layout(pages=[
            [make_app_item("com.dup")],
            [make_app_item("com.dup")],
        ])
        loc = compute_location_map(layout)
        self.assertEqual(loc["com.dup"], "Page 1")


class TestListAllApps(unittest.TestCase):
    """Tests for list_all_apps function."""

    def test_includes_dock_and_pages(self):
        layout = make_layout(
            dock=["com.dock"],
            pages=[[make_app_item("com.page")]],
        )
        apps = list_all_apps(layout)
        self.assertEqual(apps, ["com.dock", "com.page"])

    def test_includes_folder_apps(self):
        layout = make_layout(pages=[
            [make_folder_item("F", ["com.f1", "com.f2"])],
        ])
        apps = list_all_apps(layout)
        self.assertEqual(apps, ["com.f1", "com.f2"])

    def test_deduplicates(self):
        layout = make_layout(
            dock=["com.dup"],
            pages=[[make_app_item("com.dup")]],
        )
        apps = list_all_apps(layout)
        self.assertEqual(apps.count("com.dup"), 1)

    def test_preserves_order(self):
        layout = make_layout(
            dock=["com.first"],
            pages=[[make_app_item("com.second"), make_app_item("com.third")]],
        )
        apps = list_all_apps(layout)
        self.assertEqual(apps, ["com.first", "com.second", "com.third"])


class TestComputeFolderPageMap(unittest.TestCase):
    """Tests for compute_folder_page_map function."""

    def test_maps_folders_to_pages(self):
        layout = make_layout(pages=[
            [make_folder_item("Work")],
            [make_folder_item("Media")],
        ])
        m = compute_folder_page_map(layout)
        self.assertEqual(m["Work"], 1)
        self.assertEqual(m["Media"], 2)

    def test_first_occurrence_wins(self):
        layout = make_layout(pages=[
            [make_folder_item("Work")],
            [make_folder_item("Work")],
        ])
        m = compute_folder_page_map(layout)
        self.assertEqual(m["Work"], 1)


class TestComputeRootAppPageMap(unittest.TestCase):
    """Tests for compute_root_app_page_map function."""

    def test_maps_root_apps(self):
        layout = make_layout(pages=[
            [make_app_item("com.page1")],
            [make_app_item("com.page2")],
        ])
        m = compute_root_app_page_map(layout)
        self.assertEqual(m["com.page1"], 1)
        self.assertEqual(m["com.page2"], 2)

    def test_excludes_folder_apps(self):
        layout = make_layout(pages=[
            [make_folder_item("F", ["com.inside"])],
        ])
        m = compute_root_app_page_map(layout)
        self.assertNotIn("com.inside", m)


class TestRankUnusedCandidates(unittest.TestCase):
    """Tests for rank_unused_candidates function."""

    def test_dock_apps_have_lower_score(self):
        layout = make_layout(
            dock=["com.dock"],
            pages=[[make_app_item("com.page")]],
        )
        results = rank_unused_candidates(layout)
        scores = {app: score for app, score, _ in results}

        self.assertLess(scores["com.dock"], scores["com.page"])

    def test_page1_apps_have_lower_score(self):
        layout = make_layout(pages=[
            [make_app_item("com.page1")],
            [make_app_item("com.page3")],
            [make_app_item("com.page5")],
        ])
        results = rank_unused_candidates(layout)
        scores = {app: score for app, score, _ in results}

        self.assertLess(scores["com.page1"], scores["com.page3"])
        self.assertLess(scores["com.page3"], scores["com.page5"])

    def test_folder_apps_have_higher_score(self):
        layout = make_layout(pages=[[
            make_app_item("com.root"),
            make_folder_item("F", ["com.infolder"]),
        ]])
        results = rank_unused_candidates(layout)
        scores = {app: score for app, score, _ in results}

        self.assertGreater(scores["com.infolder"], scores["com.root"])

    def test_keep_list_removes_from_top(self):
        layout = make_layout(pages=[
            [make_app_item("com.keep"), make_app_item("com.other")],
        ])
        results = rank_unused_candidates(layout, keep_ids=["com.keep"])
        scores = {app: score for app, score, _ in results}

        self.assertLess(scores["com.keep"], scores["com.other"])

    def test_recent_apps_have_lower_score(self):
        layout = make_layout(pages=[
            [make_app_item("com.recent"), make_app_item("com.old")],
        ])
        results = rank_unused_candidates(layout, recent_ids=["com.recent"])
        scores = {app: score for app, score, _ in results}

        self.assertLess(scores["com.recent"], scores["com.old"])

    def test_common_apple_apps_penalized(self):
        layout = make_layout(pages=[[
            make_app_item("com.apple.camera"),
            make_app_item("com.random.app"),
        ]])
        results = rank_unused_candidates(layout)
        scores = {app: score for app, score, _ in results}

        self.assertLess(scores["com.apple.camera"], scores["com.random.app"])


class TestChecklistFromPlan(unittest.TestCase):
    """Tests for checklist_from_plan function."""

    def test_creates_folder_move_instructions(self):
        layout = make_layout(pages=[[make_app_item("com.app1")]])
        plan = {"pins": [], "folders": {"Work": ["com.app1"]}}
        instructions = checklist_from_plan(layout, plan)

        self.assertTrue(any("Create/Rename folder: Work" in i for i in instructions))
        self.assertTrue(any("Move com.app1" in i and "Work" in i for i in instructions))

    def test_skips_pinned_apps(self):
        layout = make_layout(pages=[[make_app_item("com.pinned")]])
        plan = {"pins": ["com.pinned"], "folders": {"Work": ["com.pinned"]}}
        instructions = checklist_from_plan(layout, plan)

        self.assertFalse(any("Move com.pinned" in i for i in instructions))

    def test_skips_apps_already_in_target_folder(self):
        layout = make_layout(pages=[[make_folder_item("Work", ["com.already"])]])
        plan = {"pins": [], "folders": {"Work": ["com.already"]}}
        instructions = checklist_from_plan(layout, plan)

        self.assertFalse(any("Move com.already" in i for i in instructions))

    def test_handles_missing_apps(self):
        layout = make_layout()
        plan = {"pins": [], "folders": {"Work": ["com.notfound"]}}
        instructions = checklist_from_plan(layout, plan)

        self.assertTrue(any("Install or locate" in i and "com.notfound" in i for i in instructions))

    def test_page_organization(self):
        layout = make_layout(pages=[
            [make_folder_item("Work")],
            [make_app_item("com.app1")],
        ])
        plan = {
            "pins": [],
            "folders": {},
            "pages": {"1": {"folders": ["Work"], "apps": ["com.app1"]}},
        }
        instructions = checklist_from_plan(layout, plan)

        # Work is on page 1, so no move needed
        # app1 is on page 2, should move to page 1
        self.assertTrue(any("Page 2 to Page 1" in i and "com.app1" in i for i in instructions))


class TestAnalyzeLayout(unittest.TestCase):
    """Tests for analyze_layout function."""

    def test_basic_analysis(self):
        layout = make_layout(
            dock=["com.dock1", "com.dock2"],
            pages=[
                [make_app_item("com.app1"), make_folder_item("Work", ["com.w1"])],
                [make_app_item("com.app2")],
            ],
        )
        result = analyze_layout(layout)

        self.assertEqual(result["dock"], ["com.dock1", "com.dock2"])
        self.assertEqual(result["dock_count"], 2)
        self.assertEqual(result["pages_count"], 2)
        self.assertEqual(len(result["pages"]), 2)
        self.assertEqual(result["pages"][0]["root_apps"], 1)
        self.assertEqual(result["pages"][0]["folders"], 1)
        self.assertEqual(len(result["folders"]), 1)
        self.assertEqual(result["folders"][0]["name"], "Work")
        self.assertEqual(result["folders"][0]["app_count"], 1)

    def test_totals(self):
        layout = make_layout(
            dock=["com.dock"],
            pages=[[make_app_item("com.app1"), make_folder_item("F", ["com.f1", "com.f2"])]],
        )
        result = analyze_layout(layout)

        self.assertEqual(result["totals"]["unique_apps"], 4)  # dock + app1 + f1 + f2
        self.assertEqual(result["totals"]["root_apps"], 1)
        self.assertEqual(result["totals"]["folders"], 1)

    def test_duplicates_detected(self):
        layout = make_layout(
            dock=["com.dup"],
            pages=[[make_app_item("com.dup")]],
        )
        result = analyze_layout(layout)
        self.assertIn("com.dup", result["duplicates"])

    def test_observations_small_dock(self):
        layout = make_layout(dock=["com.one"])
        result = analyze_layout(layout)
        self.assertTrue(any("Dock has 1 apps" in o for o in result["observations"]))

    def test_observations_tiny_folders(self):
        layout = make_layout(pages=[[make_folder_item("Tiny", ["com.one"])]])
        result = analyze_layout(layout)
        self.assertTrue(any("tiny folder" in o for o in result["observations"]))

    def test_observations_large_folders(self):
        layout = make_layout(pages=[
            [make_folder_item("Big", [f"com.app{i}" for i in range(15)])],
        ])
        result = analyze_layout(layout)
        self.assertTrue(any("large folder" in o for o in result["observations"]))

    def test_plan_alignment_missing_pins(self):
        layout = make_layout()
        plan = {"pins": ["com.missing"]}
        result = analyze_layout(layout, plan=plan)
        self.assertTrue(any("pins not found" in o for o in result["observations"]))


class TestAutoFolderize(unittest.TestCase):
    """Tests for auto_folderize function."""

    def test_basic_folderization(self):
        layout = make_layout(pages=[[make_app_item("com.spotify.music")]])
        folders = auto_folderize(layout)

        # spotify should be classified as Media
        self.assertIn("Media", folders)
        self.assertIn("com.spotify.music", folders["Media"])

    def test_keep_list_excludes_apps(self):
        layout = make_layout(pages=[[make_app_item("com.spotify.music")]])
        folders = auto_folderize(layout, keep=["com.spotify.music"])

        # Should not appear in any folder
        all_apps = [app for apps in folders.values() for app in apps]
        self.assertNotIn("com.spotify.music", all_apps)

    def test_seed_folders_preserved(self):
        layout = make_layout(pages=[[make_app_item("com.new.app")]])
        seed = {"Custom": ["com.existing"]}
        folders = auto_folderize(layout, seed_folders=seed)

        self.assertIn("Custom", folders)
        self.assertIn("com.existing", folders["Custom"])


class TestDistributeFoldersAcrossPages(unittest.TestCase):
    """Tests for distribute_folders_across_pages function."""

    def test_basic_distribution(self):
        folders = ["Work", "Media", "Social"]
        result = distribute_folders_across_pages(folders, per_page=2, start_page=2)

        self.assertIn(2, result)
        self.assertIn(3, result)
        self.assertEqual(result[2]["folders"], ["Work", "Media"])
        self.assertEqual(result[3]["folders"], ["Social"])
        self.assertEqual(result[2]["apps"], [])

    def test_single_page_when_all_fit(self):
        folders = ["A", "B", "C"]
        result = distribute_folders_across_pages(folders, per_page=10)

        self.assertEqual(len(result), 1)
        self.assertIn(2, result)
        self.assertEqual(result[2]["folders"], ["A", "B", "C"])

    def test_empty_folders(self):
        result = distribute_folders_across_pages([])
        self.assertEqual(result, {})

    def test_custom_start_page(self):
        folders = ["A"]
        result = distribute_folders_across_pages(folders, start_page=5)
        self.assertIn(5, result)


if __name__ == "__main__":
    unittest.main()
