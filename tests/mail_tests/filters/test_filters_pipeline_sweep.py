"""Tests for filters pipeline — sweep, prune, add-forward, add-token, rm-token processors."""

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
    FiltersSweepConsumer,
    FiltersSweepRangeConsumer,
    FiltersPruneConsumer,
    FiltersAddForwardConsumer,
    FiltersAddTokenConsumer,
    FiltersRemoveTokenConsumer,
)
from mail.filters.processors_sweep import (
    FiltersSweepProcessor,
    FiltersSweepRangeProcessor,
    FiltersPruneProcessor,
    FiltersAddForwardProcessor,
    FiltersAddTokenProcessor,
    FiltersRemoveTokenProcessor,
)
from mail.filters.producers import (
    FiltersSweepProducer,
    FiltersSweepRangeProducer,
    FiltersPruneProducer,
    FiltersAddForwardProducer,
    FiltersAddTokenProducer,
    FiltersRemoveTokenProducer,
)

from tests.mail_tests.fixtures import FakeGmailClient, make_pipeline_client


class FiltersSweepProcessorTests(unittest.TestCase):
    def _make_context(self, data: str, **flags):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        cfg_path = Path(tmpdir.name) / "filters.yaml"
        cfg_path.write_text(data)
        args = SimpleNamespace(config=str(cfg_path), **flags)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = make_pipeline_client()
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
        producer = FiltersSweepProducer(payload.client, payload.producer_config)
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
        producer = FiltersSweepProducer(payload.client, payload.producer_config)
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
        producer = FiltersSweepRangeProducer(payload.client, payload.producer_config)
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
        producer = FiltersSweepRangeProducer(payload.client, payload.producer_config)
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.produce(envelope)
        self.assertTrue(ctx.gmail_client.modified_batches)
        self.assertIn("Total modified across windows", buf.getvalue())


class FiltersPruneProcessorTests(unittest.TestCase):
    def _make_context(self, *, dry_run: bool):
        args = SimpleNamespace(pages=2, days=None, only_inbox=False, dry_run=dry_run)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = make_pipeline_client()
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
        ctx.gmail_client = make_pipeline_client()
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
        ctx.gmail_client = make_pipeline_client()
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
