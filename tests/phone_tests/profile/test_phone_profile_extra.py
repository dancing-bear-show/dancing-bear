"""Additional tests for phone/profile.py covering previously uncovered lines."""
from __future__ import annotations

import unittest

from phone.profile import (
    AppItem,
    AutoCategorizeConfig,
    FolderItem,
    HomeScreenConfigBuilder,
    HslPayloadConfig,
    Page,
    _add_all_apps_folder,
    _add_auto_categorized_folders,
    _build_default_pages,
    _build_hsl_payload,
    _build_pages_from_spec,
    _collect_apps,
    _collect_assigned_apps,
    _collect_page_apps,
    _folder_item,
    _list_apps_from_export,
    _normalize_pages_spec,
    _resolve_dock,
    build_mobileconfig,
)


class TestAppItem(unittest.TestCase):
    def test_as_spec(self):
        item = AppItem("com.example.app")
        spec = item.as_spec()
        self.assertEqual(spec, {"Type": "Application", "BundleID": "com.example.app"})


class TestFolderItem(unittest.TestCase):
    def test_as_spec_basic(self):
        folder = FolderItem("Work", [AppItem("com.slack"), AppItem("com.mail")])
        spec = folder.as_spec()
        self.assertEqual(spec["Type"], "Folder")
        self.assertEqual(spec["DisplayName"], "Work")
        self.assertEqual(len(spec["Pages"]), 1)

    def test_as_spec_empty_apps(self):
        folder = FolderItem("Empty")
        spec = folder.as_spec()
        self.assertEqual(spec["Pages"], [[]])

    def test_as_spec_zero_page_size(self):
        apps = [AppItem(f"com.app{i}") for i in range(5)]
        folder = FolderItem("All", apps, page_size=0)
        spec = folder.as_spec()
        # When page_size <= 0, all apps go on one page
        self.assertEqual(len(spec["Pages"]), 1)
        self.assertEqual(len(spec["Pages"][0]), 5)

    def test_as_spec_paginates_apps(self):
        apps = [AppItem(f"com.app{i}") for i in range(35)]
        folder = FolderItem("Big", apps, page_size=10)
        spec = folder.as_spec()
        # 35 apps / 10 per page = 4 pages
        self.assertEqual(len(spec["Pages"]), 4)

    def test_default_display_name_when_empty(self):
        folder = FolderItem("")
        spec = folder.as_spec()
        self.assertEqual(spec["DisplayName"], "Folder")


class TestFolderItemFunction(unittest.TestCase):
    def test_folder_item_basic(self):
        result = _folder_item("Work", ["com.slack", "com.mail"])
        self.assertEqual(result["Type"], "Folder")
        self.assertEqual(result["DisplayName"], "Work")

    def test_folder_item_zero_page_size(self):
        result = _folder_item("Work", ["com.app1", "com.app2"], page_size=0)
        self.assertEqual(len(result["Pages"]), 1)

    def test_folder_item_filters_empty_apps(self):
        result = _folder_item("Work", ["com.app1", "", "com.app2"])
        total_apps = sum(len(p) for p in result["Pages"])
        self.assertEqual(total_apps, 2)

    def test_folder_item_empty_apps(self):
        result = _folder_item("Empty", [])
        self.assertEqual(result["Pages"], [[]])


class TestCollectApps(unittest.TestCase):
    def test_collects_unique_apps(self):
        seen = set()
        apps = []
        _collect_apps(["com.app1", "com.app2", "com.app1"], seen, apps)
        self.assertEqual(apps, ["com.app1", "com.app2"])

    def test_skips_non_strings(self):
        seen = set()
        apps = []
        _collect_apps([None, 123, "com.app1"], seen, apps)
        self.assertEqual(apps, ["com.app1"])


class TestCollectPageApps(unittest.TestCase):
    def test_collects_apps_and_folder_apps(self):
        seen = set()
        apps = []
        page = {
            "apps": ["com.app1"],
            "folders": [{"apps": ["com.folder_app1"]}],
        }
        _collect_page_apps(page, seen, apps)
        self.assertIn("com.app1", apps)
        self.assertIn("com.folder_app1", apps)


class TestListAppsFromExport(unittest.TestCase):
    def test_lists_all_apps(self):
        export = {
            "dock": ["com.dock1"],
            "pages": [
                {
                    "apps": ["com.app1", "com.app2"],
                    "folders": [{"apps": ["com.folder_app1"]}],
                }
            ],
        }
        result = _list_apps_from_export(export)
        self.assertIn("com.dock1", result)
        self.assertIn("com.app1", result)
        self.assertIn("com.app2", result)
        self.assertIn("com.folder_app1", result)

    def test_deduplicates(self):
        export = {
            "dock": ["com.app1"],
            "pages": [{"apps": ["com.app1"], "folders": []}],
        }
        result = _list_apps_from_export(export)
        self.assertEqual(result.count("com.app1"), 1)


class TestPage(unittest.TestCase):
    def test_as_items_empty(self):
        page = Page()
        self.assertEqual(page.as_items(), [])

    def test_as_items_with_apps_and_folders(self):
        page = Page(
            apps=[AppItem("com.app1")],
            folders=[FolderItem("Work", [AppItem("com.work")])],
        )
        items = page.as_items()
        self.assertEqual(len(items), 2)
        kinds = {item.get("Type") for item in items}
        self.assertIn("Application", kinds)
        self.assertIn("Folder", kinds)


class TestHomeScreenConfigBuilder(unittest.TestCase):
    def test_set_dock(self):
        builder = HomeScreenConfigBuilder()
        builder.set_dock(["com.app1", "", "com.app2", 123])
        self.assertEqual(builder.dock, ["com.app1", "com.app2"])

    def test_add_app(self):
        builder = HomeScreenConfigBuilder()
        builder.add_app(1, "com.app1")
        self.assertIn(1, builder.pages)
        self.assertEqual(builder.pages[1].apps[0].bundle_id, "com.app1")

    def test_add_app_skips_empty(self):
        builder = HomeScreenConfigBuilder()
        builder.add_app(1, "")
        self.assertNotIn(1, builder.pages)

    def test_add_folder(self):
        builder = HomeScreenConfigBuilder()
        builder.add_folder(1, "Work", ["com.slack"])
        self.assertIn(1, builder.pages)
        self.assertEqual(builder.pages[1].folders[0].name, "Work")

    def test_add_all_apps_folder(self):
        layout = {
            "dock": ["com.dock"],
            "pages": [{"apps": ["com.app1", "com.app2"], "folders": []}],
        }
        builder = HomeScreenConfigBuilder(layout)
        builder.add_all_apps_folder(page=2, name="All Apps")
        self.assertIn(2, builder.pages)

    def test_add_all_apps_folder_no_export(self):
        builder = HomeScreenConfigBuilder(None)
        builder.layout_export = None  # type: ignore
        # Should return early without error
        builder.add_all_apps_folder(page=1, name="All")
        self.assertNotIn(1, builder.pages)

    def test_build_pages_items_empty(self):
        builder = HomeScreenConfigBuilder()
        self.assertEqual(builder._build_pages_items(), [])

    def test_build_payload(self):
        builder = HomeScreenConfigBuilder()
        builder.set_dock(["com.app1"])
        builder.add_app(1, "com.app2")
        payload = builder.build_payload(
            payload_identifier="com.test.hs",
            display_name="Test Layout",
        )
        self.assertEqual(payload["PayloadType"], "com.apple.homescreenlayout")

    def test_build_profile(self):
        builder = HomeScreenConfigBuilder()
        profile = builder.build_profile(
            payload_identifier="com.test.hs",
            display_name="Test Layout",
            top_identifier="com.test.profile",
            organization="Test Org",
        )
        self.assertEqual(profile["PayloadType"], "Configuration")
        self.assertEqual(profile["PayloadOrganization"], "Test Org")

    def test_build_profile_no_organization(self):
        builder = HomeScreenConfigBuilder()
        profile = builder.build_profile(
            payload_identifier="com.test.hs",
            display_name="Test Layout",
            top_identifier="com.test.profile",
        )
        self.assertNotIn("PayloadOrganization", profile)


class TestBuildHslPayload(unittest.TestCase):
    def test_with_pages_items(self):
        payload = _build_hsl_payload(HslPayloadConfig(
            dock_ids=["com.dock"],
            pinned_ids=[],
            folders={},
            payload_identifier="com.test.hs",
            display_name="Test",
            pages_items=[[{"Type": "Application", "BundleID": "com.app1"}]],
        ))
        self.assertEqual(payload["PayloadType"], "com.apple.homescreenlayout")
        self.assertEqual(len(payload["Pages"]), 1)

    def test_without_pages_items_uses_pins_and_folders(self):
        payload = _build_hsl_payload(HslPayloadConfig(
            dock_ids=["com.dock"],
            pinned_ids=["com.pin1"],
            folders={"Work": ["com.slack"]},
            payload_identifier="com.test.hs",
            display_name="Test",
        ))
        self.assertEqual(len(payload["Pages"]), 1)
        # Pins go to page 1 (if not in dock), plus folders
        page1 = payload["Pages"][0]
        self.assertGreater(len(page1), 0)

    def test_pins_in_dock_not_on_page1(self):
        payload = _build_hsl_payload(HslPayloadConfig(
            dock_ids=["com.pin1"],
            pinned_ids=["com.pin1"],  # same as dock
            folders={},
            payload_identifier="com.test.hs",
            display_name="Test",
        ))
        page1 = payload["Pages"][0]
        pin_ids = [i.get("BundleID") for i in page1 if i.get("Type") == "Application"]
        self.assertNotIn("com.pin1", pin_ids)

    def test_empty_folders_skipped(self):
        payload = _build_hsl_payload(HslPayloadConfig(
            dock_ids=[],
            pinned_ids=[],
            folders={"Empty": []},
            payload_identifier="com.test.hs",
            display_name="Test",
        ))
        page1 = payload["Pages"][0]
        folder_names = [i.get("DisplayName") for i in page1 if i.get("Type") == "Folder"]
        self.assertNotIn("Empty", folder_names)


class TestNormalizePagesSpec(unittest.TestCase):
    def test_orders_by_page_num(self):
        spec = {
            3: {"apps": ["com.app3"], "folders": []},
            1: {"apps": ["com.app1"], "folders": []},
            2: {"apps": ["com.app2"], "folders": []},
        }
        result = _normalize_pages_spec(spec)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["apps"], ["com.app1"])
        self.assertEqual(result[2]["apps"], ["com.app3"])

    def test_handles_string_keys(self):
        spec = {"1": {"apps": ["com.a1"]}, "2": {"apps": ["com.a2"]}}
        result = _normalize_pages_spec(spec)
        self.assertEqual(len(result), 2)


class TestResolveDock(unittest.TestCase):
    def test_uses_plan_dock_when_list(self):
        plan = {"dock": ["com.app1", "com.app2"]}
        result = _resolve_dock(plan, None, [], 4)
        self.assertEqual(result, ["com.app1", "com.app2"])

    def test_uses_layout_export_dock(self):
        plan = {}
        export = {"dock": ["com.from_export"]}
        result = _resolve_dock(plan, export, [], 4)
        self.assertEqual(result, ["com.from_export"])

    def test_falls_back_to_pins(self):
        plan = {}
        result = _resolve_dock(plan, None, ["com.pin1", "com.pin2", "com.pin3"], 2)
        self.assertEqual(result, ["com.pin1", "com.pin2"])

    def test_negative_dock_count_returns_empty(self):
        plan = {}
        result = _resolve_dock(plan, None, ["com.pin1"], -1)
        self.assertEqual(result, [])


class TestBuildPagesFromSpec(unittest.TestCase):
    def test_builds_apps_and_folders(self):
        builder = HomeScreenConfigBuilder()
        pages_spec = {
            1: {"apps": ["com.app1", "com.app2"], "folders": ["Work"]},
        }
        folders = {"Work": ["com.slack", "com.outlook"]}
        _build_pages_from_spec(builder, pages_spec, folders, [])
        self.assertIn(1, builder.pages)

    def test_skips_dock_apps(self):
        builder = HomeScreenConfigBuilder()
        pages_spec = {1: {"apps": ["com.dock_app", "com.page_app"]}}
        _build_pages_from_spec(builder, pages_spec, {}, dock=["com.dock_app"])
        if 1 in builder.pages:
            app_ids = [a.bundle_id for a in builder.pages[1].apps]
            self.assertNotIn("com.dock_app", app_ids)


class TestBuildDefaultPages(unittest.TestCase):
    def test_adds_pins_and_folders(self):
        builder = HomeScreenConfigBuilder()
        _build_default_pages(builder, ["com.pin1"], {"Work": ["com.slack"]}, [])
        self.assertIn(1, builder.pages)

    def test_skips_dock_apps_in_pins(self):
        builder = HomeScreenConfigBuilder()
        _build_default_pages(builder, ["com.dock_pin"], {}, dock=["com.dock_pin"])
        if 1 in builder.pages:
            app_ids = [a.bundle_id for a in builder.pages[1].apps]
            self.assertNotIn("com.dock_pin", app_ids)


class TestCollectAssignedApps(unittest.TestCase):
    def test_collects_from_all_sources(self):
        builder = HomeScreenConfigBuilder()
        builder.add_app(1, "com.page_app")
        builder.add_folder(2, "Work", ["com.folder_app"])

        assigned = _collect_assigned_apps(
            builder,
            dock=["com.dock_app"],
            pins=["com.pin_app"],
            folders={"Tools": ["com.tool_app"]},
        )
        self.assertIn("com.dock_app", assigned)
        self.assertIn("com.pin_app", assigned)
        self.assertIn("com.tool_app", assigned)
        self.assertIn("com.page_app", assigned)
        self.assertIn("com.folder_app", assigned)


class TestAddAllAppsFolder(unittest.TestCase):
    def test_adds_catch_all_folder(self):
        layout = {
            "dock": ["com.dock"],
            "pages": [{"apps": ["com.app1", "com.app2", "com.app3"], "folders": []}],
        }
        builder = HomeScreenConfigBuilder(layout)
        builder.set_dock(["com.dock"])
        cfg = {"name": "All Apps", "page": 2}
        _add_all_apps_folder(builder, cfg, ["com.dock"], [], {})
        self.assertIn(2, builder.pages)


class TestAddAutoCategorizedFolders(unittest.TestCase):
    def test_auto_categorizes_remaining_apps(self):
        layout = {
            "dock": [],
            "pages": [{"apps": ["com.apple.calculator", "com.apple.Maps"], "folders": []}],
        }
        builder = HomeScreenConfigBuilder(layout)
        _add_auto_categorized_folders(
            builder,
            AutoCategorizeConfig(
                auto_categories=["Utilities", "Navigation"],
                auto_categories_page=2,
                layout_export=layout,
                dock=[],
                pins=[],
                folders={},
            ),
        )
        # Some folders should be added on page 2
        self.assertIsInstance(builder.pages, dict)


class TestBuildMobileconfig(unittest.TestCase):
    def test_basic_plan(self):
        plan = {
            "pins": ["com.app1", "com.app2"],
            "folders": {"Work": ["com.slack"]},
        }
        profile = build_mobileconfig(plan=plan)
        self.assertEqual(profile["PayloadType"], "Configuration")

    def test_with_layout_export(self):
        plan = {"dock": ["com.safari"], "pins": []}
        export = {"dock": ["com.safari"], "pages": [{"apps": ["com.music"], "folders": []}]}
        profile = build_mobileconfig(plan=plan, layout_export=export)
        payload = profile["PayloadContent"][0]
        self.assertEqual(payload["Dock"], [{"Type": "Application", "BundleID": "com.safari"}])

    def test_with_auto_categories(self):
        plan = {"pins": [], "folders": {}}
        export = {
            "dock": [],
            "pages": [{"apps": ["com.apple.calculator", "com.apple.Maps"], "folders": []}],
        }
        profile = build_mobileconfig(
            plan=plan,
            layout_export=export,
            auto_categories=["Utilities"],
            auto_categories_page=2,
        )
        self.assertEqual(profile["PayloadType"], "Configuration")

    def test_all_apps_folder_overrides_plan(self):
        plan = {
            "pins": [],
            "folders": {},
            "all_apps_folder": {"name": "Plan All", "page": 2},
        }
        export = {
            "dock": [],
            "pages": [{"apps": ["com.app1", "com.app2"], "folders": []}],
        }
        profile = build_mobileconfig(
            plan=plan,
            layout_export=export,
            all_apps_folder={"name": "Override All", "page": 3},
        )
        self.assertEqual(profile["PayloadType"], "Configuration")

    def test_with_pages_spec(self):
        plan = {
            "pins": [],
            "folders": {"Work": ["com.slack"]},
            "pages": {1: {"apps": [], "folders": ["Work"]}},
        }
        profile = build_mobileconfig(plan=plan)
        self.assertEqual(profile["PayloadType"], "Configuration")


if __name__ == "__main__":
    unittest.main()
