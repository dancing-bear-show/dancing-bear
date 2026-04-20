"""Tests for mail/auto/consumers.py consumer pipeline classes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from mail.auto.consumers import (
    AutoApplyConsumer,
    AutoApplyPayload,
    AutoProposeConsumer,
    AutoProposePayload,
    AutoSummaryConsumer,
    AutoSummaryPayload,
)
from tests.mail_tests.fixtures import make_mock_mail_context


class TestAutoProposeConsumer(unittest.TestCase):
    """Tests for AutoProposeConsumer."""

    def _make_context(self):
        return make_mock_mail_context()

    def test_consume_returns_auto_propose_payload(self):
        ctx = self._make_context()
        out_path = Path("/tmp/proposal.json")  # nosec B108 - test-only path
        consumer = AutoProposeConsumer(
            context=ctx,
            out_path=out_path,
            days=7,
            pages=5,
        )
        payload = consumer.consume()
        self.assertIsInstance(payload, AutoProposePayload)

    def test_consume_sets_context(self):
        ctx = self._make_context()
        consumer = AutoProposeConsumer(
            context=ctx,
            out_path=Path("/tmp/proposal.json"),  # nosec B108 - test-only path
            days=7,
            pages=5,
        )
        payload = consumer.consume()
        self.assertIs(payload.context, ctx)

    def test_consume_sets_out_path(self):
        ctx = self._make_context()
        out_path = Path("/tmp/my_proposal.json")  # nosec B108 - test-only path
        consumer = AutoProposeConsumer(context=ctx, out_path=out_path, days=3, pages=2)
        payload = consumer.consume()
        self.assertEqual(payload.out_path, out_path)

    def test_consume_sets_days_and_pages(self):
        ctx = self._make_context()
        consumer = AutoProposeConsumer(
            context=ctx,
            out_path=Path("/tmp/p.json"),  # nosec B108 - test-only path
            days=14,
            pages=10,
        )
        payload = consumer.consume()
        self.assertEqual(payload.days, 14)
        self.assertEqual(payload.pages, 10)

    def test_consume_forwards_kwargs(self):
        ctx = self._make_context()
        protect = ["boss@example.com"]
        consumer = AutoProposeConsumer(
            context=ctx,
            out_path=Path("/tmp/p.json"),  # nosec B108 - test-only path
            days=7,
            pages=5,
            protect=protect,
            dry_run=True,
            log_path="logs/test.jsonl",
        )
        payload = consumer.consume()
        self.assertEqual(payload.protect, protect)
        self.assertTrue(payload.dry_run)
        self.assertEqual(payload.log_path, "logs/test.jsonl")

    def test_consume_uses_payload_defaults(self):
        ctx = self._make_context()
        consumer = AutoProposeConsumer(
            context=ctx,
            out_path=Path("/tmp/p.json"),  # nosec B108 - test-only path
            days=7,
            pages=5,
        )
        payload = consumer.consume()
        self.assertEqual(payload.protect, [])
        self.assertFalse(payload.dry_run)
        self.assertEqual(payload.log_path, "logs/auto_runs.jsonl")


class TestAutoSummaryConsumer(unittest.TestCase):
    """Tests for AutoSummaryConsumer."""

    def _write_proposal(self, data: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(data, tmp)
        tmp.close()
        return Path(tmp.name)

    def test_consume_returns_auto_summary_payload(self):
        proposal = {"messages": [{"id": "m1", "reasons": ["list"]}]}
        path = self._write_proposal(proposal)
        consumer = AutoSummaryConsumer(proposal_path=path)
        payload = consumer.consume()
        self.assertIsInstance(payload, AutoSummaryPayload)

    def test_consume_reads_proposal_from_file(self):
        proposal = {"messages": [{"id": "m1"}, {"id": "m2"}]}
        path = self._write_proposal(proposal)
        consumer = AutoSummaryConsumer(proposal_path=path)
        payload = consumer.consume()
        self.assertEqual(payload.proposal, proposal)

    def test_consume_reads_empty_proposal(self):
        proposal = {"messages": []}
        path = self._write_proposal(proposal)
        consumer = AutoSummaryConsumer(proposal_path=path)
        payload = consumer.consume()
        self.assertEqual(payload.proposal["messages"], [])

    def test_consume_stores_path_on_init(self):
        path = Path("/tmp/unused.json")  # nosec B108 - test-only path
        consumer = AutoSummaryConsumer(proposal_path=path)
        self.assertEqual(consumer._proposal_path, path)


class TestAutoApplyConsumer(unittest.TestCase):
    """Tests for AutoApplyConsumer."""

    def _make_context(self):
        return make_mock_mail_context()

    def _write_proposal(self, data: dict) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(data, tmp)
        tmp.close()
        return Path(tmp.name)

    def test_consume_returns_auto_apply_payload(self):
        ctx = self._make_context()
        proposal = {"messages": [{"id": "m1", "add": ["Lists/Newsletters"], "remove": ["INBOX"]}]}
        path = self._write_proposal(proposal)
        consumer = AutoApplyConsumer(context=ctx, proposal_path=path)
        payload = consumer.consume()
        self.assertIsInstance(payload, AutoApplyPayload)

    def test_consume_sets_context(self):
        ctx = self._make_context()
        proposal = {"messages": []}
        path = self._write_proposal(proposal)
        consumer = AutoApplyConsumer(context=ctx, proposal_path=path)
        payload = consumer.consume()
        self.assertIs(payload.context, ctx)

    def test_consume_reads_proposal_from_file(self):
        ctx = self._make_context()
        proposal = {"messages": [{"id": "m1"}, {"id": "m2"}]}
        path = self._write_proposal(proposal)
        consumer = AutoApplyConsumer(context=ctx, proposal_path=path)
        payload = consumer.consume()
        self.assertEqual(payload.proposal, proposal)

    def test_consume_forwards_kwargs(self):
        ctx = self._make_context()
        proposal = {"messages": []}
        path = self._write_proposal(proposal)
        consumer = AutoApplyConsumer(
            context=ctx,
            proposal_path=path,
            cutoff_days=30,
            batch_size=100,
            dry_run=True,
            log_path="logs/custom.jsonl",
        )
        payload = consumer.consume()
        self.assertEqual(payload.cutoff_days, 30)
        self.assertEqual(payload.batch_size, 100)
        self.assertTrue(payload.dry_run)
        self.assertEqual(payload.log_path, "logs/custom.jsonl")

    def test_consume_uses_payload_defaults(self):
        ctx = self._make_context()
        proposal = {"messages": []}
        path = self._write_proposal(proposal)
        consumer = AutoApplyConsumer(context=ctx, proposal_path=path)
        payload = consumer.consume()
        self.assertIsNone(payload.cutoff_days)
        self.assertEqual(payload.batch_size, 500)
        self.assertFalse(payload.dry_run)
        self.assertEqual(payload.log_path, "logs/auto_runs.jsonl")

    def test_consume_stores_context_and_path_on_init(self):
        ctx = self._make_context()
        path = Path("/tmp/unused.json")  # nosec B108 - test-only path
        consumer = AutoApplyConsumer(context=ctx, proposal_path=path)
        self.assertIs(consumer._context, ctx)
        self.assertEqual(consumer._proposal_path, path)


if __name__ == "__main__":
    unittest.main()
