"""Tests for mail/outlook/processors.py."""

from tests.fixtures import test_path
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from mail.outlook.processors import (
    # Result dataclasses
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
    # Helper function
    _canon_rule,
    # Processors
    OutlookRulesListProcessor,
    OutlookRulesDeleteProcessor,
    OutlookCategoriesListProcessor,
    OutlookCalendarAddProcessor,
)
from mail.outlook.consumers import (
    OutlookRulesListPayload,
    OutlookRulesDeletePayload,
    OutlookCategoriesListPayload,
    OutlookCalendarAddPayload,
)


# =============================================================================
# Result Dataclass Tests
# =============================================================================

class TestOutlookRulesListResult(unittest.TestCase):
    """Tests for OutlookRulesListResult dataclass."""

    def test_default_values(self):
        result = OutlookRulesListResult()
        self.assertEqual(result.rules, [])
        self.assertEqual(result.id_to_name, {})
        self.assertEqual(result.folder_path_rev, {})

    def test_custom_values(self):
        result = OutlookRulesListResult(
            rules=[{"id": "1", "name": "Rule1"}],
            id_to_name={"1": "Rule1"},
            folder_path_rev={"folder-id": "Inbox/Work"},
        )
        self.assertEqual(len(result.rules), 1)
        self.assertEqual(result.id_to_name["1"], "Rule1")
        self.assertEqual(result.folder_path_rev["folder-id"], "Inbox/Work")


class TestOutlookRulesExportResult(unittest.TestCase):
    """Tests for OutlookRulesExportResult dataclass."""

    def test_default_values(self):
        result = OutlookRulesExportResult()
        self.assertEqual(result.count, 0)
        self.assertEqual(result.out_path, "")

    def test_custom_values(self):
        result = OutlookRulesExportResult(count=5, out_path=test_path("rules.yaml"))  # noqa: S108
        self.assertEqual(result.count, 5)
        self.assertEqual(result.out_path, test_path("rules.yaml"))  # noqa: S108


class TestOutlookRulesSyncResult(unittest.TestCase):
    """Tests for OutlookRulesSyncResult dataclass."""

    def test_default_values(self):
        result = OutlookRulesSyncResult()
        self.assertEqual(result.created, 0)
        self.assertEqual(result.deleted, 0)

    def test_custom_values(self):
        result = OutlookRulesSyncResult(created=3, deleted=2)
        self.assertEqual(result.created, 3)
        self.assertEqual(result.deleted, 2)


class TestOutlookRulesPlanResult(unittest.TestCase):
    """Tests for OutlookRulesPlanResult dataclass."""

    def test_default_values(self):
        result = OutlookRulesPlanResult()
        self.assertEqual(result.would_create, 0)
        self.assertEqual(result.plan_items, [])

    def test_custom_values(self):
        result = OutlookRulesPlanResult(
            would_create=2,
            plan_items=["Would create: rule1", "Would create: rule2"],
        )
        self.assertEqual(result.would_create, 2)
        self.assertEqual(len(result.plan_items), 2)


class TestOutlookRulesDeleteResult(unittest.TestCase):
    """Tests for OutlookRulesDeleteResult dataclass."""

    def test_default_values(self):
        result = OutlookRulesDeleteResult()
        self.assertEqual(result.rule_id, "")

    def test_custom_values(self):
        result = OutlookRulesDeleteResult(rule_id="abc123")
        self.assertEqual(result.rule_id, "abc123")


class TestOutlookRulesSweepResult(unittest.TestCase):
    """Tests for OutlookRulesSweepResult dataclass."""

    def test_default_values(self):
        result = OutlookRulesSweepResult()
        self.assertEqual(result.moved, 0)

    def test_custom_values(self):
        result = OutlookRulesSweepResult(moved=15)
        self.assertEqual(result.moved, 15)


class TestOutlookCategoriesListResult(unittest.TestCase):
    """Tests for OutlookCategoriesListResult dataclass."""

    def test_default_values(self):
        result = OutlookCategoriesListResult()
        self.assertEqual(result.categories, [])

    def test_custom_values(self):
        result = OutlookCategoriesListResult(
            categories=[{"name": "Work", "color": "blue"}]
        )
        self.assertEqual(len(result.categories), 1)


class TestOutlookCategoriesExportResult(unittest.TestCase):
    """Tests for OutlookCategoriesExportResult dataclass."""

    def test_default_values(self):
        result = OutlookCategoriesExportResult()
        self.assertEqual(result.count, 0)
        self.assertEqual(result.out_path, "")


class TestOutlookCategoriesSyncResult(unittest.TestCase):
    """Tests for OutlookCategoriesSyncResult dataclass."""

    def test_default_values(self):
        result = OutlookCategoriesSyncResult()
        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 0)


class TestOutlookFoldersSyncResult(unittest.TestCase):
    """Tests for OutlookFoldersSyncResult dataclass."""

    def test_default_values(self):
        result = OutlookFoldersSyncResult()
        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 0)


class TestOutlookCalendarAddResult(unittest.TestCase):
    """Tests for OutlookCalendarAddResult dataclass."""

    def test_default_values(self):
        result = OutlookCalendarAddResult()
        self.assertEqual(result.event_id, "")
        self.assertEqual(result.subject, "")

    def test_custom_values(self):
        result = OutlookCalendarAddResult(event_id="evt123", subject="Meeting")
        self.assertEqual(result.event_id, "evt123")
        self.assertEqual(result.subject, "Meeting")


class TestOutlookCalendarAddRecurringResult(unittest.TestCase):
    """Tests for OutlookCalendarAddRecurringResult dataclass."""

    def test_default_values(self):
        result = OutlookCalendarAddRecurringResult()
        self.assertEqual(result.event_id, "")
        self.assertEqual(result.subject, "")


class TestOutlookCalendarAddFromConfigResult(unittest.TestCase):
    """Tests for OutlookCalendarAddFromConfigResult dataclass."""

    def test_default_values(self):
        result = OutlookCalendarAddFromConfigResult()
        self.assertEqual(result.created, 0)


# =============================================================================
# Helper Function Tests
# =============================================================================

class TestCanonRule(unittest.TestCase):
    """Tests for _canon_rule helper function."""

    def test_empty_rule(self):
        rule = {}
        key = _canon_rule(rule)
        self.assertIn("from", key)
        self.assertIn("None", key)

    def test_from_criteria(self):
        rule = {"criteria": {"from": "test@example.com"}}
        key = _canon_rule(rule)
        self.assertIn("test@example.com", key)

    def test_to_criteria(self):
        rule = {"criteria": {"to": "team@example.com"}}
        key = _canon_rule(rule)
        self.assertIn("team@example.com", key)

    def test_subject_criteria(self):
        rule = {"criteria": {"subject": "[URGENT]"}}
        key = _canon_rule(rule)
        self.assertIn("[URGENT]", key)

    def test_add_label_action(self):
        rule = {"action": {"addLabelIds": ["label1", "label2"]}}
        key = _canon_rule(rule)
        self.assertIn("label1", key)
        self.assertIn("label2", key)

    def test_forward_action(self):
        rule = {"action": {"forward": "forward@example.com"}}
        key = _canon_rule(rule)
        self.assertIn("forward@example.com", key)

    def test_move_action(self):
        rule = {"action": {"moveToFolderId": "folder-123"}}
        key = _canon_rule(rule)
        self.assertIn("folder-123", key)

    def test_full_rule(self):
        rule = {
            "criteria": {"from": "sender@example.com", "subject": "Newsletter"},
            "action": {"addLabelIds": ["news"], "moveToFolderId": "newsletters"},
        }
        key = _canon_rule(rule)
        self.assertIn("sender@example.com", key)
        self.assertIn("Newsletter", key)
        self.assertIn("news", key)
        self.assertIn("newsletters", key)

    def test_sorted_labels(self):
        rule1 = {"action": {"addLabelIds": ["b", "a", "c"]}}
        rule2 = {"action": {"addLabelIds": ["a", "b", "c"]}}
        # Keys should be identical due to sorting
        self.assertEqual(_canon_rule(rule1), _canon_rule(rule2))


# =============================================================================
# Processor Tests
# =============================================================================

class TestOutlookRulesListProcessor(unittest.TestCase):
    """Tests for OutlookRulesListProcessor."""

    def test_success(self):
        mock_client = Mock()
        mock_client.list_filters.return_value = [
            {"id": "r1", "criteria": {"from": "test@example.com"}}
        ]
        mock_client.get_label_id_map.return_value = {"Work": "cat-1"}
        mock_client.get_folder_path_map.return_value = {"Inbox/Work": "folder-1"}

        payload = OutlookRulesListPayload(
            client=mock_client, use_cache=False, cache_ttl=600
        )
        processor = OutlookRulesListProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertIsNotNone(result.payload)
        self.assertEqual(len(result.payload.rules), 1)
        self.assertEqual(result.payload.id_to_name["cat-1"], "Work")

    def test_error_handling(self):
        mock_client = Mock()
        mock_client.list_filters.side_effect = Exception("API Error")

        payload = OutlookRulesListPayload(client=mock_client)
        processor = OutlookRulesListProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "error")
        self.assertIsNone(result.payload)
        self.assertIn("API Error", result.diagnostics["error"])


class TestOutlookRulesDeleteProcessor(unittest.TestCase):
    """Tests for OutlookRulesDeleteProcessor."""

    def test_success(self):
        mock_client = Mock()
        mock_client.delete_filter.return_value = None

        payload = OutlookRulesDeletePayload(client=mock_client, rule_id="rule-123")
        processor = OutlookRulesDeleteProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.payload.rule_id, "rule-123")
        mock_client.delete_filter.assert_called_once_with("rule-123")

    def test_error_handling(self):
        mock_client = Mock()
        mock_client.delete_filter.side_effect = Exception("Not found")

        payload = OutlookRulesDeletePayload(client=mock_client, rule_id="bad-id")
        processor = OutlookRulesDeleteProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "error")
        self.assertIn("Not found", result.diagnostics["error"])


class TestOutlookCategoriesListProcessor(unittest.TestCase):
    """Tests for OutlookCategoriesListProcessor."""

    def test_success(self):
        mock_client = Mock()
        mock_client.list_labels.return_value = [
            {"name": "Work", "color": {"name": "blue"}},
            {"name": "Personal", "color": {"name": "green"}},
        ]

        payload = OutlookCategoriesListPayload(client=mock_client)
        processor = OutlookCategoriesListProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertEqual(len(result.payload.categories), 2)

    def test_uses_cache_params(self):
        mock_client = Mock()
        mock_client.list_labels.return_value = []

        payload = OutlookCategoriesListPayload(
            client=mock_client, use_cache=True, cache_ttl=300
        )
        processor = OutlookCategoriesListProcessor()
        processor.process(payload)

        mock_client.list_labels.assert_called_once_with(use_cache=True, ttl=300)


class TestOutlookCalendarAddProcessor(unittest.TestCase):
    """Tests for OutlookCalendarAddProcessor."""

    def test_success(self):
        mock_client = Mock()
        mock_client.create_event.return_value = {
            "id": "evt-123",
            "subject": "Team Meeting",
        }

        payload = OutlookCalendarAddPayload(
            client=mock_client,
            subject="Team Meeting",
            start_iso="2024-01-15T10:00:00",
            end_iso="2024-01-15T11:00:00",
            calendar_name="Work",
            tz="America/New_York",
            location="Room 101",
        )
        processor = OutlookCalendarAddProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "success")
        self.assertEqual(result.payload.event_id, "evt-123")
        self.assertEqual(result.payload.subject, "Team Meeting")

    def test_passes_all_params(self):
        mock_client = Mock()
        mock_client.create_event.return_value = {"id": "x", "subject": "Test"}

        payload = OutlookCalendarAddPayload(
            client=mock_client,
            subject="All Day Event",
            start_iso="2024-01-15",
            end_iso="2024-01-16",
            all_day=True,
            body_html="<p>Notes</p>",
            no_reminder=True,
        )
        processor = OutlookCalendarAddProcessor()
        processor.process(payload)

        mock_client.create_event.assert_called_once()
        call_kwargs = mock_client.create_event.call_args[1]
        self.assertEqual(call_kwargs["subject"], "All Day Event")
        self.assertTrue(call_kwargs["all_day"])
        self.assertTrue(call_kwargs["no_reminder"])

    def test_error_handling(self):
        mock_client = Mock()
        mock_client.create_event.side_effect = Exception("Calendar not found")

        payload = OutlookCalendarAddPayload(
            client=mock_client,
            subject="Test",
            start_iso="2024-01-15T10:00:00",
            end_iso="2024-01-15T11:00:00",
        )
        processor = OutlookCalendarAddProcessor()
        result = processor.process(payload)

        self.assertEqual(result.status, "error")
        self.assertIn("Calendar not found", result.diagnostics["error"])


# =============================================================================
# Integration-style Tests (with temp files)
# =============================================================================

class TestOutlookCategoriesExportProcessor(unittest.TestCase):
    """Tests for OutlookCategoriesExportProcessor with temp files."""

    def test_export_creates_file(self):
        from mail.outlook.processors import OutlookCategoriesExportProcessor
        from mail.outlook.consumers import OutlookCategoriesExportPayload

        mock_client = Mock()
        mock_client.list_labels.return_value = [
            {"name": "Work", "color": {"name": "blue"}},
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "categories.yaml"
            payload = OutlookCategoriesExportPayload(
                client=mock_client, out_path=str(out_path)
            )
            processor = OutlookCategoriesExportProcessor()
            result = processor.process(payload)

            self.assertEqual(result.status, "success")
            self.assertEqual(result.payload.count, 1)
            self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
