"""Tests for calendars/agentic.py flow map branches and capsule sections."""
from __future__ import annotations

import unittest
from unittest.mock import patch


def _make_path_mock(true_paths: set):
    """Return a function that returns True only for the given paths."""
    def _exists(path):
        return tuple(path) in true_paths
    return _exists


class TestOutlookAddFlows(unittest.TestCase):
    def test_add_only(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "add")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Outlook add", result)
        self.assertIn("One-off", result)
        self.assertNotIn("Recurring", result)

    def test_add_recurring_only(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "add-recurring")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Outlook add", result)
        self.assertIn("Recurring", result)
        self.assertNotIn("One-off", result)

    def test_both_add_and_add_recurring(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "add"), ("outlook", "add-recurring")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("One-off", result)
        self.assertIn("Recurring", result)

    def test_add_from_config_and_verify(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "add-from-config"), ("outlook", "verify-from-config")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Outlook from YAML", result)
        self.assertIn("add-from-config", result)
        self.assertIn("verify-from-config", result)

    def test_add_from_config_without_verify_excluded(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "add-from-config")}  # no verify-from-config
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertNotIn("Outlook from YAML", result)


class TestOutlookManageFlows(unittest.TestCase):
    def test_locations_flow(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "update-locations"), ("outlook", "apply-locations")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Locations", result)
        self.assertIn("update-locations", result)
        self.assertIn("apply-locations", result)

    def test_reminders_flow(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "reminders-off")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Reminders", result)
        self.assertIn("reminders-off", result)

    def test_dedup_flow(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "dedup")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Deduplicate", result)

    def test_list_one_offs_flow(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "list-one-offs")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("List one-offs", result)

    def test_remove_from_config_flow(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "remove-from-config")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Remove from YAML", result)

    def test_calendar_share_flow(self):
        from calendars import agentic as mod
        true_paths = {("outlook", "calendar-share")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Share", result)


class TestGmailScanFlows(unittest.TestCase):
    def test_scan_classes(self):
        from calendars import agentic as mod
        true_paths = {("gmail", "scan-classes")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Gmail scan", result)
        self.assertIn("scan-classes", result)
        self.assertNotIn("scan-receipts", result)
        self.assertNotIn("scan-activerh", result)

    def test_scan_receipts(self):
        from calendars import agentic as mod
        true_paths = {("gmail", "scan-receipts")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Gmail scan", result)
        self.assertIn("scan-receipts", result)

    def test_scan_activerh(self):
        from calendars import agentic as mod
        true_paths = {("gmail", "scan-activerh")}
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("Gmail scan", result)
        self.assertIn("scan-activerh", result)

    def test_all_gmail_scans(self):
        from calendars import agentic as mod
        true_paths = {
            ("gmail", "scan-classes"),
            ("gmail", "scan-receipts"),
            ("gmail", "scan-activerh"),
        }
        with patch.object(mod, "_cli_path_exists", side_effect=_make_path_mock(true_paths)):
            result = mod._flow_map()
        self.assertIn("scan-classes", result)
        self.assertIn("scan-receipts", result)
        self.assertIn("scan-activerh", result)


class TestCapsuleAndDomainMapWithFlows(unittest.TestCase):
    def _all_true_mock(self, path):
        return True

    def test_capsule_with_all_flows(self):
        from calendars import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=self._all_true_mock), \
             patch.object(mod, "_cli_tree", return_value="tree-content"):
            cap = mod.build_agentic_capsule()
        self.assertIn("tree-content", cap)
        self.assertIn("Outlook add", cap)

    def test_domain_map_with_tree_and_flows(self):
        from calendars import agentic as mod
        with patch.object(mod, "_cli_path_exists", side_effect=self._all_true_mock), \
             patch.object(mod, "_cli_tree", return_value="tree-content"):
            dm = mod.build_domain_map()
        self.assertIn("tree-content", dm)
        self.assertIn("Top-Level", dm)

    def test_capsule_no_tree_no_flows(self):
        from calendars import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=False), \
             patch.object(mod, "_cli_tree", return_value=""):
            cap = mod.build_agentic_capsule()
        self.assertIsInstance(cap, str)
        self.assertGreater(len(cap), 0)

    def test_domain_map_no_tree_no_flows(self):
        from calendars import agentic as mod
        with patch.object(mod, "_cli_path_exists", return_value=False), \
             patch.object(mod, "_cli_tree", return_value=""):
            dm = mod.build_domain_map()
        self.assertIn("Top-Level", dm)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
