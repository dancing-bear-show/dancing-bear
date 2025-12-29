"""Tests for phone/device.py - Device I/O and credential helpers."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from phone.device import (
    _get_bundle_id,
    _parse_list_format,
    _parse_plist_format,
    _fallback_parse,
    _first_value,
    resolve_p12_path,
    map_udid_to_ecid,
)
from tests.phone_tests.fixtures import make_ini_section, make_list_data, make_plist_data


class TestGetBundleId(unittest.TestCase):
    """Tests for _get_bundle_id helper."""

    def test_extracts_bundle_identifier(self):
        cases = [
            ({"bundleIdentifier": "com.app"}, "com.app"),
            ({"displayIdentifier": "com.app"}, "com.app"),
            ({"bundleIdentifier": "com.first", "displayIdentifier": "com.second"}, "com.first"),
            ({"bundleIdentifier": "", "displayIdentifier": "com.fallback"}, "com.fallback"),
        ]
        for item, expected in cases:
            with self.subTest(item=item):
                self.assertEqual(_get_bundle_id(item), expected)

    def test_returns_none_for_invalid_input(self):
        for item in ["string", 123, None, [], {}]:
            with self.subTest(item=item):
                self.assertIsNone(_get_bundle_id(item))


class TestParseListFormat(unittest.TestCase):
    """Tests for _parse_list_format - cfgutil JSON list format."""

    def test_basic_dock_and_pages(self):
        data = make_list_data(["com.dock1", "com.dock2"], [["com.app1", "com.app2"]])
        result = _parse_list_format(data)
        self.assertEqual(result["dock"], ["com.dock1", "com.dock2"])
        self.assertEqual(result["pages"][0]["apps"], ["com.app1", "com.app2"])

    def test_folder_in_page(self):
        data = make_list_data([], [[["Work", "com.work1", "com.work2"]]])
        result = _parse_list_format(data)
        self.assertEqual(result["pages"][0]["folders"][0]["name"], "Work")
        self.assertIn("com.work1", result["pages"][0]["folders"][0]["apps"])

    def test_mixed_apps_and_folders(self):
        data = make_list_data(["com.dock"], [["com.app1", ["Folder", "com.f1"], "com.app2"]])
        result = _parse_list_format(data)
        self.assertEqual(result["pages"][0]["apps"], ["com.app1", "com.app2"])
        self.assertEqual(len(result["pages"][0]["folders"]), 1)

    def test_filters_invalid_items(self):
        data = [["com.valid", 123, None, "com.also.valid"], "not a list", ["com.app"]]
        result = _parse_list_format(data)
        self.assertEqual(result["dock"], ["com.valid", "com.also.valid"])
        self.assertEqual(len(result["pages"]), 1)


class TestParsePlistFormat(unittest.TestCase):
    """Tests for _parse_plist_format - cfgutil plist dict format."""

    def test_basic_buttonbar_and_iconlists(self):
        data = make_plist_data(dock=["com.dock1", "com.dock2"], apps=["com.app1"])
        result = _parse_plist_format(data)
        self.assertEqual(result["dock"], ["com.dock1", "com.dock2"])
        self.assertEqual(result["pages"][0]["apps"], ["com.app1"])

    def test_folder_in_iconlists(self):
        data = make_plist_data(folders=[{"name": "Work", "apps": ["com.work1"]}])
        result = _parse_plist_format(data)
        self.assertEqual(result["pages"][0]["folders"][0]["name"], "Work")
        self.assertEqual(result["pages"][0]["folders"][0]["apps"], ["com.work1"])

    def test_empty_data(self):
        result = _parse_plist_format({})
        self.assertEqual(result, {"dock": [], "pages": []})

    def test_display_identifier_fallback(self):
        data = {"buttonBar": [{"displayIdentifier": "com.dock"}], "iconLists": [[{"displayIdentifier": "com.app"}]]}
        result = _parse_plist_format(data)
        self.assertEqual(result["dock"], ["com.dock"])
        self.assertEqual(result["pages"][0]["apps"], ["com.app"])


class TestFallbackParse(unittest.TestCase):
    """Tests for _fallback_parse dispatcher."""

    def test_dispatches_by_type(self):
        cases = [
            (make_list_data(["com.dock"], [["com.app"]]), ["com.dock"]),
            (make_plist_data(dock=["com.dock"]), ["com.dock"]),
        ]
        for data, expected_dock in cases:
            with self.subTest(data_type=type(data).__name__):
                self.assertEqual(_fallback_parse(data)["dock"], expected_dock)

    def test_returns_empty_for_invalid(self):
        for data in [[], None, "invalid", 123]:
            with self.subTest(data=data):
                self.assertEqual(_fallback_parse(data), {})


class TestFirstValue(unittest.TestCase):
    """Tests for _first_value helper."""

    def test_key_lookup(self):
        cases = [
            ({"key1": "val1", "key2": "val2"}, ("key1", "key2"), "val1"),
            ({"key1": "", "key2": "val2"}, ("key1", "key2"), "val2"),
            ({"other": "val"}, ("key1", "key2"), None),
            ({}, ("key1",), None),
        ]
        for section, keys, expected in cases:
            with self.subTest(section=section, keys=keys):
                self.assertEqual(_first_value(section, keys), expected)


class TestResolveP12Path(unittest.TestCase):
    """Tests for resolve_p12_path credential resolution."""

    def test_explicit_path_takes_precedence(self):
        path, pwd = resolve_p12_path("/explicit.p12", "pass", "profile", {})
        self.assertEqual((path, pwd), ("/explicit.p12", "pass"))

    def test_reads_from_ini(self):
        ini = {"profile": make_ini_section("/from/ini.p12", "inipass")}
        path, pwd = resolve_p12_path(None, None, "profile", ini)
        self.assertEqual((path, pwd), ("/from/ini.p12", "inipass"))

    def test_fallback_keys(self):
        ini = {"profile": make_ini_section("/fallback.p12", key_prefix="ios_home_layout_identity")}
        path, _ = resolve_p12_path(None, None, "profile", ini)
        self.assertEqual(path, "/fallback.p12")

    def test_expands_tilde(self):
        ini = {"profile": make_ini_section("~/cert.p12")}
        path, _ = resolve_p12_path(None, None, "profile", ini)
        self.assertNotIn("~", path)

    def test_explicit_pass_preserved(self):
        ini = {"profile": make_ini_section("/ini.p12")}
        _, pwd = resolve_p12_path(None, "explicit_pass", "profile", ini)
        self.assertEqual(pwd, "explicit_pass")

    def test_missing_profile(self):
        self.assertEqual(resolve_p12_path(None, None, "missing", {}), (None, None))


class TestMapUdidToEcid(unittest.TestCase):
    """Tests for map_udid_to_ecid."""

    def _run_with_output(self, output, udid="ABC123"):
        with patch("phone.device.subprocess.check_output", return_value=output):
            return map_udid_to_ecid("/usr/bin/cfgutil", udid)

    def test_extracts_ecid(self):
        cases = [
            ("Device  UDID:ABC123  ECID:0x12345\n", "0x12345"),
            ("Device  UDID:ABC123  ECID: 0x12345\n", "0x12345"),
            ("Device  UDID:OTHER  ECID:0x99999\n", ""),
            ("Device  UDID:ABC123\n", ""),
        ]
        for output, expected in cases:
            with self.subTest(output=output):
                self.assertEqual(self._run_with_output(output), expected)

    def test_raises_on_failure(self):
        with patch("phone.device.subprocess.check_output", side_effect=Exception("error")):
            with self.assertRaises(RuntimeError):
                map_udid_to_ecid("/usr/bin/cfgutil", "ABC123")


if __name__ == "__main__":
    unittest.main()
