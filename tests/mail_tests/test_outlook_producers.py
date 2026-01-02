"""Tests for mail/outlook/producers.py."""

import unittest

from core.pipeline import ResultEnvelope
from tests.fixtures import capture_stdout, test_path

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

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("rule-1", buf.getvalue())
        self.assertIn("sender@example.com", buf.getvalue())
        self.assertIn("Work", buf.getvalue())

    def test_success_empty_rules(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesListResult(rules=[], id_to_name={}, folder_path_rev={}),
        )
        producer = OutlookRulesListProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("No Inbox rules found", buf.getvalue())

    def test_error_result(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "API failure"},
        )
        producer = OutlookRulesListProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Error", buf.getvalue())
        self.assertIn("API failure", buf.getvalue())

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

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("forward=archive@example.com", buf.getvalue())
        self.assertIn("moveToFolder=Archive/Newsletters", buf.getvalue())


class TestOutlookRulesExportProducer(unittest.TestCase):
    """Tests for OutlookRulesExportProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesExportResult(count=5, out_path=test_path("rules.yaml")),  # noqa: S108 - test fixture path
        )
        producer = OutlookRulesExportProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Exported 5 rules", buf.getvalue())
        self.assertIn(test_path("rules.yaml"), buf.getvalue())  # noqa: S108 - test fixture path

    def test_error(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Write failed"},
        )
        producer = OutlookRulesExportProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Error", buf.getvalue())


class TestOutlookRulesSyncProducer(unittest.TestCase):
    """Tests for OutlookRulesSyncProducer."""

    def test_success_no_dry_run(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSyncResult(created=3, deleted=0),
        )
        producer = OutlookRulesSyncProducer(dry_run=False)

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Sync complete", buf.getvalue())
        self.assertIn("Created: 3", buf.getvalue())

    def test_dry_run(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSyncResult(created=2, deleted=1),
        )
        producer = OutlookRulesSyncProducer(dry_run=True, delete_missing=True)

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Would sync", buf.getvalue())
        self.assertIn("Deleted: 1", buf.getvalue())

    def test_error_with_hint(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Auth failed", "hint": "Run outlook auth ensure"},
        )
        producer = OutlookRulesSyncProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Auth failed", buf.getvalue())
        self.assertIn("outlook auth ensure", buf.getvalue())


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

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Would create: rule1", buf.getvalue())
        self.assertIn("create=2", buf.getvalue())


class TestOutlookRulesDeleteProducer(unittest.TestCase):
    """Tests for OutlookRulesDeleteProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesDeleteResult(rule_id="rule-xyz"),
        )
        producer = OutlookRulesDeleteProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Deleted Outlook rule", buf.getvalue())
        self.assertIn("rule-xyz", buf.getvalue())

    def test_error(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Rule not found"},
        )
        producer = OutlookRulesDeleteProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Error deleting", buf.getvalue())


class TestOutlookRulesSweepProducer(unittest.TestCase):
    """Tests for OutlookRulesSweepProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSweepResult(moved=15),
        )
        producer = OutlookRulesSweepProducer(dry_run=False)

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Sweep summary: moved=15", buf.getvalue())

    def test_dry_run(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookRulesSweepResult(moved=10),
        )
        producer = OutlookRulesSweepProducer(dry_run=True)

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Would move=10", buf.getvalue())


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

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("cat-1", buf.getvalue())
        self.assertIn("Work", buf.getvalue())
        self.assertIn("Personal", buf.getvalue())

    def test_empty_categories(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCategoriesListResult(categories=[]),
        )
        producer = OutlookCategoriesListProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("No categories", buf.getvalue())


class TestOutlookCategoriesExportProducer(unittest.TestCase):
    """Tests for OutlookCategoriesExportProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCategoriesExportResult(count=3, out_path=test_path("cats.yaml")),  # noqa: S108 - test fixture path
        )
        producer = OutlookCategoriesExportProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Exported 3 categories", buf.getvalue())


class TestOutlookCategoriesSyncProducer(unittest.TestCase):
    """Tests for OutlookCategoriesSyncProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCategoriesSyncResult(created=2, skipped=5),
        )
        producer = OutlookCategoriesSyncProducer(dry_run=False)

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("sync complete", buf.getvalue())
        self.assertIn("Created: 2", buf.getvalue())
        self.assertIn("Skipped: 5", buf.getvalue())


class TestOutlookFoldersSyncProducer(unittest.TestCase):
    """Tests for OutlookFoldersSyncProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookFoldersSyncResult(created=1, skipped=10),
        )
        producer = OutlookFoldersSyncProducer(dry_run=False)

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("sync complete", buf.getvalue())
        self.assertIn("Created: 1", buf.getvalue())


class TestOutlookCalendarAddProducer(unittest.TestCase):
    """Tests for OutlookCalendarAddProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddResult(event_id="evt-123", subject="Meeting"),
        )
        producer = OutlookCalendarAddProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Created event", buf.getvalue())
        self.assertIn("evt-123", buf.getvalue())
        self.assertIn("Meeting", buf.getvalue())

    def test_error(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Calendar not found"},
        )
        producer = OutlookCalendarAddProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Failed to create event", buf.getvalue())


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

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Created recurring series", buf.getvalue())
        self.assertIn("series-abc", buf.getvalue())


class TestOutlookCalendarAddFromConfigProducer(unittest.TestCase):
    """Tests for OutlookCalendarAddFromConfigProducer."""

    def test_success(self):
        result = ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddFromConfigResult(created=5),
        )
        producer = OutlookCalendarAddFromConfigProducer()

        with capture_stdout() as buf:
            producer.produce(result)

        self.assertIn("Created 5 events", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
