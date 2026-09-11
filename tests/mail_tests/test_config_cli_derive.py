"""Tests for config_cli pipeline — derive labels, derive filters, optimize filters, audit filters."""

import io
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase

from tests.fixtures import test_path
from core.pipeline import ResultEnvelope

from mail.config_cli.pipeline_derive import (
    # Derive labels
    DeriveLabelsRequest,
    DeriveLabelsRequestConsumer,
    DeriveLabelsProcessor,
    DeriveLabelsProducer,
    DeriveLabelsResult,
    # Derive filters
    DeriveFiltersRequest,
    DeriveFiltersRequestConsumer,
    DeriveFiltersProcessor,
    DeriveFiltersProducer,
    DeriveFiltersResult,
    # Optimize filters
    OptimizeFiltersRequest,
    OptimizeFiltersRequestConsumer,
    OptimizeFiltersProcessor,
    OptimizeFiltersProducer,
    OptimizeFiltersResult,
    MergedGroup,
)
from mail.config_cli.pipeline_audit import (
    # Audit filters
    AuditFiltersRequest,
    AuditFiltersRequestConsumer,
    AuditFiltersProcessor,
    AuditFiltersProducer,
    AuditFiltersResult,
)


class DeriveLabelsTests(TestCase):
    """Tests for derive labels pipeline."""

    def test_derive_labels_consumer_returns_request(self):
        """DeriveLabelsRequestConsumer returns the request."""
        request = DeriveLabelsRequest(in_path="in.yaml", out_gmail="g.yaml", out_outlook="o.yaml")
        consumer = DeriveLabelsRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_derive_labels_processor_creates_files(self):
        """DeriveLabelsProcessor creates gmail and outlook label files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "labels.yaml"
            in_path.write_text("labels:\n  - name: Test\n    color: red\n")

            out_gmail = Path(tmpdir) / "gmail.yaml"
            out_outlook = Path(tmpdir) / "outlook.yaml"

            request = DeriveLabelsRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveLabelsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, result.payload.labels_count)
            self.assertTrue(out_gmail.exists())
            self.assertTrue(out_outlook.exists())

    def test_derive_labels_processor_empty_labels(self):
        """DeriveLabelsProcessor handles empty labels list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "empty.yaml"
            in_path.write_text("labels: []\n")

            out_gmail = Path(tmpdir) / "g.yaml"
            out_outlook = Path(tmpdir) / "o.yaml"

            request = DeriveLabelsRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveLabelsProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.labels_count)

    def test_derive_labels_producer_output(self):
        """DeriveLabelsProducer prints paths."""
        result = ResultEnvelope(
            status="success",
            payload=DeriveLabelsResult(
                gmail_path=test_path("gmail.yaml"),  # noqa: S108 - test fixture path
                outlook_path=test_path("outlook.yaml"),  # noqa: S108 - test fixture path
                labels_count=5,
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            DeriveLabelsProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("gmail:", output)
        self.assertIn("outlook:", output)


class DeriveFiltersTests(TestCase):
    """Tests for derive filters pipeline."""

    def test_derive_filters_consumer_returns_request(self):
        """DeriveFiltersRequestConsumer returns the request."""
        request = DeriveFiltersRequest(in_path="in.yaml", out_gmail="g.yaml", out_outlook="o.yaml")
        consumer = DeriveFiltersRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_derive_filters_processor_creates_files(self):
        """DeriveFiltersProcessor creates gmail and outlook filter files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "filters.yaml"
            in_path.write_text("filters:\n  - match:\n      from: test@example.com\n    action:\n      add: [Label]\n")

            out_gmail = Path(tmpdir) / "gmail.yaml"
            out_outlook = Path(tmpdir) / "outlook.yaml"

            request = DeriveFiltersRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(1, result.payload.filters_count)
            self.assertTrue(out_gmail.exists())
            self.assertTrue(out_outlook.exists())

    def _derive(self, tmpdir, yaml_text):
        """Run the derive processor over yaml_text; return (gmail_doc, outlook_doc)."""
        import yaml

        in_path = Path(tmpdir) / "filters.yaml"
        in_path.write_text(yaml_text)
        out_gmail = Path(tmpdir) / "gmail.yaml"
        out_outlook = Path(tmpdir) / "outlook.yaml"

        # Mirrors the CLI default (--outlook-move-to-folders is on by default),
        # which the dataclass default does not carry.
        result = DeriveFiltersProcessor().process(
            DeriveFiltersRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
                outlook_move_to_folders=True,
            )
        )
        self.assertTrue(result.ok())
        return (
            yaml.safe_load(out_gmail.read_text()),
            yaml.safe_load(out_outlook.read_text()),
        )

    def test_derive_filters_outlook_derives_move_to_folder_by_default(self):
        """Without keepInInbox, Outlook gets a moveToFolder from the first add label."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, outlook = self._derive(
                tmpdir,
                "filters:\n"
                "  - match:\n"
                "      from: nintendo.net\n"
                "    action:\n"
                "      add: [Tech/Nintendo]\n",
            )
            action = outlook["filters"][0]["action"]
            self.assertEqual("Tech/Nintendo", action["moveToFolder"])

    def test_derive_filters_keep_in_inbox_suppresses_move_to_folder(self):
        """keepInInbox blocks the derived Outlook moveToFolder so mail stays in the inbox.

        The user-facing ``keepInInbox`` input marker is converted to the internal
        ``noMoveToFolder: true`` marker in the derived Outlook config.  This marker
        is consumed by the plan and sweep stages to suppress folder derivation even
        when ``move_to_folders`` is True; it is never forwarded to the Graph API
        payload (the action builders create a fresh dict and only copy known keys).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            _, outlook = self._derive(
                tmpdir,
                "filters:\n"
                "  - match:\n"
                "      from: grafana.com\n"
                "    action:\n"
                "      add: [Tech/Grafana]\n"
                "      keepInInbox: true\n",
            )
            action = outlook["filters"][0]["action"]
            self.assertNotIn("moveToFolder", action)
            self.assertEqual(["Tech/Grafana"], action["add"])
            # The user-facing input marker is never in the derived output.
            self.assertNotIn("keepInInbox", action)
            # The internal marker IS present so the plan/sweep stage can honour it.
            self.assertTrue(action.get("noMoveToFolder"))

    def test_derive_filters_keep_in_inbox_beats_archive_on_remove_inbox(self):
        """keepInInbox wins over the derived Archive destination.

        `remove: [INBOX]` is required for this to reach the branch at all:
        `_apply_archive_on_remove_inbox` only rewrites specs whose *original*
        filter removes INBOX. Without it the branch was invoked but mutated
        nothing (verified by instrumentation: 0 specs changed), so this test was
        inert and asserted nothing about the archive path.

        With the directive present it caught a real defect. The two sibling
        derive branches disagreed: `_apply_move_to_folders` skips marked rules,
        while this branch archived them regardless. A rule carrying both
        `remove: [INBOX]` and `keepInInbox: true` therefore left the inbox
        through all three consumers (sync, plan and sweep all resolved
        Archive) even though `noMoveToFolder` was set.

        Archive is a *derived* destination, so the marker suppresses it — the
        documented contract is "suppress the derived Outlook moveToFolder"
        (config/filters_unified.example.yaml:30). An explicitly authored
        `moveToFolder` is a different case and still overrides the marker.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "filters.yaml"
            in_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: grafana.com\n"
                "    action:\n"
                "      add: [Tech/Grafana]\n"
                "      keepInInbox: true\n"
                "      remove: [INBOX]\n"
            )
            out_gmail = Path(tmpdir) / "gmail.yaml"
            out_outlook = Path(tmpdir) / "outlook.yaml"

            result = DeriveFiltersProcessor().process(
                DeriveFiltersRequest(
                    in_path=str(in_path),
                    out_gmail=str(out_gmail),
                    out_outlook=str(out_outlook),
                    outlook_archive_on_remove_inbox=True,
                )
            )
            self.assertTrue(result.ok())

            import yaml

            action = yaml.safe_load(out_outlook.read_text())["filters"][0]["action"]
            self.assertNotIn("keepInInbox", action)
            self.assertTrue(action.get("noMoveToFolder"))
            # No Archive destination: the marker suppressed it.
            self.assertNotIn("moveToFolder", action)
            # `add` survives because the archive branch never rewrote this spec.
            self.assertEqual(["Tech/Grafana"], action["add"])

    def test_derive_filters_archive_on_remove_inbox_still_archives_unmarked(self):
        """Contrast: without the marker, remove:[INBOX] must still derive Archive.

        Guards the fix above from becoming "keepInInbox disables archiving for
        everyone", which would stop commercial and newsletter mail being filed.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "filters.yaml"
            in_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: shop.example.com\n"
                "    action:\n"
                "      add: [Lists/Commercial]\n"
                "      remove: [INBOX]\n"
            )
            out_gmail = Path(tmpdir) / "gmail.yaml"
            out_outlook = Path(tmpdir) / "outlook.yaml"

            result = DeriveFiltersProcessor().process(
                DeriveFiltersRequest(
                    in_path=str(in_path),
                    out_gmail=str(out_gmail),
                    out_outlook=str(out_outlook),
                    outlook_archive_on_remove_inbox=True,
                )
            )
            self.assertTrue(result.ok())

            import yaml

            action = yaml.safe_load(out_outlook.read_text())["filters"][0]["action"]
            self.assertEqual("Archive", action.get("moveToFolder"))
            self.assertNotIn("add", action)
            self.assertNotIn("noMoveToFolder", action)

    def test_derive_filters_keep_in_inbox_stripped_with_all_flags_off(self):
        """Both flags off means neither branch runs — the marker must still be converted.

        Regression: stripping used to live inside the move/archive branches, which
        are mutually exclusive and both skipped under --no-outlook-move-to-folders,
        so keepInInbox leaked into the derived Outlook config.

        Now the conversion (_strip_keep_in_inbox) happens unconditionally and
        produces noMoveToFolder: true so the plan/sweep stage can honour it
        regardless of which flags were active at derive time.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "filters.yaml"
            in_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: grafana.com\n"
                "    action:\n"
                "      add: [Tech/Grafana]\n"
                "      keepInInbox: true\n"
            )
            out_gmail = Path(tmpdir) / "gmail.yaml"
            out_outlook = Path(tmpdir) / "outlook.yaml"

            result = DeriveFiltersProcessor().process(
                DeriveFiltersRequest(
                    in_path=str(in_path),
                    out_gmail=str(out_gmail),
                    out_outlook=str(out_outlook),
                    outlook_archive_on_remove_inbox=False,
                    outlook_move_to_folders=False,
                )
            )
            self.assertTrue(result.ok())

            import yaml

            action = yaml.safe_load(out_outlook.read_text())["filters"][0]["action"]
            self.assertNotIn("keepInInbox", action)
            # No folder move was requested, so none should have been derived.
            self.assertNotIn("moveToFolder", action)
            self.assertEqual(["Tech/Grafana"], action["add"])
            # The internal marker is present so later stages can honour keepInInbox.
            self.assertTrue(action.get("noMoveToFolder"))

    def test_derive_filters_processor_empty_filters(self):
        """DeriveFiltersProcessor handles empty filters list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "empty.yaml"
            in_path.write_text("filters: []\n")

            out_gmail = Path(tmpdir) / "g.yaml"
            out_outlook = Path(tmpdir) / "o.yaml"

            request = DeriveFiltersRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
            )
            result = DeriveFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.filters_count)

    def test_derive_filters_producer_output(self):
        """DeriveFiltersProducer prints paths."""
        result = ResultEnvelope(
            status="success",
            payload=DeriveFiltersResult(
                gmail_path=test_path("gmail.yaml"),  # noqa: S108 - test fixture path
                outlook_path=test_path("outlook.yaml"),  # noqa: S108 - test fixture path
                filters_count=10,
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            DeriveFiltersProducer().produce(result)
        output = buf.getvalue()
        self.assertIn("gmail:", output)
        self.assertIn("outlook:", output)


class OptimizeFiltersTests(TestCase):
    """Tests for optimize filters pipeline."""

    def test_optimize_filters_consumer_returns_request(self):
        """OptimizeFiltersRequestConsumer returns the request."""
        request = OptimizeFiltersRequest(in_path="in.yaml", out_path="out.yaml")
        consumer = OptimizeFiltersRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_optimize_filters_processor_merges_rules(self):
        """OptimizeFiltersProcessor merges rules with same destination."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "filters.yaml"
            # Three rules going to same label - should merge
            in_path.write_text("""filters:
  - match:
      from: a@example.com
    action:
      add: [Label1]
  - match:
      from: b@example.com
    action:
      add: [Label1]
  - match:
      from: c@example.com
    action:
      add: [Label1]
  - match:
      from: x@example.com
    action:
      add: [Label2]
""")
            out_path = Path(tmpdir) / "optimized.yaml"

            request = OptimizeFiltersRequest(
                in_path=str(in_path),
                out_path=str(out_path),
                merge_threshold=2,
            )
            result = OptimizeFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(4, result.payload.original_count)
            # 3 merged into 1 + 1 passthrough = 2
            self.assertEqual(2, result.payload.optimized_count)
            self.assertEqual(1, len(result.payload.merged_groups))
            self.assertEqual("Label1", result.payload.merged_groups[0].destination)
            self.assertEqual(3, result.payload.merged_groups[0].rules_merged)

    def test_optimize_filters_processor_empty_filters(self):
        """OptimizeFiltersProcessor handles empty filters list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            in_path = Path(tmpdir) / "empty.yaml"
            in_path.write_text("filters: []\n")

            out_path = Path(tmpdir) / "out.yaml"

            request = OptimizeFiltersRequest(
                in_path=str(in_path),
                out_path=str(out_path),
            )
            result = OptimizeFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(0, result.payload.original_count)
            self.assertEqual(0, result.payload.optimized_count)

    def test_optimize_filters_producer_output(self):
        """OptimizeFiltersProducer prints results."""
        result = ResultEnvelope(
            status="success",
            payload=OptimizeFiltersResult(
                out_path=test_path("optimized.yaml"),  # noqa: S108 - test fixture path
                original_count=10,
                optimized_count=5,
                merged_groups=[MergedGroup(destination="Label", rules_merged=3, unique_from_terms=3)],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            OptimizeFiltersProducer(preview=False).produce(result)
        output = buf.getvalue()
        self.assertIn("Original=10", output)
        self.assertIn("Optimized=5", output)

    def test_optimize_filters_producer_preview_mode(self):
        """OptimizeFiltersProducer shows merged groups in preview mode."""
        result = ResultEnvelope(
            status="success",
            payload=OptimizeFiltersResult(
                out_path=test_path("optimized.yaml"),  # noqa: S108 - test fixture path
                original_count=10,
                optimized_count=5,
                merged_groups=[MergedGroup(destination="Label", rules_merged=3, unique_from_terms=3)],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            OptimizeFiltersProducer(preview=True).produce(result)
        output = buf.getvalue()
        self.assertIn("Merged groups", output)
        self.assertIn("Label", output)
        self.assertIn("merged 3 rules", output)


class AuditFiltersTests(TestCase):
    """Tests for audit filters pipeline."""

    def test_audit_filters_consumer_returns_request(self):
        """AuditFiltersRequestConsumer returns the request."""
        request = AuditFiltersRequest(in_path="in.yaml", export_path="export.yaml")
        consumer = AuditFiltersRequestConsumer(request)
        self.assertEqual(request, consumer.consume())

    def test_audit_filters_processor_calculates_coverage(self):
        """AuditFiltersProcessor calculates filter coverage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Unified filters
            unified_path = Path(tmpdir) / "unified.yaml"
            unified_path.write_text("""filters:
  - match:
      from: known@example.com
    action:
      add: [Label1]
""")
            # Exported filters (from Gmail)
            export_path = Path(tmpdir) / "export.yaml"
            export_path.write_text("""filters:
  - match:
      from: known@example.com
    action:
      add: [Label1]
  - match:
      from: unknown@other.com
    action:
      add: [Label2]
""")
            request = AuditFiltersRequest(
                in_path=str(unified_path),
                export_path=str(export_path),
            )
            result = AuditFiltersProcessor().process(request)

            self.assertTrue(result.ok())
            self.assertEqual(2, result.payload.simple_total)
            self.assertEqual(1, result.payload.covered)
            self.assertEqual(1, result.payload.not_covered)

    def test_audit_filters_producer_output(self):
        """AuditFiltersProducer prints audit results."""
        result = ResultEnvelope(
            status="success",
            payload=AuditFiltersResult(
                simple_total=100,
                covered=90,
                not_covered=10,
                percentage=10.0,
                missing_samples=[("Label", "missing@example.com")],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=False).produce(result)
        output = buf.getvalue()
        self.assertIn("Simple Gmail rules: 100", output)
        self.assertIn("Covered by unified: 90", output)
        self.assertIn("Not unified: 10", output)

    def test_audit_filters_producer_preview_missing(self):
        """AuditFiltersProducer shows missing samples in preview mode."""
        result = ResultEnvelope(
            status="success",
            payload=AuditFiltersResult(
                simple_total=100,
                covered=90,
                not_covered=10,
                percentage=10.0,
                missing_samples=[("Label", "missing@example.com")],
            ),
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            AuditFiltersProducer(preview_missing=True).produce(result)
        output = buf.getvalue()
        self.assertIn("Missing examples", output)
        self.assertIn("missing@example.com", output)


class DeriveToRuleActionSeamTests(TestCase):
    """End-to-end seam tests: derive step output fed into the rule-action builder.

    These tests cover the boundary between the derive pipeline and the Outlook
    rule/sweep processors.  Each module was individually correct:

    - The derive tests confirmed that keepInInbox suppresses moveToFolder in the
      derived YAML and that the keepInInbox marker is stripped from the output.
    - The rule-action tests confirmed that _build_rule_action honours move_to_folders.

    Neither set of tests covered the seam — whether the derived output, after
    stripping the marker, still resulted in no folder move at the plan/sweep stage.
    The answer was: it did NOT, because _build_rule_action fell through to the
    ``elif ctx.move_to_folders and add_labs`` branch and re-derived a folder.

    This class is the test that would have caught the original bug.
    """

    def _derive_outlook(self, tmpdir: str, yaml_text: str) -> list[dict]:
        """Run the derive processor and return the derived Outlook filter list."""
        import yaml

        in_path = Path(tmpdir) / "filters.yaml"
        in_path.write_text(yaml_text)
        out_gmail = Path(tmpdir) / "gmail.yaml"
        out_outlook = Path(tmpdir) / "outlook.yaml"

        result = DeriveFiltersProcessor().process(
            DeriveFiltersRequest(
                in_path=str(in_path),
                out_gmail=str(out_gmail),
                out_outlook=str(out_outlook),
                outlook_move_to_folders=True,
            )
        )
        self.assertTrue(result.ok(), "derive step failed")
        return yaml.safe_load(out_outlook.read_text())["filters"]

    def test_keep_in_inbox_rule_produces_no_folder_move_in_rule_action(self):
        """keepInInbox rule: derive → _build_rule_action produces addLabelIds, no moveToFolderId.

        This is the regression test for the bug.  move_to_folders is True (the
        CLI default), so without the noMoveToFolder guard the builder fires the
        ``elif ctx.move_to_folders and add_labs`` branch and re-derives a folder
        from the first add label — moving the mail out of the inbox.
        """
        from unittest.mock import MagicMock
        from mail.outlook.processors_rules_helpers import RuleContext, _build_rule_action

        with tempfile.TemporaryDirectory() as tmpdir:
            filters = self._derive_outlook(
                tmpdir,
                "filters:\n"
                "  - match:\n"
                "      from: grafana.com\n"
                "    action:\n"
                "      add: [Tech/Grafana]\n"
                "      keepInInbox: true\n",
            )

            client = MagicMock()
            ctx = RuleContext(
                client=client,
                name_to_id={"Tech/Grafana": "label-id-grafana"},
                folder_map={"Tech/Grafana": "folder-id-grafana"},
                move_to_folders=True,
            )

            rule_action = _build_rule_action(filters[0]["action"], ctx)

            # The rule must NOT move mail to a folder.
            self.assertNotIn(
                "moveToFolderId",
                rule_action,
                "keepInInbox rule must not produce moveToFolderId (inbox move regression)",
            )
            client.ensure_folder_path.assert_not_called()
            # The rule must categorise with label IDs.
            self.assertIn("addLabelIds", rule_action)

    def test_normal_rule_still_gets_folder_in_rule_action(self):
        """Normal rule (no keepInInbox): derive → _build_rule_action still produces moveToFolderId.

        Contrast test: the fix must not disable folder derivation for every rule.
        """
        from unittest.mock import MagicMock
        from mail.outlook.processors_rules_helpers import RuleContext, _build_rule_action

        with tempfile.TemporaryDirectory() as tmpdir:
            filters = self._derive_outlook(
                tmpdir,
                "filters:\n"
                "  - match:\n"
                "      from: nintendo.net\n"
                "    action:\n"
                "      add: [Tech/Nintendo]\n",
            )

            client = MagicMock()
            client.ensure_folder_path.return_value = "folder-id-nintendo"
            ctx = RuleContext(
                client=client,
                name_to_id={},
                folder_map={},
                move_to_folders=True,
            )

            rule_action = _build_rule_action(filters[0]["action"], ctx)

            self.assertIn("moveToFolderId", rule_action)
            self.assertNotIn("addLabelIds", rule_action)

    def test_mixed_rules_seam_both_paths_correct(self):
        """One keepInInbox rule and one normal rule: each takes its correct path.

        This is the definitive end-to-end regression test.  Both rules go through
        the same derive step and the same _build_rule_action call; one must stay
        in the inbox and one must be moved to a folder.
        """
        from unittest.mock import MagicMock
        from mail.outlook.processors_rules_helpers import RuleContext, _build_rule_action

        with tempfile.TemporaryDirectory() as tmpdir:
            filters = self._derive_outlook(
                tmpdir,
                "filters:\n"
                "  - match:\n"
                "      from: grafana.com\n"
                "    action:\n"
                "      add: [Tech/Grafana]\n"
                "      keepInInbox: true\n"
                "  - match:\n"
                "      from: nintendo.net\n"
                "    action:\n"
                "      add: [Tech/Nintendo]\n",
            )
            self.assertEqual(2, len(filters), "expected 2 derived filters")

            client = MagicMock()
            client.ensure_folder_path.return_value = "folder-id-nintendo"
            ctx = RuleContext(
                client=client,
                name_to_id={"Tech/Grafana": "label-id-grafana"},
                folder_map={},
                move_to_folders=True,
            )

            grafana_action = _build_rule_action(
                next(f["action"] for f in filters if "grafana" in str(f.get("match", {}))),
                ctx,
            )
            nintendo_action = _build_rule_action(
                next(f["action"] for f in filters if "nintendo" in str(f.get("match", {}))),
                ctx,
            )

            # keepInInbox rule: categorise only, no move.
            self.assertNotIn("moveToFolderId", grafana_action)
            self.assertIn("addLabelIds", grafana_action)

            # Normal rule: folder move.
            self.assertIn("moveToFolderId", nintendo_action)
            self.assertNotIn("addLabelIds", nintendo_action)
