"""Tests for mail/outlook/producers.py."""

import unittest
from io import StringIO

from core.cli_output import OutputConfig, OutputWriter
from core.pipeline import ResultEnvelope
from tests.fixtures import capture_stdout, test_path

from mail.outlook.processors_rules import (
    OutlookRulesListResult,
    OutlookRulesExportResult,
)
from mail.outlook.processors_rules_write import (
    OutlookRulesSyncResult,
    OutlookRulesDeleteResult,
    OutlookRulesSweepResult,
)
from mail.outlook.processors_rules_plan import OutlookRulesPlanResult
from mail.outlook.processors_calendar import (
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


def _writer(buf: StringIO) -> OutputWriter:
    """Return an OutputWriter whose error_stream is also buf."""
    return OutputWriter(OutputConfig(file=buf))


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to list rules."),
            ("error key", {"error": "API failure"}, "API failure"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookRulesListProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out, msg=f"no Error: prefix in {out!r}")
                self.assertIn(expected, out)
                # ensure no double prefix
                self.assertNotIn("Error: Error:", out)

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookRulesListProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookRulesListResult(rules=[], id_to_name={}, folder_path_rev={}),
        ))
        self.assertNotIn("Failed to list rules", buf.getvalue())

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookRulesListProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to list rules.", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to export rules."),
            ("error key", {"error": "Write failed"}, "Write failed"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookRulesExportProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookRulesExportProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to export rules.", buf.getvalue())


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

        self.assertIn("[dry-run]", buf.getvalue())
        self.assertIn("Deleted: 1", buf.getvalue())

    def test_failure_with_payload_still_prints_the_tally(self):
        """A reconcile failure exits nonzero but must not swallow the counts.

        The processor returns status="error" WITH a payload when ``failed > 0``,
        so the command exits nonzero (a lost rule must not look like success).
        The default producer path prints only the error for a non-ok envelope,
        which would discard the tally -- and the tally is exactly the recovery
        information: what landed before the failure, and what a re-run still has
        to do. The headline must also not claim completion.
        """
        result = ResultEnvelope(
            status="error",
            payload=OutlookRulesSyncResult(created=2, reconciled=1, failed=1),
            diagnostics={
                "error": "1 reconcile operation(s) failed.",
                "code": 1,
                "hint": "re-run once the API error clears",
            },
        )
        producer = OutlookRulesSyncProducer(dry_run=False, reconcile=True)

        with capture_stdout() as buf:
            producer.produce(result)
        out = buf.getvalue()

        self.assertIn("Created: 2", out)
        self.assertIn("Reconciled: 1", out)
        self.assertIn("Failed: 1", out)
        self.assertIn("Hint:", out)
        # Never "Sync complete." on a run that lost a rule.
        self.assertIn("Sync incomplete", out)
        self.assertNotIn("Sync complete", out)

    def test_hard_failure_without_payload_prints_no_tally(self):
        """Contrast: a payload-less failure (auth, etc.) prints only the error.

        Guards the new branch from over-reaching -- it must trigger on a payload
        being present, not on any non-ok envelope, or an auth failure would
        print a meaningless all-zero tally.
        """
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Auth failed", "code": 2, "hint": "Run outlook auth.ensure"},
        )
        producer = OutlookRulesSyncProducer(dry_run=False, reconcile=True)

        with capture_stdout() as buf:
            producer.produce(result)
        out = buf.getvalue()

        self.assertNotIn("Created:", out)
        self.assertNotIn("Sync complete", out)
        self.assertNotIn("Sync incomplete", out)

    def test_reconciled_count_is_reported(self):
        """`--reconcile` must surface what it did, on both output paths.

        The count reached OutlookRulesSyncResult before this was wired, so the
        flag worked while the run said nothing about it. Dry-run is asserted
        alongside live because the dry-run branch builds its own string: it
        previously did so inline and would have silently dropped the new field.
        """
        payload = OutlookRulesSyncResult(created=2, deleted=1, reconciled=3)

        for dry_run, marker in ((False, "Sync complete."), (True, "[dry-run]")):
            with self.subTest(dry_run=dry_run):
                producer = OutlookRulesSyncProducer(
                    dry_run=dry_run, delete_missing=True, reconcile=True
                )
                with capture_stdout() as buf:
                    producer.produce(ResultEnvelope(status="success", payload=payload))
                out = buf.getvalue()
                self.assertIn(marker, out)
                self.assertIn("Created: 2", out)
                self.assertIn("Reconciled: 3", out)
                self.assertIn("Deleted: 1", out)

    def test_reconciled_line_omitted_when_nothing_reconciled(self):
        """Contrast: reconcile on but zero reconciled says nothing extra.

        Keeps the flag from adding noise to every run that changes nothing.
        """
        producer = OutlookRulesSyncProducer(dry_run=False, reconcile=True)
        with capture_stdout() as buf:
            producer.produce(ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(created=2, deleted=0, reconciled=0),
            ))
        out = buf.getvalue()
        self.assertIn("Created: 2", out)
        self.assertNotIn("Reconciled", out)

    def test_failed_count_is_reported_on_both_branches(self):
        """A failed reconcile must be visible, in dry-run as well as live.

        Regression: `Failed: N` was added to the live branch only. The dry-run
        branch built its own parts list and omitted it, so a preview said nothing
        about a rule it would fail to reconcile — and a failed reconcile can mean
        a rule was deleted and not replaced. That is the same defect the
        `Reconciled` field had before f5b940a, in the same method, caused by the
        same duplicated message construction. Both branches now derive from one
        parts list; this test pins both so the duplication cannot return.
        """
        payload = OutlookRulesSyncResult(created=0, deleted=0, reconciled=0, failed=1)

        for dry_run, marker in ((False, "Sync complete."), (True, "[dry-run]")):
            with self.subTest(dry_run=dry_run):
                producer = OutlookRulesSyncProducer(dry_run=dry_run, reconcile=True)
                with capture_stdout() as buf:
                    producer.produce(ResultEnvelope(status="success", payload=payload))
                out = buf.getvalue()
                self.assertIn(marker, out)
                self.assertIn("Failed: 1", out)

    def test_reconciled_and_failed_both_reported_together(self):
        """A partial run reports both halves — some reconciled, some failed."""
        producer = OutlookRulesSyncProducer(
            dry_run=False, delete_missing=True, reconcile=True
        )
        with capture_stdout() as buf:
            producer.produce(ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(
                    created=1, deleted=1, reconciled=2, failed=1
                ),
            ))
        out = buf.getvalue()
        for expected in ("Created: 1", "Reconciled: 2", "Failed: 1", "Deleted: 1"):
            self.assertIn(expected, out)

    def test_failed_line_omitted_when_nothing_failed(self):
        """Contrast: a clean run must not mention failures."""
        producer = OutlookRulesSyncProducer(dry_run=False, reconcile=True)
        with capture_stdout() as buf:
            producer.produce(ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(created=1, deleted=0, reconciled=0, failed=0),
            ))
        self.assertNotIn("Failed", buf.getvalue())

    def test_failed_not_reported_without_reconcile(self):
        """The opt-in guarantee: `failed` is a reconcile-only concept.

        A non-zero count with the flag off must not leak into the default
        output, which has to stay byte-identical to pre-reconcile runs.
        """
        producer = OutlookRulesSyncProducer(dry_run=False, delete_missing=True)
        with capture_stdout() as buf:
            producer.produce(ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(created=1, deleted=1, reconciled=2, failed=1),
            ))
        out = buf.getvalue()
        self.assertIn("Created: 1", out)
        self.assertIn("Deleted: 1", out)
        self.assertNotIn("Failed", out)
        self.assertNotIn("Reconciled", out)

    def test_default_output_unchanged_without_reconcile(self):
        """The opt-in guarantee, asserted at the output layer.

        A reconciled count can only appear when the flag asked for it, so an
        existing `rules.sync` run prints exactly what it always did.
        """
        producer = OutlookRulesSyncProducer(dry_run=False, delete_missing=True)
        with capture_stdout() as buf:
            producer.produce(ResultEnvelope(
                status="success",
                payload=OutlookRulesSyncResult(created=2, deleted=1, reconciled=3),
            ))
        out = buf.getvalue()
        self.assertIn("Created: 2", out)
        self.assertIn("Deleted: 1", out)
        self.assertNotIn("Reconciled", out)

    def test_error_with_hint(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Auth failed", "hint": "Run outlook auth ensure"},
        )
        buf = StringIO()
        producer = OutlookRulesSyncProducer(writer=_writer(buf))
        producer.produce(result)
        out = buf.getvalue()
        self.assertIn("Auth failed", out)
        self.assertIn("outlook auth ensure", out)

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to sync rules."),
            ("error key", {"error": "Auth failed"}, "Auth failed"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookRulesSyncProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookRulesSyncProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to sync rules.", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to plan rules."),
            ("error key", {"error": "Network error"}, "Network error"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookRulesPlanProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookRulesPlanProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to plan rules.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookRulesPlanProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookRulesPlanResult(would_create=0, plan_items=[]),
        ))
        self.assertNotIn("Failed to plan rules", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to delete Outlook rule."),
            ("error key", {"error": "Rule not found"}, "Rule not found"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookRulesDeleteProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookRulesDeleteProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to delete Outlook rule.", buf.getvalue())


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

        self.assertIn("[dry-run]", buf.getvalue())
        self.assertIn("move=10", buf.getvalue())

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to sweep."),
            ("error key", {"error": "Sweep failed"}, "Sweep failed"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookRulesSweepProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookRulesSweepProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to sweep.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookRulesSweepProducer(dry_run=False, writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookRulesSweepResult(moved=0),
        ))
        self.assertNotIn("Failed to sweep", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to list categories."),
            ("error key", {"error": "API down"}, "API down"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookCategoriesListProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookCategoriesListProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to list categories.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookCategoriesListProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookCategoriesListResult(categories=[]),
        ))
        self.assertNotIn("Failed to list categories", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to export categories."),
            ("error key", {"error": "Disk full"}, "Disk full"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookCategoriesExportProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookCategoriesExportProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to export categories.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookCategoriesExportProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookCategoriesExportResult(count=0, out_path="/tmp/out.yaml"),  # nosec B108 - test fixture path, never written
        ))
        self.assertNotIn("Failed to export categories", buf.getvalue())


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

    def test_dry_run(self):
        buf = StringIO()
        producer = OutlookCategoriesSyncProducer(dry_run=True, writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookCategoriesSyncResult(created=1, skipped=0),
        ))
        self.assertIn("[dry-run]", buf.getvalue())
        self.assertIn("Created: 1", buf.getvalue())

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to sync categories."),
            ("error key", {"error": "Token expired"}, "Token expired"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookCategoriesSyncProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookCategoriesSyncProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to sync categories.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookCategoriesSyncProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookCategoriesSyncResult(created=0, skipped=0),
        ))
        self.assertNotIn("Failed to sync categories", buf.getvalue())


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

    def test_dry_run(self):
        buf = StringIO()
        producer = OutlookFoldersSyncProducer(dry_run=True, writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookFoldersSyncResult(created=3, skipped=2),
        ))
        self.assertIn("[dry-run]", buf.getvalue())
        self.assertIn("Created: 3", buf.getvalue())

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to sync folders."),
            ("error key", {"error": "Folder not found"}, "Folder not found"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookFoldersSyncProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookFoldersSyncProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to sync folders.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookFoldersSyncProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookFoldersSyncResult(created=0, skipped=0),
        ))
        self.assertNotIn("Failed to sync folders", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to create event."),
            ("error key", {"error": "Calendar not found"}, "Calendar not found"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookCalendarAddProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookCalendarAddProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to create event.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookCalendarAddProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddResult(event_id="e1", subject="S"),
        ))
        self.assertNotIn("Failed to create event", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to create recurring event."),
            ("error key", {"error": "Recurrence invalid"}, "Recurrence invalid"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookCalendarAddRecurringProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookCalendarAddRecurringProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to create recurring event.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookCalendarAddRecurringProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddRecurringResult(event_id="e1", subject="S"),
        ))
        self.assertNotIn("Failed to create recurring event", buf.getvalue())


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

    def test_error_cases(self):
        cases = [
            ("no diagnostics", {}, "Failed to add events from config."),
            ("error key", {"error": "Config invalid"}, "Config invalid"),
        ]
        for label, diag, expected in cases:
            with self.subTest(label):
                buf = StringIO()
                producer = OutlookCalendarAddFromConfigProducer(writer=_writer(buf))
                producer.produce(ResultEnvelope(status="error", payload=None, diagnostics=diag))
                out = buf.getvalue()
                self.assertIn("Error:", out)
                self.assertIn(expected, out)
                self.assertNotIn("Error: Error:", out)

    def test_payload_none_uses_fallback(self):
        buf = StringIO()
        producer = OutlookCalendarAddFromConfigProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(status="success", payload=None))
        self.assertIn("Failed to add events from config.", buf.getvalue())

    def test_success_no_failure_text(self):
        buf = StringIO()
        producer = OutlookCalendarAddFromConfigProducer(writer=_writer(buf))
        producer.produce(ResultEnvelope(
            status="success",
            payload=OutlookCalendarAddFromConfigResult(created=0),
        ))
        self.assertNotIn("Failed to add events from config", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
