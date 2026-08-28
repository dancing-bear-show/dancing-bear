"""Tests for mail/outlook/processors_calendar.py — coverage gap fill.

Targets the missing lines/branches identified from ``make cov``:
  74-76, 108->110, 122-123, 155-156, 166-171, 179, 181-182, 183->176, 199,
  211-212, 228, 231, 241-242, 246->238, 311-312, 341-342, 351, 409-410, 417,
  432-433
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from mail.outlook.processors_calendar import (
    OutlookCategoriesExportProcessor,
    OutlookCategoriesSyncProcessor,
    OutlookCalendarAddFromConfigProcessor,
    OutlookCalendarAddRecurringProcessor,
    OutlookFoldersSyncProcessor,
    _entry_name,
)
from mail.outlook.consumers import (
    OutlookCategoriesExportPayload,
    OutlookCategoriesSyncPayload,
    OutlookCalendarAddFromConfigPayload,
    OutlookCalendarAddRecurringPayload,
    OutlookFoldersSyncPayload,
)


# ---------------------------------------------------------------------------
# _entry_name helper (lines 74-76)
# ---------------------------------------------------------------------------

class TestEntryName(unittest.TestCase):
    """Tests for _entry_name module-level helper."""

    def test_dict_returns_name(self):
        self.assertEqual(_entry_name({"name": "Work"}), "Work")

    def test_str_returns_string(self):
        # line 74-75
        self.assertEqual(_entry_name("Personal"), "Personal")

    def test_other_type_returns_none(self):
        # line 76
        self.assertIsNone(_entry_name(42))

    def test_none_returns_none(self):
        self.assertIsNone(_entry_name(None))


# ---------------------------------------------------------------------------
# OutlookCategoriesExportProcessor (lines 108->110, 122-123)
# ---------------------------------------------------------------------------

class TestCategoriesExportBranches(unittest.TestCase):
    """Coverage for export processor branches."""

    def test_color_without_name_not_included(self):
        """Color dict missing 'name' key should not be included (line 108->110)."""
        mock_client = MagicMock()
        mock_client.list_labels.return_value = [
            {"name": "Work", "color": {"preset": "light-blue"}},  # no 'name' key
        ]
        with patch("core.yamlio.dump_config"):
            payload = OutlookCategoriesExportPayload(client=mock_client, out_path="/tmp/test.yaml")
            envelope = OutlookCategoriesExportProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.count, 1)

    def test_no_color_key_not_included(self):
        """Category with no color key should export without color."""
        mock_client = MagicMock()
        mock_client.list_labels.return_value = [{"name": "NoColor"}]
        with patch("core.yamlio.dump_config"):
            payload = OutlookCategoriesExportPayload(client=mock_client, out_path="/tmp/test.yaml")
            envelope = OutlookCategoriesExportProcessor().process(payload)

        self.assertEqual(envelope.status, "success")

    def test_process_error_path(self):
        """Exception from list_labels triggers error envelope (lines 122-123)."""
        mock_client = MagicMock()
        mock_client.list_labels.side_effect = RuntimeError("graph down")

        payload = OutlookCategoriesExportPayload(client=mock_client, out_path="/tmp/export.yaml")
        envelope = OutlookCategoriesExportProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertIn("graph down", envelope.diagnostics["error"])
        self.assertEqual(envelope.diagnostics["code"], 1)


# ---------------------------------------------------------------------------
# OutlookCategoriesSyncProcessor (lines 155-156, 166-171, 179, 181-182, 183->176)
# ---------------------------------------------------------------------------

class TestCategoriesSyncBranches(unittest.TestCase):
    """Coverage for sync processor internal branches."""

    @patch("core.yamlio.load_config")
    @patch("mail.dsl.normalize_labels_for_outlook")
    def test_process_error_path(self, mock_norm, mock_load):
        """Exception during sync triggers error envelope (lines 155-156)."""
        mock_load.side_effect = IOError("file missing")
        payload = OutlookCategoriesSyncPayload(client=MagicMock(), config_path="/missing.yaml")
        envelope = OutlookCategoriesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 1)

    def test_create_one_category_dry_run_returns_true(self):
        """_create_one_category with dry_run=True must not call client (line 165)."""
        proc = OutlookCategoriesSyncProcessor()
        mock_client = MagicMock()
        result = proc._create_one_category(mock_client, {"name": "Work"}, dry_run=True)

        self.assertTrue(result)
        mock_client.create_label.assert_not_called()

    def test_create_one_category_real_run_dict_entry(self):
        """_create_one_category without dry_run calls create_label (lines 167-169)."""
        proc = OutlookCategoriesSyncProcessor()
        mock_client = MagicMock()
        result = proc._create_one_category(mock_client, {"name": "Work", "color": "blue"}, dry_run=False)

        self.assertTrue(result)
        mock_client.create_label.assert_called_once_with("Work", color="blue")

    def test_create_one_category_real_run_str_entry(self):
        """_create_one_category with str entry passes str directly (lines 167-169)."""
        proc = OutlookCategoriesSyncProcessor()
        mock_client = MagicMock()
        result = proc._create_one_category(mock_client, "Personal", dry_run=False)

        self.assertTrue(result)
        mock_client.create_label.assert_called_once_with("Personal", color=None)

    def test_create_one_category_create_label_raises(self):
        """Exception during create_label returns False (lines 170-171)."""
        proc = OutlookCategoriesSyncProcessor()
        mock_client = MagicMock()
        mock_client.create_label.side_effect = Exception("already exists")
        result = proc._create_one_category(mock_client, {"name": "Work"}, dry_run=False)

        self.assertFalse(result)

    def test_sync_categories_skips_empty_name(self):
        """Entry with no name is skipped without incrementing any counter (line 179)."""
        proc = OutlookCategoriesSyncProcessor()
        mock_client = MagicMock()
        # Dict entry with no 'name' key -> name is None
        created, skipped = proc._sync_categories(mock_client, [{"color": "red"}], {}, dry_run=True)

        self.assertEqual(created, 0)
        self.assertEqual(skipped, 0)

    def test_sync_categories_skips_existing(self):
        """Existing category is skipped (lines 181-182)."""
        proc = OutlookCategoriesSyncProcessor()
        mock_client = MagicMock()
        existing = {"Work": {"name": "Work"}}
        created, skipped = proc._sync_categories(mock_client, [{"name": "Work"}], existing, dry_run=True)

        self.assertEqual(created, 0)
        self.assertEqual(skipped, 1)

    def test_sync_categories_creation_failure_not_counted(self):
        """When _create_one_category returns False, created is not incremented (line 183->176)."""
        proc = OutlookCategoriesSyncProcessor()
        mock_client = MagicMock()
        mock_client.create_label.side_effect = Exception("fail")
        created, skipped = proc._sync_categories(mock_client, [{"name": "New"}], {}, dry_run=False)

        self.assertEqual(created, 0)
        self.assertEqual(skipped, 0)


# ---------------------------------------------------------------------------
# OutlookFoldersSyncProcessor (lines 199, 211-212, 228, 231, 241-242, 246->238)
# ---------------------------------------------------------------------------

class TestFoldersSyncBranches(unittest.TestCase):
    """Coverage for folders sync internal branches."""

    @patch("core.yamlio.load_config")
    def test_invalid_labels_not_list(self, mock_load):
        """Non-list labels triggers error envelope (line 199)."""
        mock_load.return_value = {"labels": "not-a-list"}
        payload = OutlookFoldersSyncPayload(client=MagicMock(), config_path="/t.yaml")
        envelope = OutlookFoldersSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 2)

    @patch("core.yamlio.load_config")
    def test_process_error_path(self, mock_load):
        """Exception during process triggers error envelope (lines 211-212)."""
        mock_load.side_effect = IOError("cannot read")
        payload = OutlookFoldersSyncPayload(client=MagicMock(), config_path="/missing.yaml")
        envelope = OutlookFoldersSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 1)

    def test_sync_one_folder_dry_run_returns_true_without_api_call(self):
        """dry_run=True returns True immediately without calling ensure_folder_path (line 227-228)."""
        proc = OutlookFoldersSyncProcessor()
        mock_client = MagicMock()
        path_map: dict = {}
        result = proc._sync_one_folder(mock_client, "NewFolder", path_map, dry_run=True)

        self.assertTrue(result)
        mock_client.ensure_folder_path.assert_not_called()
        self.assertNotIn("NewFolder", path_map)

    def test_sync_one_folder_ensure_returns_falsy(self):
        """ensure_folder_path returning falsy returns False (line 230)."""
        proc = OutlookFoldersSyncProcessor()
        mock_client = MagicMock()
        mock_client.ensure_folder_path.return_value = ""  # falsy
        path_map: dict = {}
        result = proc._sync_one_folder(mock_client, "NewFolder", path_map, dry_run=False)

        self.assertFalse(result)
        self.assertNotIn("NewFolder", path_map)

    def test_sync_one_folder_ensure_returns_id(self):
        """ensure_folder_path success updates path_map and returns True (line 231)."""
        proc = OutlookFoldersSyncProcessor()
        mock_client = MagicMock()
        mock_client.ensure_folder_path.return_value = "fid42"
        path_map: dict = {}
        result = proc._sync_one_folder(mock_client, "NewFolder", path_map, dry_run=False)

        self.assertTrue(result)
        self.assertEqual(path_map["NewFolder"], "fid42")

    def test_sync_folders_skips_bracket_name(self):
        """Entry with name starting with '[' is skipped (lines 241-242)."""
        proc = OutlookFoldersSyncProcessor()
        mock_client = MagicMock()
        created, skipped = proc._sync_folders(mock_client, [{"name": "[Category]"}], {}, dry_run=True)

        self.assertEqual(created, 0)
        self.assertEqual(skipped, 1)

    def test_sync_folders_entry_without_name_no_count(self):
        """Entry with no name results in no created/skipped count."""
        proc = OutlookFoldersSyncProcessor()
        mock_client = MagicMock()
        created, skipped = proc._sync_folders(mock_client, [None], {}, dry_run=True)

        self.assertEqual(created, 0)
        self.assertEqual(skipped, 0)

    def test_sync_folders_creation_failure_not_counted(self):
        """When _sync_one_folder returns False, created is not incremented (line 246->238)."""
        proc = OutlookFoldersSyncProcessor()
        mock_client = MagicMock()
        mock_client.ensure_folder_path.return_value = ""  # causes False
        created, skipped = proc._sync_folders(mock_client, [{"name": "NewFolder"}], {}, dry_run=False)

        self.assertEqual(created, 0)
        self.assertEqual(skipped, 0)


# ---------------------------------------------------------------------------
# OutlookCalendarAddRecurringProcessor (lines 311-312)
# ---------------------------------------------------------------------------

class TestCalendarAddRecurringBranches(unittest.TestCase):
    """Coverage for recurring add processor error path."""

    def test_process_error_path(self):
        """Exception from create_recurring_event triggers error envelope (lines 311-312)."""
        mock_client = MagicMock()
        mock_client.create_recurring_event.side_effect = RuntimeError("calendar API down")

        payload = OutlookCalendarAddRecurringPayload(
            client=mock_client,
            subject="Weekly Standup",
            start_time="09:00",
            end_time="09:30",
            repeat="weekly",
            range_start="2024-01-15",
        )
        envelope = OutlookCalendarAddRecurringProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 3)
        self.assertIn("calendar API down", envelope.diagnostics["error"])


# ---------------------------------------------------------------------------
# OutlookCalendarAddFromConfigProcessor (lines 341-342, 351, 409-410, 417, 432-433)
# ---------------------------------------------------------------------------

class TestCalendarAddFromConfigBranches(unittest.TestCase):
    """Coverage for add-from-config processor branches."""

    @patch("core.yamlio.load_config")
    def test_process_error_path(self, mock_load):
        """Exception from load_config triggers error envelope (lines 341-342)."""
        mock_load.side_effect = IOError("file not found")
        payload = OutlookCalendarAddFromConfigPayload(client=MagicMock(), config_path="/missing.yaml")
        envelope = OutlookCalendarAddFromConfigProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 1)

    def test_create_one_event_no_subject_returns_false(self):
        """Event dict without 'subject' returns False (line 351)."""
        proc = OutlookCalendarAddFromConfigProcessor()
        mock_client = MagicMock()
        result = proc._create_one_event_from_config(
            {"start": "2024-01-15T10:00", "end": "2024-01-15T11:00"},
            mock_client,
            False,
        )

        self.assertFalse(result)
        mock_client.create_event.assert_not_called()

    def test_create_one_event_non_dict_returns_false(self):
        """Non-dict event entry returns False (line 351 branch)."""
        proc = OutlookCalendarAddFromConfigProcessor()
        result = proc._create_one_event_from_config("not a dict", MagicMock(), False)

        self.assertFalse(result)

    def test_create_recurring_event_exception_returns_false(self):
        """Exception from create_recurring_event returns False (lines 409-410)."""
        proc = OutlookCalendarAddFromConfigProcessor()
        mock_client = MagicMock()
        mock_client.create_recurring_event.side_effect = RuntimeError("API error")

        ev = {
            "subject": "Weekly",
            "repeat": "weekly",
            "start_time": "09:00",
            "end_time": "09:30",
            "start_date": "2024-01-15",
        }
        result = proc._create_recurring_event(ev, mock_client, False)

        self.assertFalse(result)

    def test_create_recurring_event_success(self):
        """Happy path for _create_recurring_event returns True."""
        proc = OutlookCalendarAddFromConfigProcessor()
        mock_client = MagicMock()
        mock_client.create_recurring_event.return_value = {"id": "r1"}

        ev = {
            "subject": "Weekly",
            "repeat": "weekly",
            "start_time": "09:00",
            "end_time": "09:30",
            "start_date": "2024-01-15",
        }
        result = proc._create_recurring_event(ev, mock_client, False)

        self.assertTrue(result)

    def test_create_single_event_missing_start_returns_false(self):
        """Missing start ISO returns False (line 417)."""
        proc = OutlookCalendarAddFromConfigProcessor()
        mock_client = MagicMock()
        ev = {"subject": "Meet", "end": "2024-01-15T11:00"}  # no 'start'
        result = proc._create_single_event(ev, mock_client, False)

        self.assertFalse(result)
        mock_client.create_event.assert_not_called()

    def test_create_single_event_missing_end_returns_false(self):
        """Missing end ISO returns False (line 417)."""
        proc = OutlookCalendarAddFromConfigProcessor()
        mock_client = MagicMock()
        ev = {"subject": "Meet", "start": "2024-01-15T10:00"}  # no 'end'
        result = proc._create_single_event(ev, mock_client, False)

        self.assertFalse(result)

    def test_create_single_event_exception_returns_false(self):
        """Exception from create_event returns False (lines 432-433)."""
        proc = OutlookCalendarAddFromConfigProcessor()
        mock_client = MagicMock()
        mock_client.create_event.side_effect = RuntimeError("network error")

        ev = {"subject": "Meet", "start": "2024-01-15T10:00", "end": "2024-01-15T11:00"}
        result = proc._create_single_event(ev, mock_client, False)

        self.assertFalse(result)

    def test_create_single_event_success(self):
        """Happy path for _create_single_event returns True."""
        proc = OutlookCalendarAddFromConfigProcessor()
        mock_client = MagicMock()
        mock_client.create_event.return_value = {"id": "e1"}

        ev = {"subject": "Meet", "start": "2024-01-15T10:00", "end": "2024-01-15T11:00"}
        result = proc._create_single_event(ev, mock_client, False)

        self.assertTrue(result)

    def test_build_recurring_event_range_prefers_nested_block(self):
        """_build_recurring_event_range prefers 'range' sub-block over top-level keys."""
        proc = OutlookCalendarAddFromConfigProcessor()
        ev = {
            "start_date": "2024-01-01",
            "range": {"start_date": "2024-06-01", "until": "2024-12-31"},
        }
        start_date, until = proc._build_recurring_event_range(ev)

        self.assertEqual(start_date, "2024-06-01")
        self.assertEqual(until, "2024-12-31")

    def test_build_recurring_event_range_falls_back_to_top_level(self):
        """_build_recurring_event_range falls back to top-level start_date when no range block."""
        proc = OutlookCalendarAddFromConfigProcessor()
        ev = {"start_date": "2024-01-15", "until": "2024-12-31"}
        start_date, until = proc._build_recurring_event_range(ev)

        self.assertEqual(start_date, "2024-01-15")
        self.assertEqual(until, "2024-12-31")

    def test_build_recurring_event_params_legacy_aliases(self):
        """_build_recurring_event_params resolves legacy camelCase aliases."""
        proc = OutlookCalendarAddFromConfigProcessor()
        ev = {
            "subject": "Weekly",
            "repeat": "weekly",
            "startTime": "09:00",
            "endTime": "09:30",
            "byDay": "MO,WE,FR",
            "bodyHtml": "<p>hello</p>",
            "startDate": "2024-01-15",
        }
        params = proc._build_recurring_event_params(ev, no_reminder=False)

        self.assertEqual(params.start_time, "09:00")
        self.assertEqual(params.end_time, "09:30")
        self.assertEqual(params.byday, "MO,WE,FR")
        self.assertEqual(params.body_html, "<p>hello</p>")

    def test_first_present_returns_first_truthy(self):
        """_first_present returns first non-falsy value."""
        proc = OutlookCalendarAddFromConfigProcessor()
        ev = {"a": "", "b": None, "c": "found"}
        result = proc._first_present(ev, "a", "b", "c", default="fallback")
        self.assertEqual(result, "found")

    def test_first_present_uses_default(self):
        """_first_present returns default when all keys missing or falsy."""
        proc = OutlookCalendarAddFromConfigProcessor()
        ev = {"a": "", "b": None}
        result = proc._first_present(ev, "a", "b", default="fallback")
        self.assertEqual(result, "fallback")


if __name__ == "__main__":
    unittest.main()
