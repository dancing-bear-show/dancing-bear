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


if __name__ == "__main__":
    unittest.main()
