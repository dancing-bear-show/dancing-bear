"""Tests for mail/auto/consumers.py consumer classes."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from mail.auto.consumers import (
    AutoProposeConsumer,
    AutoSummaryConsumer,
    AutoApplyConsumer,
    AutoProposePayload,
    AutoSummaryPayload,
    AutoApplyPayload,
)
from mail.context import MailContext


class TestAutoProposeConsumer(unittest.TestCase):
    """Tests for AutoProposeConsumer."""

    def test_creates_payload_with_context(self):
        args = SimpleNamespace(credentials=None, token=None, profile=None)
        ctx = MailContext.from_args(args)
        consumer = AutoProposeConsumer(
            context=ctx,
            out_path=Path("/tmp/test.json"),
            days=7,
            pages=5,
            protect=["friend@example.com"],
            dry_run=True,
            log_path="logs/test.jsonl",
        )

        payload = consumer.consume()

        self.assertIsInstance(payload, AutoProposePayload)
        self.assertEqual(payload.context, ctx)
        self.assertEqual(payload.out_path, Path("/tmp/test.json"))
        self.assertEqual(payload.days, 7)
        self.assertEqual(payload.pages, 5)
        self.assertEqual(payload.protect, ["friend@example.com"])
        self.assertTrue(payload.dry_run)
        self.assertEqual(payload.log_path, "logs/test.jsonl")


class TestAutoSummaryConsumer(unittest.TestCase):
    """Tests for AutoSummaryConsumer."""

    def test_loads_proposal_from_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            proposal = {"messages": [{"id": "m1", "reasons": ["list"]}]}
            json.dump(proposal, f)
            f.flush()
            proposal_path = Path(f.name)

        try:
            consumer = AutoSummaryConsumer(proposal_path=proposal_path)
            payload = consumer.consume()

            self.assertIsInstance(payload, AutoSummaryPayload)
            self.assertEqual(payload.proposal, proposal)
        finally:
            proposal_path.unlink()


class TestAutoApplyConsumer(unittest.TestCase):
    """Tests for AutoApplyConsumer."""

    def test_loads_proposal_and_creates_payload(self):
        args = SimpleNamespace(credentials=None, token=None, profile=None)
        ctx = MailContext.from_args(args)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            proposal = {
                "messages": [
                    {"id": "m1", "add": ["Lists/Newsletters"], "remove": ["INBOX"]},
                ]
            }
            json.dump(proposal, f)
            f.flush()
            proposal_path = Path(f.name)

        try:
            consumer = AutoApplyConsumer(
                context=ctx,
                proposal_path=proposal_path,
                cutoff_days=30,
                batch_size=100,
                dry_run=True,
                log_path="logs/apply.jsonl",
            )
            payload = consumer.consume()

            self.assertIsInstance(payload, AutoApplyPayload)
            self.assertEqual(payload.context, ctx)
            self.assertEqual(payload.proposal, proposal)
            self.assertEqual(payload.cutoff_days, 30)
            self.assertEqual(payload.batch_size, 100)
            self.assertTrue(payload.dry_run)
            self.assertEqual(payload.log_path, "logs/apply.jsonl")
        finally:
            proposal_path.unlink()


if __name__ == "__main__":
    unittest.main()
