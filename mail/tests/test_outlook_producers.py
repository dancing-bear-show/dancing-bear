"""Tests for mail/outlook/producers.py."""
import io
import sys
import unittest
from unittest.mock import Mock

from core.pipeline import ResultEnvelope

from mail.outlook.processors import (
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
)
from mail.outlook.producers import (
    OutlookRulesListProducer,
    OutlookRulesExportProducer,
    OutlookRulesSyncProducer,
    OutlookRulesPlanProducer,
    OutlookRulesDeleteProducer,
    OutlookRulesSweepProducer,
    OutlookCategoriesListProducer,
    OutlookCategoriesExportProducer,
    OutlookCategoriesSyncProducer,
    OutlookFoldersSyncProducer,
    OutlookCalendarAddProducer,
    OutlookCalendarAddRecurringProducer,
    OutlookCalendarAddFromConfigProducer,
)


class CaptureOutput:
    """Context manager to capture stdout."""

    def __enter__(self):
        self.captured = io.StringIO()
        self.old_stdout = sys.stdout
        sys.stdout = self.captured
        return self

    def __exit__(self, *args):
        sys.stdout = self.old_stdout

    @property
    def output(self):
        return self.captured.getvalue()


class TestOutlookRulesListProducer(unittest.TestCase):
    """Tests for OutlookRulesListProducer."""

    def test_success_with_rules(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesListResult(
                rules=[
                    {
                        "id": "rule-1",
                        "criteria": {"from": "sender@example.com"},
                        "action": {"addLabelIds": ["cat-1"]},
                    }
                ],
                id_to_name={"cat-1": "Work"},
                folder_path_rev={},
            ),
        )
        producer = OutlookRulesListProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("rule-1", cap.output)
        self.assertIn("sender@example.com", cap.output)
        self.assertIn("Work", cap.output)

    def test_success_empty_rules(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesListResult(rules=[], id_to_name={}, folder_path_rev={}),
        )
        producer = OutlookRulesListProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("No Inbox rules found", cap.output)

    def test_error_result(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "API failure"},
        )
        producer = OutlookRulesListProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Error", cap.output)
        self.assertIn("API failure", cap.output)

    def test_rule_with_forward_and_move(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesListResult(
                rules=[
                    {
                        "id": "rule-2",
                        "criteria": {"subject": "Newsletter"},
                        "action": {
                            "forward": "archive@example.com",
                            "moveToFolderId": "folder-123",
                        },
                    }
                ],
                id_to_name={},
                folder_path_rev={"folder-123": "Archive/Newsletters"},
            ),
        )
        producer = OutlookRulesListProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("forward=archive@example.com", cap.output)
        self.assertIn("moveToFolder=Archive/Newsletters", cap.output)


class TestOutlookRulesExportProducer(unittest.TestCase):
    """Tests for OutlookRulesExportProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesExportResult(count=5, out_path="/tmp/rules.yaml"),
        )
        producer = OutlookRulesExportProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Exported 5 rules", cap.output)
        self.assertIn("/tmp/rules.yaml", cap.output)

    def test_error(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Write failed"},
        )
        producer = OutlookRulesExportProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Error", cap.output)


class TestOutlookRulesSyncProducer(unittest.TestCase):
    """Tests for OutlookRulesSyncProducer."""

    def test_success_no_dry_run(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSyncResult(created=3, deleted=0),
        )
        producer = OutlookRulesSyncProducer(dry_run=False)

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Sync complete", cap.output)
        self.assertIn("Created: 3", cap.output)

    def test_dry_run(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSyncResult(created=2, deleted=1),
        )
        producer = OutlookRulesSyncProducer(dry_run=True, delete_missing=True)

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Would sync", cap.output)
        self.assertIn("Deleted: 1", cap.output)

    def test_error_with_hint(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Auth failed", "hint": "Run outlook auth ensure"},
        )
        producer = OutlookRulesSyncProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Auth failed", cap.output)
        self.assertIn("outlook auth ensure", cap.output)


class TestOutlookRulesPlanProducer(unittest.TestCase):
    """Tests for OutlookRulesPlanProducer."""

    def test_success_with_items(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesPlanResult(
                would_create=2,
                plan_items=["Would create: rule1", "Would create: rule2"],
            ),
        )
        producer = OutlookRulesPlanProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Would create: rule1", cap.output)
        self.assertIn("create=2", cap.output)


class TestOutlookRulesDeleteProducer(unittest.TestCase):
    """Tests for OutlookRulesDeleteProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesDeleteResult(rule_id="rule-xyz"),
        )
        producer = OutlookRulesDeleteProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Deleted Outlook rule", cap.output)
        self.assertIn("rule-xyz", cap.output)

    def test_error(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Rule not found"},
        )
        producer = OutlookRulesDeleteProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Error deleting", cap.output)


class TestOutlookRulesSweepProducer(unittest.TestCase):
    """Tests for OutlookRulesSweepProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSweepResult(moved=15),
        )
        producer = OutlookRulesSweepProducer(dry_run=False)

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Sweep summary: moved=15", cap.output)

    def test_dry_run(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSweepResult(moved=10),
        )
        producer = OutlookRulesSweepProducer(dry_run=True)

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Would move=10", cap.output)


class TestOutlookCategoriesListProducer(unittest.TestCase):
    """Tests for OutlookCategoriesListProducer."""

    def test_success_with_categories(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCategoriesListResult(
                categories=[
                    {"id": "cat-1", "name": "Work"},
                    {"id": "cat-2", "name": "Personal"},
                ]
            ),
        )
        producer = OutlookCategoriesListProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("cat-1", cap.output)
        self.assertIn("Work", cap.output)
        self.assertIn("Personal", cap.output)

    def test_empty_categories(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCategoriesListResult(categories=[]),
        )
        producer = OutlookCategoriesListProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("No categories", cap.output)


class TestOutlookCategoriesExportProducer(unittest.TestCase):
    """Tests for OutlookCategoriesExportProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCategoriesExportResult(count=3, out_path="/tmp/cats.yaml"),
        )
        producer = OutlookCategoriesExportProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Exported 3 categories", cap.output)


class TestOutlookCategoriesSyncProducer(unittest.TestCase):
    """Tests for OutlookCategoriesSyncProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCategoriesSyncResult(created=2, skipped=5),
        )
        producer = OutlookCategoriesSyncProducer(dry_run=False)

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("sync complete", cap.output)
        self.assertIn("Created: 2", cap.output)
        self.assertIn("Skipped: 5", cap.output)


class TestOutlookFoldersSyncProducer(unittest.TestCase):
    """Tests for OutlookFoldersSyncProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookFoldersSyncResult(created=1, skipped=10),
        )
        producer = OutlookFoldersSyncProducer(dry_run=False)

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("sync complete", cap.output)
        self.assertIn("Created: 1", cap.output)


class TestOutlookCalendarAddProducer(unittest.TestCase):
    """Tests for OutlookCalendarAddProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddResult(event_id="evt-123", subject="Meeting"),
        )
        producer = OutlookCalendarAddProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Created event", cap.output)
        self.assertIn("evt-123", cap.output)
        self.assertIn("Meeting", cap.output)

    def test_error(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Calendar not found"},
        )
        producer = OutlookCalendarAddProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Failed to create event", cap.output)


class TestOutlookCalendarAddRecurringProducer(unittest.TestCase):
    """Tests for OutlookCalendarAddRecurringProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddRecurringResult(
                event_id="series-abc", subject="Standup"
            ),
        )
        producer = OutlookCalendarAddRecurringProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Created recurring series", cap.output)
        self.assertIn("series-abc", cap.output)


class TestOutlookCalendarAddFromConfigProducer(unittest.TestCase):
    """Tests for OutlookCalendarAddFromConfigProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddFromConfigResult(created=5),
        )
        producer = OutlookCalendarAddFromConfigProducer()

        with CaptureOutput() as cap:
            producer.produce(result)

        self.assertIn("Created 5 events", cap.output)


if __name__ == "__main__":
    unittest.main(verbosity=2)
