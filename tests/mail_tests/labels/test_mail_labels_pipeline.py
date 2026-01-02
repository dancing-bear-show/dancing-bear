from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

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
from tests.mail_tests.fixtures import (
    FakeGmailClient,
    make_user_label,
    make_system_label,
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
        args = SimpleNamespace(config=str(cfg_path), **flags)
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


if __name__ == "__main__":
    unittest.main()
