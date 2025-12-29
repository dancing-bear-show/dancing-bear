"""Tests for mail/auto/producers.py auto pipeline producers."""

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from core.pipeline import ResultEnvelope
from mail.auto.processors import AutoProposeResult, AutoSummaryResult, AutoApplyResult
from mail.auto.producers import AutoProposeProducer, AutoSummaryProducer, AutoApplyProducer


class TestAutoProposeProducer(unittest.TestCase):
    """Tests for AutoProposeProducer."""

    def test_produce_success_output(self):
        payload = AutoProposeResult(
            out_path=Path("/tmp/proposal.json"),
            total_considered=100,
            selected_count=25,
            query="in:inbox newer_than:7d",
        )
        result = ResultEnvelope(status="success", payload=payload)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoProposeProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("/tmp/proposal.json", output)
        self.assertIn("25", output)
        self.assertIn("100", output)

    def test_produce_error_output(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Connection failed"},
        )

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoProposeProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Error:", output)
        self.assertIn("Connection failed", output)

    def test_produce_error_without_diagnostics(self):
        result = ResultEnvelope(status="error", payload=None)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoProposeProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Error:", output)
        self.assertIn("Auto propose failed", output)


class TestAutoSummaryProducer(unittest.TestCase):
    """Tests for AutoSummaryProducer."""

    def test_produce_success_output(self):
        payload = AutoSummaryResult(
            message_count=50,
            reasons={"list": 30, "category:promotions": 15, "bulk": 5},
            label_adds={"Lists/Commercial": 20, "Lists/Newsletters": 30},
        )
        result = ResultEnvelope(status="success", payload=payload)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoSummaryProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Messages: 50", output)
        self.assertIn("Top reasons:", output)
        self.assertIn("list: 30", output)
        self.assertIn("Label adds:", output)
        self.assertIn("Lists/Commercial: 20", output)

    def test_produce_success_with_empty_reasons(self):
        payload = AutoSummaryResult(
            message_count=0,
            reasons={},
            label_adds={},
        )
        result = ResultEnvelope(status="success", payload=payload)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoSummaryProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Messages: 0", output)
        self.assertIn("Top reasons:", output)
        self.assertIn("Label adds:", output)

    def test_produce_error_output(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Invalid proposal format"},
        )

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoSummaryProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Error:", output)
        self.assertIn("Invalid proposal format", output)

    def test_produce_error_without_diagnostics(self):
        result = ResultEnvelope(status="error", payload=None)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoSummaryProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Error:", output)
        self.assertIn("Auto summary failed", output)


class TestAutoApplyProducer(unittest.TestCase):
    """Tests for AutoApplyProducer."""

    def test_produce_success_apply_output(self):
        payload = AutoApplyResult(
            total_modified=75,
            dry_run=False,
            groups=[
                (50, ["Label/A"], ["INBOX"]),
                (25, ["Label/B"], ["INBOX"]),
            ],
        )
        result = ResultEnvelope(status="success", payload=payload)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoApplyProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Applied to 75 messages", output)

    def test_produce_success_dry_run_output(self):
        payload = AutoApplyResult(
            total_modified=100,
            dry_run=True,
            groups=[
                (60, ["Lists/Commercial"], ["INBOX"]),
                (40, ["Lists/Newsletters"], ["INBOX"]),
            ],
        )
        result = ResultEnvelope(status="success", payload=payload)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoApplyProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Would modify 60 messages", output)
        self.assertIn("Would modify 40 messages", output)
        self.assertIn("Applied to 100 messages", output)

    def test_produce_success_empty_groups(self):
        payload = AutoApplyResult(
            total_modified=0,
            dry_run=False,
            groups=[],
        )
        result = ResultEnvelope(status="success", payload=payload)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoApplyProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Applied to 0 messages", output)

    def test_produce_error_output(self):
        result = ResultEnvelope(
            status="error",
            payload=None,
            diagnostics={"error": "Authentication failed"},
        )

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoApplyProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Error:", output)
        self.assertIn("Authentication failed", output)

    def test_produce_error_without_diagnostics(self):
        result = ResultEnvelope(status="error", payload=None)

        buf = io.StringIO()
        with redirect_stdout(buf):
            AutoApplyProducer().produce(result)

        output = buf.getvalue()
        self.assertIn("Error:", output)
        self.assertIn("Auto apply failed", output)


if __name__ == "__main__":
    unittest.main()
