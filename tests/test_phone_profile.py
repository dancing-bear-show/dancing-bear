import unittest

from phone.profile import build_mobileconfig


def _extract_folder_apps(folder_item):
    apps = []
    for page in folder_item.get("Pages") or []:
        for it in page or []:
            apps.append(it.get("BundleID"))
    return apps


class TestPhoneProfile(unittest.TestCase):
    def test_build_mobileconfig_all_apps_folder_uses_remaining_apps(self):
        plan = {
            "dock": ["com.example.dock"],
            "folders": {"Keep": ["com.example.a"]},
            "pages": {1: {"folders": ["Keep"]}},
            "all_apps_folder": {"name": "All Apps", "page": 2},
        }
        layout_export = {
            "dock": ["com.example.dock"],
            "pages": [
                {"apps": ["com.example.a", "com.example.b", "com.example.c"], "folders": []},
            ],
        }

        profile = build_mobileconfig(
            plan=plan,
            layout_export=layout_export,
            top_identifier="com.example.profile",
            hs_identifier="com.example.hslayout",
        )

        payload = profile["PayloadContent"][0]
        self.assertEqual(
            payload["Dock"],
            [{"Type": "Application", "BundleID": "com.example.dock"}],
        )

        pages = payload["Pages"]
        # Page 1 contains the Keep folder only
        self.assertEqual(pages[0][0]["DisplayName"], "Keep")
        # Page 2 contains the All Apps folder with remaining apps
        all_apps_folder = pages[1][0]
        self.assertEqual(all_apps_folder["DisplayName"], "All Apps")
        self.assertEqual(set(_extract_folder_apps(all_apps_folder)), {"com.example.b", "com.example.c"})
