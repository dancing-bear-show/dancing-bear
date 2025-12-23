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


class _FakeLabelsClient:
    def __init__(self):
        self.labels = [
            {"id": "LBL_KEEP", "name": "Keep", "type": "user", "color": {"textColor": "#111", "backgroundColor": "#eee"}},
            {"id": "LBL_OLD", "name": "OldLabel", "type": "user"},
            {"id": "LBL_SYS", "name": "INBOX", "type": "system"},
        ]
        self.merged = []

    def list_labels(self):
        return list(self.labels)

    def get_label_id_map(self):
        return {lab["name"]: lab["id"] for lab in self.labels}

    def create_label(self, **body):
        self.labels.append({"id": f"LBL_{len(self.labels)}", **body})

    def update_label(self, label_id, body):
        for lab in self.labels:
            if lab["id"] == label_id:
                lab.update(body)
                return

    def delete_label(self, label_id):
        self.labels = [lab for lab in self.labels if lab["id"] != label_id]

    def ensure_label(self, name):
        mapping = self.get_label_id_map()
        if name in mapping:
            return mapping[name]
        new_id = f"LBL_{len(self.labels)}"
        self.labels.append({"id": new_id, "name": name, "type": "user"})
        return new_id

    def list_message_ids(self, label_ids=None, max_pages=1, page_size=500, query=None):
        return ["m1", "m2"]

    def batch_modify_messages(self, ids, add_label_ids=None, remove_label_ids=None):
        self.merged.append({"ids": ids, "add": add_label_ids, "remove": remove_label_ids})


class LabelsPipelineTests(unittest.TestCase):
    def _make_context(self, data: str, **flags):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cfg_path = Path(tmpdir.name) / "labels.yaml"
        cfg_path.write_text(data)
        args = SimpleNamespace(config=str(cfg_path), **flags)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _FakeLabelsClient()
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
