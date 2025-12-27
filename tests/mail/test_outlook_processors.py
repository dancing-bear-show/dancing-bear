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
    OutlookRulesDeleteProcessor,
    OutlookCategoriesListProcessor,
    OutlookCalendarAddProcessor,
    OutlookCalendarAddRecurringProcessor,
)
from mail.outlook.consumers import (
    OutlookRulesListPayload,
    OutlookRulesDeletePayload,
    OutlookCategoriesListPayload,
    OutlookCalendarAddPayload,
    OutlookCalendarAddRecurringPayload,
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
        self.assertIn("label1", result)

    def test_empty_rule(self):
        """Test empty rule."""
        rule = {}
        result = _canon_rule(rule)
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
        self.assertIn("recipient@example.com", result)
        self.assertIn("Test Subject", result)
        self.assertIn("forward@example.com", result)
        self.assertIn("folder123", result)

    def test_rule_labels_sorted(self):
        """Test that labels are sorted for consistent comparison."""
        rule1 = {
            "criteria": {"from": "test@example.com"},
            "action": {"addLabelIds": ["b", "a", "c"]},
        }
        rule2 = {
            "criteria": {"from": "test@example.com"},
            "action": {"addLabelIds": ["c", "a", "b"]},
        }
        self.assertEqual(_canon_rule(rule1), _canon_rule(rule2))

    def test_rule_with_none_values(self):
        """Test rule with None values."""
        rule = {
            "criteria": None,
            "action": None,
        }
        result = _canon_rule(rule)
        self.assertIsInstance(result, str)


class TestResultDataclasses(unittest.TestCase):
    """Tests for result dataclasses."""

    def test_rules_list_result_defaults(self):
        """Test OutlookRulesListResult defaults."""
        result = OutlookRulesListResult()
        self.assertEqual(result.rules, [])
        self.assertEqual(result.id_to_name, {})
        self.assertEqual(result.folder_path_rev, {})

    def test_rules_list_result_with_data(self):
        """Test OutlookRulesListResult with data."""
        result = OutlookRulesListResult(
            rules=[{"id": "rule1"}],
            id_to_name={"id1": "Label1"},
            folder_path_rev={"fid1": "Inbox/Test"},
        )
        self.assertEqual(len(result.rules), 1)
        self.assertEqual(result.id_to_name["id1"], "Label1")

    def test_rules_export_result(self):
        """Test OutlookRulesExportResult."""
        result = OutlookRulesExportResult(count=5, out_path="/path/to/file.yaml")
        self.assertEqual(result.count, 5)
        self.assertEqual(result.out_path, "/path/to/file.yaml")

    def test_rules_sync_result(self):
        """Test OutlookRulesSyncResult."""
        result = OutlookRulesSyncResult(created=3, deleted=1)
        self.assertEqual(result.created, 3)
        self.assertEqual(result.deleted, 1)

    def test_rules_plan_result(self):
        """Test OutlookRulesPlanResult."""
        result = OutlookRulesPlanResult(
            would_create=2,
            plan_items=["Would create rule1", "Would create rule2"],
        )
        self.assertEqual(result.would_create, 2)
        self.assertEqual(len(result.plan_items), 2)

    def test_rules_delete_result(self):
        """Test OutlookRulesDeleteResult."""
        result = OutlookRulesDeleteResult(rule_id="rule123")
        self.assertEqual(result.rule_id, "rule123")

    def test_rules_sweep_result(self):
        """Test OutlookRulesSweepResult."""
        result = OutlookRulesSweepResult(moved=10)
        self.assertEqual(result.moved, 10)

    def test_categories_list_result(self):
        """Test OutlookCategoriesListResult."""
        result = OutlookCategoriesListResult(categories=[{"name": "Work"}])
        self.assertEqual(len(result.categories), 1)

    def test_categories_export_result(self):
        """Test OutlookCategoriesExportResult."""
        result = OutlookCategoriesExportResult(count=3, out_path="/path/out.yaml")
        self.assertEqual(result.count, 3)

    def test_categories_sync_result(self):
        """Test OutlookCategoriesSyncResult."""
        result = OutlookCategoriesSyncResult(created=2, skipped=5)
        self.assertEqual(result.created, 2)
        self.assertEqual(result.skipped, 5)

    def test_folders_sync_result(self):
        """Test OutlookFoldersSyncResult."""
        result = OutlookFoldersSyncResult(created=1, skipped=3)
        self.assertEqual(result.created, 1)
        self.assertEqual(result.skipped, 3)

    def test_calendar_add_result(self):
        """Test OutlookCalendarAddResult."""
        result = OutlookCalendarAddResult(event_id="evt123", subject="Meeting")
        self.assertEqual(result.event_id, "evt123")
        self.assertEqual(result.subject, "Meeting")

    def test_calendar_add_recurring_result(self):
        """Test OutlookCalendarAddRecurringResult."""
        result = OutlookCalendarAddRecurringResult(event_id="evt456", subject="Weekly")
        self.assertEqual(result.event_id, "evt456")
        self.assertEqual(result.subject, "Weekly")

    def test_calendar_add_from_config_result(self):
        """Test OutlookCalendarAddFromConfigResult."""
        result = OutlookCalendarAddFromConfigResult(created=5)
        self.assertEqual(result.created, 5)


class TestOutlookRulesListProcessor(unittest.TestCase):
    """Tests for OutlookRulesListProcessor."""

    def test_process_success(self):
        """Test successful rules list."""
        mock_client = MagicMock()
        mock_client.list_filters.return_value = [
            {"id": "rule1", "criteria": {"from": "test@example.com"}},
        ]
        mock_client.get_label_id_map.return_value = {"Label1": "id1"}
        mock_client.get_folder_path_map.return_value = {"Inbox/Test": "fid1"}

        payload = OutlookRulesListPayload(client=mock_client)
        processor = OutlookRulesListProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertIsNotNone(envelope.payload)
        self.assertEqual(len(envelope.payload.rules), 1)
        self.assertEqual(envelope.payload.id_to_name["id1"], "Label1")
        self.assertEqual(envelope.payload.folder_path_rev["fid1"], "Inbox/Test")

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.list_filters.side_effect = Exception("API Error")

        payload = OutlookRulesListPayload(client=mock_client)
        processor = OutlookRulesListProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertIn("API Error", envelope.diagnostics["error"])

    def test_process_with_cache(self):
        """Test processing with cache enabled."""
        mock_client = MagicMock()
        mock_client.list_filters.return_value = []
        mock_client.get_label_id_map.return_value = {}
        mock_client.get_folder_path_map.return_value = {}

        payload = OutlookRulesListPayload(
            client=mock_client, use_cache=True, cache_ttl=300
        )
        processor = OutlookRulesListProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        mock_client.list_filters.assert_called_once_with(use_cache=True, ttl=300)


class TestOutlookRulesDeleteProcessor(unittest.TestCase):
    """Tests for OutlookRulesDeleteProcessor."""

    def test_process_success(self):
        """Test successful rule deletion."""
        mock_client = MagicMock()

        payload = OutlookRulesDeletePayload(client=mock_client, rule_id="rule123")
        processor = OutlookRulesDeleteProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.rule_id, "rule123")
        mock_client.delete_filter.assert_called_once_with("rule123")

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.delete_filter.side_effect = Exception("Delete failed")

        payload = OutlookRulesDeletePayload(client=mock_client, rule_id="rule123")
        processor = OutlookRulesDeleteProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertIsNone(envelope.payload)
        self.assertEqual(envelope.diagnostics["code"], 3)


class TestOutlookCategoriesListProcessor(unittest.TestCase):
    """Tests for OutlookCategoriesListProcessor."""

    def test_process_success(self):
        """Test successful categories list."""
        mock_client = MagicMock()
        mock_client.list_labels.return_value = [
            {"name": "Work", "color": {"name": "blue"}},
            {"name": "Personal", "color": {"name": "green"}},
        ]

        payload = OutlookCategoriesListPayload(client=mock_client)
        processor = OutlookCategoriesListProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(len(envelope.payload.categories), 2)

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.list_labels.side_effect = Exception("API Error")

        payload = OutlookCategoriesListPayload(client=mock_client)
        processor = OutlookCategoriesListProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 1)


class TestOutlookCalendarAddProcessor(unittest.TestCase):
    """Tests for OutlookCalendarAddProcessor."""

    def test_process_success(self):
        """Test successful event creation."""
        mock_client = MagicMock()
        mock_client.create_event.return_value = {
            "id": "evt123",
            "subject": "Team Meeting",
        }

        payload = OutlookCalendarAddPayload(
            client=mock_client,
            subject="Team Meeting",
            start_iso="2024-01-15T10:00:00",
            end_iso="2024-01-15T11:00:00",
            calendar_name="Work",
            tz="America/New_York",
        )
        processor = OutlookCalendarAddProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.event_id, "evt123")
        self.assertEqual(envelope.payload.subject, "Team Meeting")

    def test_process_with_all_options(self):
        """Test event creation with all options."""
        mock_client = MagicMock()
        mock_client.create_event.return_value = {"id": "evt456", "subject": "All Day"}

        payload = OutlookCalendarAddPayload(
            client=mock_client,
            subject="All Day Event",
            start_iso="2024-01-15",
            end_iso="2024-01-16",
            all_day=True,
            body_html="<p>Description</p>",
            location="Conference Room",
            no_reminder=True,
        )
        processor = OutlookCalendarAddProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        mock_client.create_event.assert_called_once()
        call_kwargs = mock_client.create_event.call_args.kwargs
        self.assertTrue(call_kwargs["all_day"])
        self.assertTrue(call_kwargs["no_reminder"])

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.create_event.side_effect = Exception("Calendar error")

        payload = OutlookCalendarAddPayload(
            client=mock_client,
            subject="Meeting",
            start_iso="2024-01-15T10:00:00",
            end_iso="2024-01-15T11:00:00",
        )
        processor = OutlookCalendarAddProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 3)


class TestOutlookCalendarAddRecurringProcessor(unittest.TestCase):
    """Tests for OutlookCalendarAddRecurringProcessor."""

    def test_process_success(self):
        """Test successful recurring event creation."""
        mock_client = MagicMock()
        mock_client.create_recurring_event.return_value = {
            "id": "rec123",
            "subject": "Weekly Standup",
        }

        payload = OutlookCalendarAddRecurringPayload(
            client=mock_client,
            subject="Weekly Standup",
            start_time="09:00",
            end_time="09:30",
            repeat="weekly",
            range_start="2024-01-15",
            byday=["MO", "WE", "FR"],
            interval=1,
        )
        processor = OutlookCalendarAddRecurringProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        self.assertEqual(envelope.payload.event_id, "rec123")
        self.assertEqual(envelope.payload.subject, "Weekly Standup")

    def test_process_with_until(self):
        """Test recurring event with until date."""
        mock_client = MagicMock()
        mock_client.create_recurring_event.return_value = {"id": "rec456", "subject": "Monthly"}

        payload = OutlookCalendarAddRecurringPayload(
            client=mock_client,
            subject="Monthly Review",
            start_time="14:00",
            end_time="15:00",
            repeat="monthly",
            range_start="2024-01-15",
            until="2024-12-31",
        )
        processor = OutlookCalendarAddRecurringProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "success")
        call_kwargs = mock_client.create_recurring_event.call_args.kwargs
        self.assertEqual(call_kwargs["range_until"], "2024-12-31")

    def test_process_error(self):
        """Test error handling."""
        mock_client = MagicMock()
        mock_client.create_recurring_event.side_effect = Exception("Recurring error")

        payload = OutlookCalendarAddRecurringPayload(
            client=mock_client,
            subject="Daily",
            start_time="08:00",
            end_time="08:30",
            repeat="daily",
            range_start="2024-01-15",
        )
        processor = OutlookCalendarAddRecurringProcessor()
        envelope = processor.process(payload)

        self.assertEqual(envelope.status, "error")
        self.assertEqual(envelope.diagnostics["code"], 3)


if __name__ == "__main__":
    unittest.main()
