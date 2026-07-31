"""Tests for phone.layout_merge module."""

from __future__ import annotations

import unittest

from phone.layout_merge import (
    MergePlan,
    classify_to_folder,
    merge_folders,
    verify_conservation,
)


# Minimal synthetic layout fixture
FIXTURE_LAYOUT = {
    "dock": ["com.dock.app1", "com.dock.app2"],
    "pages": [
        # Page 1 — loose apps
        {
            "apps": ["com.apple.mobilesafari", "com.apple.Preferences"],
            "folders": [],
        },
        # Page 2 — loose + folders
        {
            "apps": ["com.theathletic.news"],  # loose on page 2 → file into folder
            "folders": [
                {
                    "name": "Work",
                    "apps": ["com.slack", "us.zoom.videomeetings"],
                },
                {
                    "name": "Finance",
                    "apps": ["com.chase", "net.kortina.labs.Venmo"],
                },
                {
                    "name": "Other",  # dump folder — redistribute
                    "apps": [
                        "com.netflix.Netflix",  # → Media
                        "com.burbn.instagram",  # → Social
                        "com.amazon.Amazon",  # → Shopping
                        "com.ubercab.UberClient",  # → Travel
                        "com.alltrails.AllTrails",  # → Fitness
                    ],
                },
            ],
        },
        # Page 3 — folders only
        {
            "apps": [],
            "folders": [
                {
                    "name": "Media",
                    "apps": ["com.spotify.client"],
                },
                {
                    "name": "Social",
                    "apps": ["com.twitter.twitter"],
                },
                {
                    "name": "Travel",
                    "apps": ["com.airbnb.app"],
                },
                {
                    "name": "Fitness",
                    "apps": ["com.peloton.cycle"],
                },
                {
                    "name": "Shopping",
                    "apps": ["com.ebay.iphone"],
                },
                {
                    "name": "Misc",
                    "apps": ["com.unknown.xyzqrs"],
                },
            ],
        },
    ],
}


class TestMergeFoldersConservation(unittest.TestCase):
    def test_conservation_pass(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        # Must not raise
        verify_conservation(FIXTURE_LAYOUT, plan.to_dict())

    def test_conservation_raises_on_missing_app(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        bad_plan = plan.to_dict()
        # Remove one app from a folder to break conservation
        first_folder = next(iter(bad_plan["folders"]))
        bad_plan["folders"][first_folder] = bad_plan["folders"][first_folder][1:]
        with self.assertRaises(ValueError):
            verify_conservation(FIXTURE_LAYOUT, bad_plan)


class TestMergeFoldersDumpElimination(unittest.TestCase):
    def test_other_folder_eliminated(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        self.assertNotIn("Other", plan.folders)

    def test_dump_apps_redistributed(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        self.assertIn("com.netflix.Netflix", plan.folders.get("Media", []))
        self.assertIn("com.burbn.instagram", plan.folders.get("Social", []))
        self.assertIn("com.amazon.Amazon", plan.folders.get("Shopping", []))
        self.assertIn("com.ubercab.UberClient", plan.folders.get("Travel", []))
        self.assertIn("com.alltrails.AllTrails", plan.folders.get("Fitness", []))


class TestMergeFoldersLooseApps(unittest.TestCase):
    def test_loose_page2_filed(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        # com.theathletic.news should land in a folder (not a pin, not loose)
        self.assertNotIn("com.theathletic.news", plan.pins)
        # Must be in some folder
        all_foldered = {
            bid for apps in plan.folders.values() for bid in apps
        }
        self.assertIn("com.theathletic.news", all_foldered)

    def test_page1_pins_preserved(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        self.assertIn("com.apple.mobilesafari", plan.pins)
        self.assertIn("com.apple.Preferences", plan.pins)
        # Page-1 apps must NOT be in any folder
        all_foldered = {
            bid for apps in plan.folders.values() for bid in apps
        }
        self.assertNotIn("com.apple.mobilesafari", all_foldered)
        self.assertNotIn("com.apple.Preferences", all_foldered)


class TestMergeFoldersDockAndFolders(unittest.TestCase):
    def test_dock_preserved(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        self.assertEqual(plan.dock, ["com.dock.app1", "com.dock.app2"])

    def test_existing_folders_preserved(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        # Work still has slack + zoom
        work_apps = plan.folders.get("Work", [])
        self.assertIn("com.slack", work_apps)
        self.assertIn("us.zoom.videomeetings", work_apps)
        # Finance still has chase + venmo
        finance_apps = plan.folders.get("Finance", [])
        self.assertIn("com.chase", finance_apps)
        self.assertIn("net.kortina.labs.Venmo", finance_apps)


class TestMergeFoldersPageAssignments(unittest.TestCase):
    def test_page_assignments(self):
        plan = merge_folders(FIXTURE_LAYOUT)
        # Page 2 should list Work and Finance (not Other)
        page2_folders = plan.pages.get(2, {}).get("folders", [])
        self.assertIn("Work", page2_folders)
        self.assertIn("Finance", page2_folders)
        self.assertNotIn("Other", page2_folders)
        # Page 3 should include Media
        page3_folders = plan.pages.get(3, {}).get("folders", [])
        self.assertIn("Media", page3_folders)


class TestClassifyToFolder(unittest.TestCase):
    def test_classify_to_folder_health_maps_to_fitness(self):
        result = classify_to_folder(
            "com.peloton.cycle",
            {"Fitness", "Work", "Misc"},
        )
        self.assertEqual(result, "Fitness")

    def test_classify_to_folder_utilities_maps_to_misc(self):
        # An unknown app → Utilities → Misc
        result = classify_to_folder(
            "com.some.unknown.app",
            {"Fitness", "Work", "Misc"},
        )
        self.assertEqual(result, "Misc")

    def test_classify_to_folder_fallback_when_no_match(self):
        # Category target not in existing_folders → fallback
        result = classify_to_folder(
            "com.unknown.nothing",
            {"Work"},  # Misc not present
            fallback="Misc",
        )
        # Fallback "Misc" not in existing_folders, so returns first sorted folder
        self.assertEqual(result, "Work")

    def test_bundle_override_respected(self):
        result = classify_to_folder(
            "com.netflix.Netflix",
            {"Media", "Work", "Misc"},
        )
        self.assertEqual(result, "Media")

    def test_bundle_override_falls_back_when_folder_missing(self):
        # com.alltrails.AllTrails → Fitness override, but Fitness not in existing_folders
        result = classify_to_folder(
            "com.alltrails.AllTrails",
            {"Work", "Misc"},
        )
        # Fitness not available, classifier returns Health → _CATEGORY_TO_FOLDER → Fitness → not found
        # Falls back to Misc
        self.assertEqual(result, "Misc")


class TestPage1NonDumpFolder(unittest.TestCase):
    def test_page1_nondump_folder_appears_in_pages(self):
        """Non-dump folder on page 1 must appear in pages[1]['folders']."""
        layout = {
            "dock": [],
            "pages": [
                # Page 1 — loose apps + a non-dump folder
                {
                    "apps": ["com.apple.mobilesafari"],
                    "folders": [
                        {"name": "Work", "apps": ["com.slack", "us.zoom.videomeetings"]},
                    ],
                },
                # Page 2 — another folder so existing_folders is non-empty
                {
                    "apps": [],
                    "folders": [
                        {"name": "Media", "apps": ["com.spotify.client"]},
                    ],
                },
            ],
        }
        plan = merge_folders(layout)
        verify_conservation(layout, plan.to_dict())
        # The page-1 folder must appear in pages[1]['folders']
        page1 = plan.pages.get(1, {})
        self.assertIn("Work", page1.get("folders", []))
        # Pins from page 1 loose apps must also be present
        self.assertIn("com.apple.mobilesafari", page1.get("apps", []))
        # Work folder apps must be in plan.folders
        self.assertIn("com.slack", plan.folders.get("Work", []))


class TestPage1DumpFolderAppsRedistributed(unittest.TestCase):
    def test_page1_dump_folder_apps_redistributed(self):
        """Dump folder on page 1 must have its apps redistributed; conservation must pass."""
        layout = {
            "dock": [],
            "pages": [
                # Page 1 — dump folder "Other" sits here
                {
                    "apps": ["com.apple.mobilesafari"],
                    "folders": [
                        {
                            "name": "Other",
                            "apps": ["com.netflix.Netflix", "com.amazon.Amazon"],
                        },
                    ],
                },
                # Page 2 — real folders to absorb the dump apps
                {
                    "apps": [],
                    "folders": [
                        {"name": "Media", "apps": ["com.spotify.client"]},
                        {"name": "Shopping", "apps": ["com.ebay.iphone"]},
                    ],
                },
            ],
        }
        plan = merge_folders(layout)
        # Conservation must not raise
        verify_conservation(layout, plan.to_dict())
        # "Other" must be gone from plan.folders
        self.assertNotIn("Other", plan.folders)
        # Dump apps must have landed in existing folders
        all_foldered = {bid for apps in plan.folders.values() for bid in apps}
        self.assertIn("com.netflix.Netflix", all_foldered)
        self.assertIn("com.amazon.Amazon", all_foldered)


class TestEmptyExistingFoldersRaises(unittest.TestCase):
    def test_empty_existing_folders_raises(self):
        """merge_folders must raise ValueError when all folders are dump folders."""
        layout = {
            "dock": [],
            "pages": [
                {
                    "apps": ["com.apple.mobilesafari"],
                    "folders": [
                        {"name": "Other", "apps": ["com.netflix.Netflix"]},
                    ],
                },
            ],
        }
        with self.assertRaises(ValueError) as ctx:
            merge_folders(layout)
        self.assertIn("No existing (non-dump) folders", str(ctx.exception))


class TestConservationCatchesDuplicate(unittest.TestCase):
    def test_conservation_catches_duplicate(self):
        """verify_conservation uses multiset semantics: dropping one copy of a
        duplicate bundle ID must raise ValueError."""
        layout = {
            "dock": [],
            "pages": [
                # bundle ID appears twice (once loose, once in a folder)
                {
                    "apps": ["com.duplicate.app"],
                    "folders": [
                        {"name": "Work", "apps": ["com.duplicate.app", "com.slack"]},
                    ],
                },
            ],
        }
        # Plan that only accounts for one copy of com.duplicate.app
        plan = {
            "dock": [],
            "pins": ["com.duplicate.app"],
            "folders": {"Work": ["com.slack"]},  # second copy missing
        }
        with self.assertRaises(ValueError):
            verify_conservation(layout, plan)


class TestMergePlanToDict(unittest.TestCase):
    def test_to_dict_structure(self):
        plan = MergePlan(
            dock=["com.a"],
            pins=["com.b"],
            folders={"Work": ["com.c"]},
            pages={1: {"apps": ["com.b"], "folders": []}},
        )
        d = plan.to_dict()
        self.assertEqual(d["dock"], ["com.a"])
        self.assertEqual(d["pins"], ["com.b"])
        self.assertEqual(d["folders"]["Work"], ["com.c"])
        self.assertIn("1", d["pages"])


if __name__ == "__main__":
    unittest.main()
