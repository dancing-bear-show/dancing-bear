from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from mail.context import MailContext
from mail.labels.consumers import (
    LabelsPlanConsumer,
    LabelsSyncConsumer,
    LabelsExportConsumer,
)
from mail.labels.processors import (
    LabelsPlanProcessor,
    LabelsSyncProcessor,
    LabelsExportProcessor,
)
from mail.labels.producers import (
    LabelsPlanProducer,
    LabelsSyncProducer,
    LabelsExportProducer,
)
from tests.fixtures import capture_stdout
from tests.mail_tests.fixtures import (
    FakeGmailClient,
    make_args,
    make_user_label,
    make_system_label,
    make_success_envelope,
    make_error_envelope,
)


def _make_labels_client() -> FakeGmailClient:
    """Create a FakeGmailClient with standard test labels."""
    return FakeGmailClient(labels=[
        make_user_label("Keep", "LBL_KEEP", color={"textColor": "#111", "backgroundColor": "#eee"}),
        make_user_label("OldLabel", "LBL_OLD"),
        make_system_label("INBOX"),
    ])


class LabelsPipelineTests(unittest.TestCase):
    def _make_context(self, data: str, **flags):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cfg_path = Path(tmpdir.name) / "labels.yaml"
        cfg_path.write_text(data)
        args = make_args(config=str(cfg_path), **flags)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _make_labels_client()
        return ctx

    def test_plan_pipeline_matches_legacy_output(self):
        ctx = self._make_context(
            """
labels:
  - name: Keep
    color:
      textColor: "#000"
      backgroundColor: "#fff"
  - name: NewLabel
""",
            delete_missing=False,
        )

        consumer = LabelsPlanConsumer(ctx)
        payload = consumer.consume()
        processor = LabelsPlanProcessor()
        envelope = processor.process(payload)
        buf = io.StringIO()
        producer = LabelsPlanProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("Plan: create=1 update=1", out)
        self.assertIn("NewLabel", out)
        self.assertIn("Would update:", out)
        self.assertIn("Keep (color:", out)

    def test_sync_pipeline_applies_creates_updates_deletes_and_redirects(self):
        ctx = self._make_context(
            """
labels:
  - name: Keep
  - name: Fresh
    messageListVisibility: show
redirects:
  - from: OldLabel
    to: Keep
""",
            delete_missing=True,
            sweep_redirects=True,
            dry_run=False,
        )
        consumer = LabelsSyncConsumer(ctx)
        payload = consumer.consume()
        processor = LabelsSyncProcessor()
        envelope = processor.process(payload)
        producer = LabelsSyncProducer(ctx.gmail_client, dry_run=False)

        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("Created label: Fresh", out)
        self.assertIn("Merged 'OldLabel' into 'Keep'", out)
        self.assertTrue(any(lab["name"] == "Fresh" for lab in ctx.gmail_client.labels))
        self.assertFalse(any(lab["name"] == "OldLabel" for lab in ctx.gmail_client.labels))

    def test_export_pipeline_writes_expected_yaml(self):
        ctx = self._make_context(
            """
labels:
  - name: Keep
""",
        )
        args = ctx.args
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "labels.yaml"
            args.out = str(out)
            export_ctx = MailContext.from_args(args)
            export_ctx.gmail_client = ctx.gmail_client
            consumer = LabelsExportConsumer(export_ctx)
            payload = consumer.consume()
            processor = LabelsExportProcessor()
            envelope = processor.process(payload)
            buf = io.StringIO()
            producer = LabelsExportProducer()
            with redirect_stdout(buf):
                producer.produce(envelope)
            self.assertTrue(out.exists())
            import yaml

            data = yaml.safe_load(out.read_text())
            self.assertIn("labels", data)
            self.assertGreaterEqual(len(data["labels"]), 1)
            self.assertIn("Exported", buf.getvalue())


class RunLabelsCommandsTests(unittest.TestCase):
    """Tests for the run_labels_* command wrappers in commands_plan.py.

    These patch the Consumer/Processor/Producer classes as imported into
    mail.labels.commands_plan (the usage site), not their defining modules.
    """

    def _make_args(self, **flags):
        return make_args(config="/tmp/unused.yaml", **flags)  # nosec B108 - never opened; consumer is mocked

    # -- run_labels_plan ---------------------------------------------------

    def test_run_labels_plan_returns_0_on_success(self):
        from mail.labels import commands_plan

        envelope = make_success_envelope()
        with patch.object(commands_plan, "LabelsPlanConsumer") as mock_consumer_cls, \
                patch.object(commands_plan, "LabelsPlanProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsPlanProducer") as mock_producer_cls:
            mock_processor_cls.return_value.process.return_value = envelope
            result = commands_plan.run_labels_plan(self._make_args())

        self.assertEqual(result, 0)
        mock_consumer_cls.return_value.consume.assert_called_once()
        mock_processor_cls.return_value.process.assert_called_once()
        mock_producer_cls.return_value.produce.assert_called_once_with(envelope)

    def test_run_labels_plan_returns_1_on_error_envelope(self):
        from mail.labels import commands_plan

        envelope = make_error_envelope()
        with patch.object(commands_plan, "LabelsPlanConsumer"), \
                patch.object(commands_plan, "LabelsPlanProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsPlanProducer"):
            mock_processor_cls.return_value.process.return_value = envelope
            result = commands_plan.run_labels_plan(self._make_args())

        self.assertEqual(result, 1)

    def test_run_labels_plan_returns_1_and_prints_on_value_error(self):
        from mail.labels import commands_plan

        with patch.object(commands_plan, "LabelsPlanConsumer") as mock_consumer_cls, \
                patch.object(commands_plan, "LabelsPlanProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsPlanProducer") as mock_producer_cls:
            mock_consumer_cls.return_value.consume.side_effect = ValueError("bad config")
            with capture_stdout() as buf:
                result = commands_plan.run_labels_plan(self._make_args())

        self.assertEqual(result, 1)
        self.assertIn("bad config", buf.getvalue())
        mock_processor_cls.return_value.process.assert_not_called()
        mock_producer_cls.return_value.produce.assert_not_called()

    # -- run_labels_export ---------------------------------------------------

    def test_run_labels_export_returns_0_on_success(self):
        from mail.labels import commands_plan

        envelope = make_success_envelope()
        with patch.object(commands_plan, "LabelsExportConsumer"), \
                patch.object(commands_plan, "LabelsExportProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsExportProducer") as mock_producer_cls:
            mock_processor_cls.return_value.process.return_value = envelope
            result = commands_plan.run_labels_export(self._make_args())

        self.assertEqual(result, 0)
        mock_producer_cls.return_value.produce.assert_called_once_with(envelope)

    def test_run_labels_export_returns_1_on_value_error(self):
        from mail.labels import commands_plan

        with patch.object(commands_plan, "LabelsExportConsumer") as mock_consumer_cls, \
                patch.object(commands_plan, "LabelsExportProcessor"), \
                patch.object(commands_plan, "LabelsExportProducer"):
            mock_consumer_cls.return_value.consume.side_effect = ValueError("no such file")
            with capture_stdout() as buf:
                result = commands_plan.run_labels_export(self._make_args())

        self.assertEqual(result, 1)
        self.assertIn("no such file", buf.getvalue())

    # -- run_labels_sync ---------------------------------------------------

    def test_run_labels_sync_returns_0_on_success_dry_run_true(self):
        from mail.labels import commands_plan

        envelope = make_success_envelope()
        fake_client = FakeGmailClient()
        with patch.object(commands_plan, "LabelsSyncConsumer") as mock_consumer_cls, \
                patch.object(commands_plan, "LabelsSyncProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsSyncProducer") as mock_producer_cls:
            mock_processor_cls.return_value.process.return_value = envelope
            args = self._make_args(dry_run=True)
            args._gmail_client = fake_client  # noqa: SLF001 - test seam, not the module under test's leak

            with patch.object(MailContext, "get_gmail_client", return_value=fake_client):
                result = commands_plan.run_labels_sync(args)

        self.assertEqual(result, 0)
        mock_consumer_cls.return_value.consume.assert_called_once()
        mock_processor_cls.return_value.process.assert_called_once()
        mock_producer_cls.assert_called_once_with(fake_client, dry_run=True)
        mock_producer_cls.return_value.produce.assert_called_once_with(envelope)

    def test_run_labels_sync_returns_1_on_error_envelope_dry_run_false(self):
        from mail.labels import commands_plan

        envelope = make_error_envelope()
        fake_client = FakeGmailClient()
        with patch.object(commands_plan, "LabelsSyncConsumer"), \
                patch.object(commands_plan, "LabelsSyncProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsSyncProducer") as mock_producer_cls:
            mock_processor_cls.return_value.process.return_value = envelope
            args = self._make_args(dry_run=False)

            with patch.object(MailContext, "get_gmail_client", return_value=fake_client):
                result = commands_plan.run_labels_sync(args)

        self.assertEqual(result, 1)
        mock_producer_cls.assert_called_once_with(fake_client, dry_run=False)

    def test_run_labels_sync_defaults_dry_run_false_when_flag_absent(self):
        from mail.labels import commands_plan

        envelope = make_success_envelope()
        fake_client = FakeGmailClient()
        with patch.object(commands_plan, "LabelsSyncConsumer"), \
                patch.object(commands_plan, "LabelsSyncProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsSyncProducer") as mock_producer_cls:
            mock_processor_cls.return_value.process.return_value = envelope
            args = self._make_args()  # no dry_run attribute at all

            with patch.object(MailContext, "get_gmail_client", return_value=fake_client):
                result = commands_plan.run_labels_sync(args)

        self.assertEqual(result, 0)
        mock_producer_cls.assert_called_once_with(fake_client, dry_run=False)

    def test_run_labels_sync_returns_1_and_prints_on_value_error(self):
        from mail.labels import commands_plan

        fake_client = FakeGmailClient()
        with patch.object(commands_plan, "LabelsSyncConsumer") as mock_consumer_cls, \
                patch.object(commands_plan, "LabelsSyncProcessor") as mock_processor_cls, \
                patch.object(commands_plan, "LabelsSyncProducer") as mock_producer_cls:
            mock_consumer_cls.return_value.consume.side_effect = ValueError("bad redirects")
            args = self._make_args(dry_run=False)

            with patch.object(MailContext, "get_gmail_client", return_value=fake_client):
                with capture_stdout() as buf:
                    result = commands_plan.run_labels_sync(args)

        self.assertEqual(result, 1)
        self.assertIn("bad redirects", buf.getvalue())
        mock_processor_cls.return_value.process.assert_not_called()
        mock_producer_cls.return_value.produce.assert_not_called()

    # -- run_labels_list -----------------------------------------------------

    def test_run_labels_list_prints_id_and_name_using_injected_client(self):
        from mail.labels import commands_plan

        client = MagicMock()
        client.list_labels.return_value = [
            {"id": "L1", "name": "Work"},
            {"id": "L2", "name": "Personal"},
        ]
        args = self._make_args()
        args._gmail_client = client  # noqa: SLF001 - documented injection seam

        with capture_stdout() as buf:
            result = commands_plan.run_labels_list(args)

        self.assertEqual(result, 0)
        out = buf.getvalue()
        self.assertIn("L1\tWork", out)
        self.assertIn("L2\tPersonal", out)
        client.list_labels.assert_called_once()

    def test_run_labels_list_falls_back_to_unknown_for_missing_name(self):
        from mail.labels import commands_plan

        client = MagicMock()
        client.list_labels.return_value = [{"id": "L3"}]
        args = self._make_args()
        args._gmail_client = client  # noqa: SLF001 - documented injection seam

        with capture_stdout() as buf:
            result = commands_plan.run_labels_list(args)

        self.assertEqual(result, 0)
        self.assertIn("L3\t<unknown>", buf.getvalue())

    def test_run_labels_list_authenticates_when_no_injected_client(self):
        from mail.labels import commands_plan

        client = MagicMock()
        client.list_labels.return_value = []
        args = self._make_args()  # no _gmail_client attribute

        with patch("mail.utils.cli_helpers.gmail_client_authenticated", return_value=client) as mock_auth:
            with capture_stdout():
                result = commands_plan.run_labels_list(args)

        self.assertEqual(result, 0)
        mock_auth.assert_called_once_with(args)
        client.list_labels.assert_called_once()


# ---------------------------------------------------------------------------
# _print_list_section: boundary tests for line 26 (> 20 items)
# ---------------------------------------------------------------------------

class PrintListSectionTests(unittest.TestCase):
    """Tests for _print_list_section in labels/producers.py."""

    def test_empty_items_prints_nothing(self):
        from mail.labels.producers import _print_list_section
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_list_section("Title", [], lambda x: x)
        self.assertEqual("", buf.getvalue())

    def test_exactly_20_items_no_trailer(self):
        from mail.labels.producers import _print_list_section
        items = [f"item{i}" for i in range(20)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_list_section("Title", items, lambda x: x)
        out = buf.getvalue()
        self.assertIn("Title:", out)
        self.assertNotIn("more", out)

    def test_more_than_20_items_shows_trailer(self):
        from mail.labels.producers import _print_list_section
        items = [f"item{i}" for i in range(21)]
        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_list_section("Title", items, lambda x: x)
        out = buf.getvalue()
        self.assertIn("and 1 more", out)


# ---------------------------------------------------------------------------
# LabelsPlanProducer: error-path tests (lines 42-43)
# ---------------------------------------------------------------------------

class LabelsPlanProducerErrorTests(unittest.TestCase):
    """LabelsPlanProducer failure paths — pairing each sad path with happy path."""

    def test_produce_succeeds_with_valid_envelope(self):
        from mail.labels.processors import LabelsPlanResult
        plan = LabelsPlanResult(to_create=[{"name": "NewX"}], to_update=[], to_delete=[], show_delete=False)
        envelope = make_success_envelope(payload=plan)
        buf = io.StringIO()
        producer = LabelsPlanProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("NewX", buf.getvalue())

    def test_produce_prints_failed_when_result_not_ok(self):
        # Sad path: result.ok() is False
        envelope = make_error_envelope()
        buf = io.StringIO()
        producer = LabelsPlanProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Labels plan failed.", buf.getvalue())

    def test_produce_prints_failed_when_payload_is_none(self):
        # Sad path: ok but empty payload (line 43)
        envelope = make_success_envelope(payload=None)
        buf = io.StringIO()
        producer = LabelsPlanProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Labels plan failed.", buf.getvalue())


# ---------------------------------------------------------------------------
# LabelsSyncProducer: error-path and apply-path tests
# ---------------------------------------------------------------------------

class LabelsSyncProducerUncoveredTests(unittest.TestCase):
    """LabelsSyncProducer: sad-path and apply-path coverage."""

    # -- Failure paths (lines 66-67) -----------------------------------------

    def test_produce_prints_failed_when_result_not_ok(self):
        client = _make_labels_client()
        envelope = make_error_envelope()
        buf = io.StringIO()
        producer = LabelsSyncProducer(client)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Labels sync failed.", buf.getvalue())

    def test_produce_prints_failed_when_payload_is_none(self):
        client = _make_labels_client()
        envelope = make_success_envelope(payload=None)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Labels sync failed.", buf.getvalue())

    # -- _apply_creates (lines 85, 88) ----------------------------------------

    def test_apply_creates_skips_spec_without_name(self):
        # Sad path: spec missing 'name' key (line 85 branch — continue)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        initial_count = len(client.labels)
        plan = LabelsPlanResult(to_create=[{"color": "red"}], to_update=[], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertNotIn("Created label:", buf.getvalue())
        self.assertEqual(initial_count, len(client.labels))

    def test_apply_creates_dry_run_prints_would_create(self):
        # Happy dry-run path (line 88 not taken)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[{"name": "DryNew"}], to_update=[], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=True)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Would create label: DryNew", buf.getvalue())
        self.assertFalse(any(lab["name"] == "DryNew" for lab in client.labels))

    def test_apply_creates_live_creates_label(self):
        # Happy live path (line 88 — client.create_label called)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[{"name": "NewOne"}], to_update=[], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Created label: NewOne", buf.getvalue())
        self.assertTrue(any(lab["name"] == "NewOne" for lab in client.labels))

    # -- _apply_updates (lines 98-109) ----------------------------------------

    def test_apply_updates_dry_run_prints_would_update(self):
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult, LabelChange
        client = _make_labels_client()
        change = LabelChange(name="Keep", changes={"color": {"from": "#000", "to": "#fff"}}, spec={})
        plan = LabelsPlanResult(to_create=[], to_update=[change], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=True)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Would update label: Keep", buf.getvalue())

    def test_apply_updates_live_updates_label(self):
        # Happy path: label found in map, update_label called
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult, LabelChange
        client = _make_labels_client()
        change = LabelChange(name="Keep", changes={"color": {"from": "#000", "to": "#fff"}}, spec={})
        plan = LabelsPlanResult(to_create=[], to_update=[change], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Updated label: Keep", buf.getvalue())

    def test_apply_updates_live_skips_label_not_in_map(self):
        # Sad path: label_id not found in get_label_id_map() — continue (line 106)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult, LabelChange
        client = _make_labels_client()
        change = LabelChange(name="NotExist", changes={"color": {"from": "#000", "to": "#fff"}}, spec={})
        plan = LabelsPlanResult(to_create=[], to_update=[change], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertNotIn("Updated label: NotExist", buf.getvalue())

    # -- _apply_deletes (lines 115-122) ----------------------------------------

    def test_apply_deletes_dry_run_prints_would_delete(self):
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[], to_update=[], to_delete=["OldLabel"], show_delete=True)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=True)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Would delete label: OldLabel", buf.getvalue())

    def test_apply_deletes_live_deletes_label(self):
        # Happy path: delete_label called, label removed
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[], to_update=[], to_delete=["OldLabel"], show_delete=True)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Deleted label: OldLabel", buf.getvalue())
        self.assertFalse(any(lab["name"] == "OldLabel" for lab in client.labels))

    def test_apply_deletes_live_skips_label_not_in_map(self):
        # Sad path: label not found in id map (line 119 branch — label_id falsy)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[], to_update=[], to_delete=["Ghost"], show_delete=True)
        sync_result = LabelsSyncResult(plan=plan, redirects=[])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertNotIn("Deleted label: Ghost", buf.getvalue())

    # -- _apply_one_redirect (lines 150, 155, 158-159) -----------------------

    def test_apply_one_redirect_same_src_and_dest_skipped(self):
        # Sad path: old == new (line 149-150, returns None)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[], to_update=[], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[{"from": "Keep", "to": "Keep"}])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertNotIn("Merged", buf.getvalue())

    def test_apply_one_redirect_old_id_not_found_skipped(self):
        # Sad path: old label not in id map (line 155 — not old_id, returns None)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[], to_update=[], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[{"from": "Ghost", "to": "Keep"}])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=False)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertNotIn("Merged", buf.getvalue())

    def test_apply_one_redirect_dry_run_prints_would_merge(self):
        # Dry-run path (lines 158-159)
        from mail.labels.processors import LabelsPlanResult, LabelsSyncResult
        client = _make_labels_client()
        plan = LabelsPlanResult(to_create=[], to_update=[], to_delete=[], show_delete=False)
        sync_result = LabelsSyncResult(plan=plan, redirects=[{"from": "OldLabel", "to": "Keep"}])
        envelope = make_success_envelope(payload=sync_result)
        buf = io.StringIO()
        producer = LabelsSyncProducer(client, dry_run=True)
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Would merge 'OldLabel' into 'Keep'", buf.getvalue())


# ---------------------------------------------------------------------------
# LabelsExportProducer: error-path tests (lines 192-193)
# ---------------------------------------------------------------------------

class LabelsExportProducerErrorTests(unittest.TestCase):
    """LabelsExportProducer failure paths."""

    def test_produce_prints_failed_when_result_not_ok(self):
        # Sad path: ok() returns False (line 192)
        envelope = make_error_envelope()
        buf = io.StringIO()
        producer = LabelsExportProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Labels export failed.", buf.getvalue())

    def test_produce_prints_failed_when_payload_is_none(self):
        # Sad path: ok but payload is None (line 192 second condition)
        envelope = make_success_envelope(payload=None)
        buf = io.StringIO()
        producer = LabelsExportProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Labels export failed.", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
