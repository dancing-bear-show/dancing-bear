"""Tests for mail/outlook/processors.py."""
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import MagicMock, patch

from mail.outlook.processors import (
    _canon_rule,
    OutlookRulesListResult,
    OutlookRulesExportResult,
    OutlookRulesSyncResult,
    OutlookRulesPlanResult,
    OutlookRulesDeleteResult,
    OutlookRulesSweepResult,
    OutlookCategoriesListResult,
    OutlookCategoriesExportResult,
    OutlookCategoriesSyncResult,
    OutlookFoldersSyncResult,
    OutlookCalendarAddResult,
    OutlookCalendarAddRecurringResult,
    OutlookCalendarAddFromConfigResult,
    OutlookRulesListProcessor,
    OutlookRulesExportProcessor,
    OutlookRulesSyncProcessor,
    OutlookRulesPlanProcessor,
    OutlookRulesDeleteProcessor,
    OutlookRulesSweepProcessor,
    OutlookCategoriesListProcessor,
    OutlookCategoriesExportProcessor,
    OutlookCategoriesSyncProcessor,
    OutlookFoldersSyncProcessor,
    OutlookCalendarAddProcessor,
    OutlookCalendarAddRecurringProcessor,
    OutlookCalendarAddFromConfigProcessor,
)
from mail.outlook.consumers import (
    OutlookRulesListPayload,
    OutlookRulesExportPayload,
    OutlookRulesSyncPayload,
    OutlookRulesPlanPayload,
    OutlookRulesDeletePayload,
    OutlookRulesSweepPayload,
    OutlookCategoriesListPayload,
    OutlookCategoriesExportPayload,
    OutlookCategoriesSyncPayload,
    OutlookFoldersSyncPayload,
    OutlookCalendarAddPayload,
    OutlookCalendarAddRecurringPayload,
    OutlookCalendarAddFromConfigPayload,
)


class TestCanonRule(unittest.TestCase):
    """Tests for _canon_rule helper function."""

    def test_basic_rule(self):
        """Test basic rule canonicalization."""
        rule = {
            "criteria": {"from": "test@example.com"},
            "action": {"addLabelIds": ["label1"]},
        }
        result = _canon_rule(rule)
        self.assertIn("test@example.com", result)

    def test_empty_rule(self):
        """Test empty rule."""
        result = _canon_rule({})
        self.assertIsInstance(result, str)

    def test_rule_with_all_criteria(self):
        """Test rule with all criteria fields."""
        rule = {
            "criteria": {
                "from": "sender@example.com",
                "to": "recipient@example.com",
                "subject": "Test Subject",
            },
            "action": {
                "addLabelIds": ["lab1", "lab2"],
                "forward": "forward@example.com",
                "moveToFolderId": "folder123",
            },
        }
        result = _canon_rule(rule)
        self.assertIn("sender@example.com", result)
        self.assertIn("folder123", result)

    def test_rule_labels_sorted(self):
        """Test that labels are sorted for consistent comparison."""
        rule1 = {"criteria": {"from": "t@e.com"}, "action": {"addLabelIds": ["b", "a"]}}
        rule2 = {"criteria": {"from": "t@e.com"}, "action": {"addLabelIds": ["a", "b"]}}
        self.assertEqual(_canon_rule(rule1), _canon_rule(rule2))


class TestResultDataclasses(unittest.TestCase):
    """Tests for result dataclasses."""

    def test_rules_list_result_defaults(self):
        """Test OutlookRulesListResult defaults."""
        result = OutlookRulesListResult()
        self.assertEqual(result.rules, [])

    def test_rules_export_result(self):
        """Test OutlookRulesExportResult."""
        result = OutlookRulesExportResult(count=5, out_path="/path/file.yaml")
        self.assertEqual(result.count, 5)

    def test_rules_sync_result(self):
        """Test OutlookRulesSyncResult."""
        result = OutlookRulesSyncResult(created=3, deleted=1)
        self.assertEqual(result.created, 3)

    def test_rules_plan_result(self):
        """Test OutlookRulesPlanResult."""
        result = OutlookRulesPlanResult(would_create=2, plan_items=["item1"])
        self.assertEqual(result.would_create, 2)

    def test_categories_sync_result(self):
        """Test OutlookCategoriesSyncResult."""
        result = OutlookCategoriesSyncResult(created=2, skipped=5)
        self.assertEqual(result.created, 2)

    def test_calendar_add_result(self):
        """Test OutlookCalendarAddResult."""
        result = OutlookCalendarAddResult(event_id="evt123", subject="Meeting")
        self.assertEqual(result.event_id, "evt123")


class TestOutlookRulesListProcessor(unittest.TestCase):
    """Tests for OutlookRulesListProcessor."""

    def test_process_success(self):
        """Test successful rules list."""
        mock_client = MagicMock()
        mock_client.list_filters.return_value = [{"id": "rule1"}]
        mock_client.get_label_id_map.return_value = {"Label1": "id1"}
        mock_client.get_folder_path_map.return_value = {"Inbox/Test": "fid1"}

        payload = OutlookRulesListPayload(client=mock_client)
        envelope = OutlookRulesListProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(len(envelope.payload.rules), 1)

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.list_filters.side_effect = Exception("API Error")

        payload = OutlookRulesListPayload(client=mock_client)
        envelope = OutlookRulesListProcessor().process(payload)

        self.assertEqual(envelope.status, "error")


class TestOutlookRulesExportProcessor(unittest.TestCase):
    """Tests for OutlookRulesExportProcessor."""

    def test_process_success(self):
        """Test successful rules export."""
        mock_client = MagicMock()
        mock_client.list_filters.return_value = [
            {"criteria": {"from": "t@e.com"}, "action": {"addLabelIds": ["l1"]}},
        ]
        mock_client.get_label_id_map.return_value = {"l1": "Label1"}
        mock_client.get_folder_path_map.return_value = {}

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            payload = OutlookRulesExportPayload(client=mock_client, out_path=f.name)
            envelope = OutlookRulesExportProcessor().process(payload)
            self.assertEqual(envelope.status, "success")

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.list_filters.side_effect = Exception("Export error")

        payload = OutlookRulesExportPayload(client=mock_client, out_path="/tmp/t.yaml")
        envelope = OutlookRulesExportProcessor().process(payload)
        self.assertEqual(envelope.status, "error")


class TestOutlookRulesSyncProcessor(unittest.TestCase):
    """Tests for OutlookRulesSyncProcessor."""

    @patch("mail.outlook.processors.load_config")
    @patch("mail.outlook.processors.normalize_filters_for_outlook")
    def test_process_success(self, mock_norm, mock_load):
        """Test successful rules sync."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{"match": {"from": "t@e.com"}, "action": {"add": ["L1"]}}]

        mock_client = MagicMock()
        mock_client.list_filters.return_value = []
        mock_client.get_label_id_map.return_value = {"L1": "id1"}
        mock_client.get_folder_path_map.return_value = {}

        payload = OutlookRulesSyncPayload(client=mock_client, config_path="/t.yaml", dry_run=True)
        envelope = OutlookRulesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 1)

    @patch("mail.outlook.processors.load_config")
    def test_process_error(self, mock_load):
        """Test error handling."""
        mock_load.side_effect = Exception("Config error")
        payload = OutlookRulesSyncPayload(client=MagicMock(), config_path="/t.yaml")
        envelope = OutlookRulesSyncProcessor().process(payload)
        self.assertEqual(envelope.status, "error")


class TestOutlookRulesPlanProcessor(unittest.TestCase):
    """Tests for OutlookRulesPlanProcessor."""

    @patch("mail.outlook.processors.load_config")
    @patch("mail.outlook.processors.normalize_filters_for_outlook")
    def test_process_success(self, mock_norm, mock_load):
        """Test successful rules plan."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{"match": {"from": "new@e.com"}, "action": {"add": ["NL"]}}]

        mock_client = MagicMock()
        mock_client.list_filters.return_value = []
        mock_client.get_label_id_map.return_value = {"NL": "id1"}
        mock_client.get_folder_id_map.return_value = {}

        payload = OutlookRulesPlanPayload(client=mock_client, config_path="/t.yaml")
        envelope = OutlookRulesPlanProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.would_create, 1)


class TestOutlookRulesDeleteProcessor(unittest.TestCase):
    """Tests for OutlookRulesDeleteProcessor."""

    def test_process_success(self):
        """Test successful rule deletion."""
        mock_client = MagicMock()
        payload = OutlookRulesDeletePayload(client=mock_client, rule_id="rule123")
        envelope = OutlookRulesDeleteProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.rule_id, "rule123")

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.delete_filter.side_effect = Exception("Delete failed")

        payload = OutlookRulesDeletePayload(client=mock_client, rule_id="rule123")
        envelope = OutlookRulesDeleteProcessor().process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 3)


class TestOutlookRulesSweepProcessor(unittest.TestCase):
    """Tests for OutlookRulesSweepProcessor."""

    @patch("mail.outlook.processors.load_config")
    @patch("mail.outlook.processors.normalize_filters_for_outlook")
    def test_process_success_dry_run(self, mock_norm, mock_load):
        """Test successful rules sweep dry run."""
        mock_load.return_value = {"filters": []}
        mock_norm.return_value = [{"match": {"from": "news@e.com"}, "action": {"moveToFolder": "Archive"}}]

        mock_client = MagicMock()
        mock_client.get_folder_path_map.return_value = {"Archive": "f1"}
        mock_client.search_inbox_messages.return_value = ["m1", "m2"]

        payload = OutlookRulesSweepPayload(
            client=mock_client, config_path="/t.yaml", dry_run=True, move_to_folders=True
        )
        envelope = OutlookRulesSweepProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.moved, 2)


class TestOutlookCategoriesListProcessor(unittest.TestCase):
    """Tests for OutlookCategoriesListProcessor."""

    def test_process_success(self):
        """Test successful categories list."""
        mock_client = MagicMock()
        mock_client.list_labels.return_value = [{"name": "Work"}]

        payload = OutlookCategoriesListPayload(client=mock_client)
        envelope = OutlookCategoriesListProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(len(envelope.payload.categories), 1)


class TestOutlookCategoriesExportProcessor(unittest.TestCase):
    """Tests for OutlookCategoriesExportProcessor."""

    def test_process_success(self):
        """Test successful categories export."""
        mock_client = MagicMock()
        mock_client.list_labels.return_value = [{"name": "Work", "color": {"name": "blue"}}]

        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            payload = OutlookCategoriesExportPayload(client=mock_client, out_path=f.name)
            envelope = OutlookCategoriesExportProcessor().process(payload)
            self.assertEqual(envelope.status, "success")
            self.assertEqual(envelope.payload.count, 1)


class TestOutlookCategoriesSyncProcessor(unittest.TestCase):
    """Tests for OutlookCategoriesSyncProcessor."""

    @patch("mail.outlook.processors.load_config")
    @patch("mail.outlook.processors.normalize_labels_for_outlook")
    def test_process_success(self, mock_norm, mock_load):
        """Test successful categories sync."""
        mock_load.return_value = {"labels": []}
        mock_norm.return_value = [{"name": "NewCat"}]

        mock_client = MagicMock()
        mock_client.list_labels.return_value = []

        payload = OutlookCategoriesSyncPayload(client=mock_client, config_path="/t.yaml", dry_run=True)
        envelope = OutlookCategoriesSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 1)

    @patch("mail.outlook.processors.load_config")
    def test_process_invalid_labels(self, mock_load):
        """Test error on invalid labels format."""
        mock_load.return_value = {"labels": "not a list"}
        payload = OutlookCategoriesSyncPayload(client=MagicMock(), config_path="/t.yaml")
        envelope = OutlookCategoriesSyncProcessor().process(payload)
        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 2)


class TestOutlookFoldersSyncProcessor(unittest.TestCase):
    """Tests for OutlookFoldersSyncProcessor."""

    @patch("mail.outlook.processors.load_config")
    def test_process_success(self, mock_load):
        """Test successful folders sync."""
        mock_load.return_value = {"labels": [{"name": "NewFolder"}]}

        mock_client = MagicMock()
        mock_client.get_folder_path_map.return_value = {}
        mock_client.ensure_folder_path.return_value = "f123"

        payload = OutlookFoldersSyncPayload(client=mock_client, config_path="/t.yaml")
        envelope = OutlookFoldersSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 1)

    @patch("mail.outlook.processors.load_config")
    def test_process_skips_existing(self, mock_load):
        """Test skipping existing folders."""
        mock_load.return_value = {"labels": [{"name": "Existing"}]}

        mock_client = MagicMock()
        mock_client.get_folder_path_map.return_value = {"Existing": "f1"}

        payload = OutlookFoldersSyncPayload(client=mock_client, config_path="/t.yaml")
        envelope = OutlookFoldersSyncProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.skipped, 1)


class TestOutlookCalendarAddProcessor(unittest.TestCase):
    """Tests for OutlookCalendarAddProcessor."""

    def test_process_success(self):
        """Test successful event creation."""
        mock_client = MagicMock()
        mock_client.create_event.return_value = {"id": "e123", "subject": "Meet"}

        payload = OutlookCalendarAddPayload(
            client=mock_client, subject="Meet", start_iso="2024-01-15T10:00", end_iso="2024-01-15T11:00"
        )
        envelope = OutlookCalendarAddProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.event_id, "e123")

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.create_event.side_effect = Exception("Calendar error")

        payload = OutlookCalendarAddPayload(
            client=mock_client, subject="Meet", start_iso="2024-01-15T10:00", end_iso="2024-01-15T11:00"
        )
        envelope = OutlookCalendarAddProcessor().process(payload)
        self.assertEqual(envelope.status, "error")


class TestOutlookCalendarAddRecurringProcessor(unittest.TestCase):
    """Tests for OutlookCalendarAddRecurringProcessor."""

    def test_process_success(self):
        """Test successful recurring event creation."""
        mock_client = MagicMock()
        mock_client.create_recurring_event.return_value = {"id": "r123", "subject": "Weekly"}

        payload = OutlookCalendarAddRecurringPayload(
            client=mock_client, subject="Weekly", start_time="09:00", end_time="09:30",
            repeat="weekly", range_start="2024-01-15"
        )
        envelope = OutlookCalendarAddRecurringProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.event_id, "r123")


class TestOutlookCalendarAddFromConfigProcessor(unittest.TestCase):
    """Tests for OutlookCalendarAddFromConfigProcessor."""

    @patch("mail.outlook.processors.load_config")
    def test_process_success_single(self, mock_load):
        """Test successful single event creation."""
        mock_load.return_value = {"events": [{"subject": "Meet", "start": "2024-01-15T10:00", "end": "2024-01-15T11:00"}]}

        mock_client = MagicMock()
        mock_client.create_event.return_value = {"id": "e1"}

        payload = OutlookCalendarAddFromConfigPayload(client=mock_client, config_path="/t.yaml")
        envelope = OutlookCalendarAddFromConfigProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 1)

    @patch("mail.outlook.processors.load_config")
    def test_process_success_recurring(self, mock_load):
        """Test successful recurring event creation."""
        mock_load.return_value = {"events": [{"subject": "Weekly", "repeat": "weekly", "start_time": "09:00", "end_time": "09:30", "start_date": "2024-01-15"}]}

        mock_client = MagicMock()
        mock_client.create_recurring_event.return_value = {"id": "r1"}

        payload = OutlookCalendarAddFromConfigPayload(client=mock_client, config_path="/t.yaml")
        envelope = OutlookCalendarAddFromConfigProcessor().process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.created, 1)

    @patch("mail.outlook.processors.load_config")
    def test_process_invalid_events(self, mock_load):
        """Test error on invalid events format."""
        mock_load.return_value = {"events": "not a list"}
        payload = OutlookCalendarAddFromConfigPayload(client=MagicMock(), config_path="/t.yaml")
        envelope = OutlookCalendarAddFromConfigProcessor().process(payload)
        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 2)


if __name__ == "__main__":
    unittest.main()
