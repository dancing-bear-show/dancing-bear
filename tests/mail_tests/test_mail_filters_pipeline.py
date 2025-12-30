from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import List

from mail.context import MailContext
from mail.filters.consumers import (
    FiltersPlanConsumer,
    FiltersPlanPayload,
    FiltersSyncPayload,
    FiltersImpactPayload,
    FiltersExportConsumer,
    FiltersSweepConsumer,
    FiltersSweepRangeConsumer,
    FiltersPruneConsumer,
    FiltersAddForwardConsumer,
    FiltersAddTokenConsumer,
    FiltersRemoveTokenConsumer,
)
from mail.filters.processors import (
    FiltersPlanProcessor,
    FiltersSyncProcessor,
    FiltersImpactProcessor,
    FiltersExportProcessor,
    FiltersSweepProcessor,
    FiltersSweepRangeProcessor,
    FiltersPruneProcessor,
    FiltersAddForwardProcessor,
    FiltersAddTokenProcessor,
    FiltersRemoveTokenProcessor,
)
from mail.filters.producers import (
    FiltersPlanProducer,
    FiltersSyncProducer,
    FiltersImpactProducer,
    FiltersExportProducer,
    FiltersSweepProducer,
    FiltersSweepRangeProducer,
    FiltersPruneProducer,
    FiltersAddForwardProducer,
    FiltersAddTokenProducer,
    FiltersRemoveTokenProducer,
)

from tests.mail_tests.fixtures import FakeGmailClient


def _make_pipeline_client():
    """Create a FakeGmailClient configured for filters pipeline tests."""
    return FakeGmailClient(
        labels=[
            {"id": "LBL_VIP", "name": "VIP"},
            {"id": "LBL_OTHER", "name": "Other"},
        ],
        filters=[
            {
                "id": "EXTRA",
                "criteria": {"from": "someone@example.com"},
                "action": {"addLabelIds": ["LBL_OTHER"]},
            }
        ],
        message_ids_by_query={
            "foo@example.com": ["m1"] * 5,
            'subject:"bar report"': ["m2"] * 3,
        },
        verified_forward_addresses={"verified@example.com"},
    )


class FiltersPlanConsumerTests(unittest.TestCase):
    def test_consume_loads_config_and_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "filters.yaml"
            cfg_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: foo@example.com\n"
                "    action:\n"
                "      add:\n"
                "        - VIP\n"
            )
            args = SimpleNamespace(config=str(cfg_path), credentials=None, token=None, profile=None)
            ctx = MailContext.from_args(args)
            ctx.gmail_client = _make_pipeline_client()

            consumer = FiltersPlanConsumer(ctx)
            payload = consumer.consume()

            self.assertEqual(len(payload.desired_filters), 1)
            self.assertEqual(payload.name_to_id.get("VIP"), "LBL_VIP")
            self.assertEqual(payload.id_to_name.get("LBL_OTHER"), "Other")
            self.assertEqual(len(payload.existing_filters), 1)
            self.assertFalse(payload.delete_missing)


class FiltersPlanProcessorTests(unittest.TestCase):
    def test_processor_and_producer_match_legacy_output(self):
        payload = FiltersPlanPayload(
            desired_filters=[
                {"match": {"from": "foo@example.com"}, "action": {"add": ["VIP"]}},
                {"match": {"from": "bar@example.com"}, "action": {"add": ["Other"]}},
            ],
            existing_filters=[
                {
                    "id": "KEEP",
                    "criteria": {"from": "foo@example.com"},
                    "action": {"addLabelIds": ["LBL_VIP"]},
                },
                {
                    "id": "DROP",
                    "criteria": {"from": "dropme@example.com"},
                    "action": {"addLabelIds": ["LBL_OTHER"]},
                },
            ],
            id_to_name={"LBL_VIP": "VIP", "LBL_OTHER": "Other"},
            name_to_id={"VIP": "LBL_VIP", "Other": "LBL_OTHER"},
            delete_missing=True,
        )
        processor = FiltersPlanProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        result = envelope.payload
        self.assertIsNotNone(result)
        self.assertEqual(len(result.to_create), 1)
        self.assertEqual(len(result.to_delete), 1)

        buf = io.StringIO()
        producer = FiltersPlanProducer(preview_limit=5)
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()

        self.assertIn("Plan: create=1 delete=1", output)
        self.assertIn("from:bar@example.com", output)
        self.assertIn("Would delete (not present in YAML):", output)
        self.assertIn("add=['Other']", output)


class FiltersSyncProcessorTests(unittest.TestCase):
    def test_sync_processor_detects_diffs_and_producer_executes(self):
        payload = FiltersSyncPayload(
            desired_filters=[
                {
                    "match": {"from": "bar@example.com"},
                    "action": {"add": ["VIP"], "categorizeAs": "promotions"},
                },
            ],
            existing_filters=[
                {
                    "id": "DROP",
                    "criteria": {"from": "drop@example.com"},
                    "action": {"addLabelIds": ["LBL_OTHER"]},
                }
            ],
            id_to_name={"LBL_VIP": "VIP", "LBL_OTHER": "Other"},
            name_to_id={"VIP": "LBL_VIP", "Other": "LBL_OTHER"},
            delete_missing=True,
            require_forward_verified=False,
            verified_forward_addresses=set(),
        )
        processor = FiltersSyncProcessor()
        envelope = processor.process(payload)
        self.assertTrue(envelope.ok())
        result = envelope.payload
        self.assertIsNotNone(result)
        self.assertEqual(len(result.to_create), 1)
        self.assertEqual(len(result.to_delete), 1)

        fake_client = FakeGmailClient(
            labels=[{"id": "LBL_VIP", "name": "VIP"}, {"id": "LBL_OTHER", "name": "Other"}],
            filters=[
                {
                    "id": "DROP",
                    "criteria": {"from": "drop@example.com"},
                    "action": {"addLabelIds": ["LBL_OTHER"]},
                }
            ],
        )
        producer = FiltersSyncProducer(fake_client, dry_run=False)
        producer.produce(envelope)

        created = [f for f in fake_client.created_filters]
        self.assertTrue(
            any(
                "CATEGORY_PROMOTIONS" in (f.get("action", {}).get("addLabelIds") or [])
                for f in created
            )
        )

    def test_sync_processor_errors_on_unverified_forward(self):
        payload = FiltersSyncPayload(
            desired_filters=[
                {"match": {"from": "foo@example.com"}, "action": {"forward": "bad@example.com"}}
            ],
            existing_filters=[],
            id_to_name={},
            name_to_id={},
            delete_missing=False,
            require_forward_verified=True,
            verified_forward_addresses={"verified@example.com"},
        )
        processor = FiltersSyncProcessor()
        envelope = processor.process(payload)
        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.diagnostics.get("code"), 2)


class FiltersImpactProcessorTests(unittest.TestCase):
    def test_impact_processor_counts_and_producer_outputs(self):
        client = _make_pipeline_client()
        payload = FiltersImpactPayload(
            filters=[
                {"match": {"from": "foo@example.com"}},
                {"match": {"subject": "Bar Report"}},
            ],
            days=7,
            only_inbox=True,
            pages=2,
            client=client,
        )
        processor = FiltersImpactProcessor()
        envelope = processor.process(payload)
        self.assertTrue(envelope.ok())
        buf = io.StringIO()
        producer = FiltersImpactProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("     5", out)
        self.assertIn("     3", out)
        self.assertIn("Total impacted: 8", out)


class FiltersExportProcessorTests(unittest.TestCase):
    def test_export_pipeline_writes_yaml(self):
        args = SimpleNamespace(out=None)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _make_pipeline_client()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "filters.yaml"
            ctx.args.out = str(out_path)
            consumer = FiltersExportConsumer(ctx)
            payload = consumer.consume()
            processor = FiltersExportProcessor()
            envelope = processor.process(payload)
            producer = FiltersExportProducer()
            buf = io.StringIO()
            with redirect_stdout(buf):
                producer.produce(envelope)
            self.assertTrue(out_path.exists())
            import yaml

            data = yaml.safe_load(out_path.read_text())
            self.assertIn("filters", data)
            self.assertEqual(len(data["filters"]), len(ctx.gmail_client.list_filters()))
            self.assertIn("criteria", data["filters"][0])
            self.assertIn("action", data["filters"][0])
            self.assertIn("Exported", buf.getvalue())


class FiltersSweepProcessorTests(unittest.TestCase):
    def _make_context(self, data: str, **flags):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cfg_path = Path(tmpdir.name) / "filters.yaml"
        cfg_path.write_text(data)
        args = SimpleNamespace(config=str(cfg_path), **flags)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _make_pipeline_client()
        return ctx

    def test_sweep_pipeline_modifies_messages(self):
        ctx = self._make_context(
            """
filters:
  - match:
      from: foo@example.com
    action:
      add:
        - VIP
""",
            days=7,
            only_inbox=True,
            pages=1,
            max_msgs=3,
            batch_size=2,
            dry_run=False,
        )
        consumer = FiltersSweepConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersSweepProcessor()
        envelope = processor.process(payload)
        producer = FiltersSweepProducer(
            payload.client,
            pages=payload.pages,
            batch_size=payload.batch_size,
            max_msgs=payload.max_msgs,
            dry_run=payload.dry_run,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertTrue(ctx.gmail_client.modified_batches)
        self.assertIn("Sweep complete. Modified", buf.getvalue())

    def test_sweep_pipeline_dry_run_outputs_summary(self):
        ctx = self._make_context(
            """
filters:
  - match:
      subject: Bar Report
    action:
      remove:
        - VIP
""",
            days=None,
            only_inbox=False,
            pages=2,
            max_msgs=None,
            batch_size=10,
            dry_run=True,
        )
        consumer = FiltersSweepConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersSweepProcessor()
        envelope = processor.process(payload)
        producer = FiltersSweepProducer(
            payload.client,
            pages=payload.pages,
            batch_size=payload.batch_size,
            max_msgs=payload.max_msgs,
            dry_run=payload.dry_run,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertFalse(ctx.gmail_client.modified_batches)
        out = buf.getvalue()
        self.assertIn("Query:", out)
        self.assertIn("Sweep complete. Modified", out)

    def test_sweep_range_pipeline_dry_run(self):
        ctx = self._make_context(
            """
filters:
  - match:
      from: foo@example.com
""",
            from_days=0,
            to_days=20,
            step_days=10,
            pages=1,
            max_msgs=5,
            batch_size=2,
            dry_run=True,
        )
        consumer = FiltersSweepRangeConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersSweepRangeProcessor()
        envelope = processor.process(payload)
        producer = FiltersSweepRangeProducer(
            payload.client,
            pages=payload.pages,
            batch_size=payload.batch_size,
            max_msgs=payload.max_msgs,
            dry_run=payload.dry_run,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("Window: newer_than:10d older_than:0d", out)
        self.assertIn("Total modified across windows", out)

    def test_sweep_range_pipeline_applies_batches(self):
        ctx = self._make_context(
            """
filters:
  - match:
      from: foo@example.com
""",
            from_days=0,
            to_days=15,
            step_days=5,
            pages=1,
            max_msgs=4,
            batch_size=2,
            dry_run=False,
        )
        consumer = FiltersSweepRangeConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersSweepRangeProcessor()
        envelope = processor.process(payload)
        producer = FiltersSweepRangeProducer(
            payload.client,
            pages=payload.pages,
            batch_size=payload.batch_size,
            max_msgs=payload.max_msgs,
            dry_run=payload.dry_run,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertTrue(ctx.gmail_client.modified_batches)
        self.assertIn("Total modified across windows", buf.getvalue())


class FiltersPruneProcessorTests(unittest.TestCase):
    def _make_context(self, *, dry_run: bool):
        args = SimpleNamespace(pages=2, days=None, only_inbox=False, dry_run=dry_run)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _make_pipeline_client()
        return ctx

    def test_prune_dry_run_outputs_plan(self):
        ctx = self._make_context(dry_run=True)
        consumer = FiltersPruneConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersPruneProcessor()
        envelope = processor.process(payload)
        producer = FiltersPruneProducer(payload.client, dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("Would delete filter id=EXTRA", out)
        self.assertIn("Prune complete. Examined:", out)

    def test_prune_executes_deletions(self):
        ctx = self._make_context(dry_run=False)
        consumer = FiltersPruneConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersPruneProcessor()
        envelope = processor.process(payload)
        producer = FiltersPruneProducer(payload.client, dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("Deleted filter id=EXTRA", out)
        self.assertIn("Prune complete. Examined:", out)
        self.assertIn("EXTRA", ctx.gmail_client.deleted_ids)


class FiltersAddForwardProcessorTests(unittest.TestCase):
    def _make_context(self, *, dry_run: bool, require_verified: bool = False, label_prefix: str = "Other"):
        args = SimpleNamespace(
            email="dest@example.com",
            label_prefix=label_prefix,
            dry_run=dry_run,
            require_forward_verified=require_verified,
        )
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _make_pipeline_client()
        return ctx

    def test_add_forward_dry_run(self):
        ctx = self._make_context(dry_run=True)
        consumer = FiltersAddForwardConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersAddForwardProcessor()
        envelope = processor.process(payload)
        producer = FiltersAddForwardProducer(payload.client, dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("Would update filter id=", out)

    def test_add_forward_requires_verified(self):
        ctx = self._make_context(dry_run=False, require_verified=True)
        consumer = FiltersAddForwardConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersAddForwardProcessor()
        envelope = processor.process(payload)
        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.diagnostics.get("code"), 2)

    def test_add_forward_executes(self):
        ctx = self._make_context(dry_run=False)
        consumer = FiltersAddForwardConsumer(ctx)
        payload = consumer.consume()
        processor = FiltersAddForwardProcessor()
        envelope = processor.process(payload)
        producer = FiltersAddForwardProducer(payload.client, dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("Updated filter id", out)


class FiltersAddTokenProcessorTests(unittest.TestCase):
    def _make_context(self, *, dry_run: bool, tokens: List[str]):
        args = SimpleNamespace(
            label_prefix="Other",
            needle="someone",
            add=tokens,
            dry_run=dry_run,
        )
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _make_pipeline_client()
        return ctx

    def test_add_token_dry_run(self):
        ctx = self._make_context(dry_run=True, tokens=["new@example.com"])
        payload = FiltersAddTokenConsumer(ctx).consume()
        envelope = FiltersAddTokenProcessor().process(payload)
        producer = FiltersAddTokenProducer(payload.client, dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Would update filter id=", buf.getvalue())

    def test_add_token_executes(self):
        ctx = self._make_context(dry_run=False, tokens=["new@example.com"])
        payload = FiltersAddTokenConsumer(ctx).consume()
        envelope = FiltersAddTokenProcessor().process(payload)
        producer = FiltersAddTokenProducer(payload.client, dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Updated filter id", buf.getvalue())


class FiltersRemoveTokenProcessorTests(unittest.TestCase):
    def _make_context(self, *, dry_run: bool, tokens: List[str]):
        args = SimpleNamespace(
            label_prefix="Other",
            needle="someone",
            remove=tokens,
            dry_run=dry_run,
        )
        ctx = MailContext.from_args(args)
        ctx.gmail_client = FakeGmailClient(
            labels=[
                {"id": "LBL_VIP", "name": "VIP"},
                {"id": "LBL_OTHER", "name": "Other"},
            ],
            filters=[
                {
                    "id": "EXTRA",
                    "criteria": {"from": "someone@example.com OR hello@example.com"},
                    "action": {"addLabelIds": ["LBL_OTHER"]},
                }
            ],
            verified_forward_addresses={"verified@example.com"},
        )
        return ctx

    def test_remove_token_dry_run(self):
        ctx = self._make_context(dry_run=True, tokens=["someone@example.com"])
        payload = FiltersRemoveTokenConsumer(ctx).consume()
        envelope = FiltersRemoveTokenProcessor().process(payload)
        producer = FiltersRemoveTokenProducer(payload.client, dry_run=True)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Would update filter id=", buf.getvalue())

    def test_remove_token_executes(self):
        ctx = self._make_context(dry_run=False, tokens=["someone@example.com"])
        payload = FiltersRemoveTokenConsumer(ctx).consume()
        envelope = FiltersRemoveTokenProcessor().process(payload)
        producer = FiltersRemoveTokenProducer(payload.client, dry_run=False)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertIn("Updated filter id", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
