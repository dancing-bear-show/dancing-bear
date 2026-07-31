"""Tests for new SafeProcessor pairs introduced in normalize-domains.

Covers C8/C9 gaps for:
  - SpotPriceProcessor / SpotPriceProducer
  - GmailCostsProcessor / GmailCostsProducer
  - OutlookCostsProcessor / OutlookCostsProducer
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from metals.pipeline import (
    GmailCostsProcessor,
    GmailCostsProducer,
    GmailCostsRequest,
    GmailCostsResult,
    OutlookCostsProcessor,
    OutlookCostsProducer,
    OutlookCostsRequest,
    OutlookCostsResult,
    SpotPriceProcessor,
    SpotPriceProducer,
    SpotPriceRequest,
    SpotPriceResult,
)
from core.pipeline import ResultEnvelope


# ---------------------------------------------------------------------------
# SpotPriceProcessor
# ---------------------------------------------------------------------------

class TestSpotPriceProcessor(unittest.TestCase):
    """Happy-path and sad-path tests for SpotPriceProcessor."""

    @patch("metals.spot._build_csv_rows")
    @patch("metals.spot._fetch_series_with_fallback")
    @patch("metals.spot._today_iso")
    @patch("metals.spot._auto_start_date")
    def test_process_safe_happy_path(
        self,
        mock_auto_start,
        mock_today,
        mock_fetch,
        mock_build_rows,
    ):
        """Consumer → processor → producer: spot fetch writes CSV and surfaces result."""
        mock_auto_start.return_value = "2024-01-01"
        mock_today.return_value = "2024-06-01"
        mock_fetch.return_value = ({"2024-01-01": 2000.0}, {"2024-01-01": 1.35})
        # header row + 3 data rows
        mock_build_rows.return_value = [
            ["date", "price_usd", "price_cad"],
            ["2024-01-01", "2000.0", "2700.0"],
            ["2024-01-02", "2010.0", "2713.5"],
            ["2024-01-03", "2020.0", "2727.0"],
        ]

        with tempfile.TemporaryDirectory() as tmp:
            out_path = os.path.join(tmp, "gold_spot.csv")
            request = SpotPriceRequest(
                metal="gold",
                start_date="2024-01-01",
                end_date="2024-06-01",
                out_path=out_path,
            )
            processor = SpotPriceProcessor()
            envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        self.assertIsNotNone(envelope.payload)
        self.assertIsInstance(envelope.payload, SpotPriceResult)
        self.assertEqual(envelope.payload.metal, "gold")
        # row_count = len(rows) - 1 (header excluded)
        self.assertEqual(envelope.payload.row_count, 3)
        self.assertEqual(envelope.payload.window, "2024-01-01..2024-06-01")
        mock_fetch.assert_called_once_with("gold", "2024-01-01", "2024-06-01")

    @patch("metals.spot._fetch_series_with_fallback")
    @patch("metals.spot._today_iso")
    @patch("metals.spot._auto_start_date")
    def test_process_safe_fetch_error_surfaces_as_failed_envelope(
        self,
        mock_auto_start,
        mock_today,
        mock_fetch,
    ):
        """A network/data error inside _process_safe returns a failed envelope."""
        mock_auto_start.return_value = "2024-01-01"
        mock_today.return_value = "2024-06-01"
        mock_fetch.side_effect = RuntimeError("upstream API unavailable")

        request = SpotPriceRequest(metal="gold")
        processor = SpotPriceProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn(
            "upstream API unavailable",
            (envelope.diagnostics or {}).get("message", ""),
        )


# ---------------------------------------------------------------------------
# SpotPriceProducer
# ---------------------------------------------------------------------------

class TestSpotPriceProducer(unittest.TestCase):
    """Happy-path and sad-path output tests for SpotPriceProducer."""

    def test_produce_success_writes_expected_line(self):
        """Successful envelope causes producer to emit expected line via writer."""
        mock_writer = MagicMock()
        producer = SpotPriceProducer(writer=mock_writer)
        payload = SpotPriceResult(
            metal="gold",
            out_path="out/metals/gold_spot.csv",
            row_count=5,
            window="2024-01-01..2024-06-01",
        )
        envelope = ResultEnvelope(status="success", payload=payload)

        producer.produce(envelope)

        mock_writer.print.assert_called_once_with(
            "wrote out/metals/gold_spot.csv rows=5 window=2024-01-01..2024-06-01"
        )

    def test_produce_error_writes_error_message(self):
        """Failed envelope causes producer to emit the error message via writer."""
        mock_writer = MagicMock()
        producer = SpotPriceProducer(writer=mock_writer)
        envelope = ResultEnvelope(
            status="error",
            diagnostics={"message": "fetch failed"},
        )

        producer.produce(envelope)

        mock_writer.print_error.assert_called_once_with("fetch failed")
        mock_writer.print.assert_not_called()


# ---------------------------------------------------------------------------
# GmailCostsProcessor
# ---------------------------------------------------------------------------

class TestGmailCostsProcessor(unittest.TestCase):
    """Happy-path and sad-path tests for GmailCostsProcessor."""

    @patch("metals.gmail_costs_extract.GmailCostExtractor")
    def test_process_safe_happy_path(self, mock_extractor_cls):
        """Consumer → processor → producer: gmail costs extraction delegates to extractor."""
        mock_extractor = MagicMock()
        mock_extractor.run.return_value = 0
        mock_extractor_cls.return_value = mock_extractor

        request = GmailCostsRequest(
            profile="gmail_personal",
            out_path="out/metals/costs.csv",
        )
        processor = GmailCostsProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        self.assertIsNotNone(envelope.payload)
        self.assertIsInstance(envelope.payload, GmailCostsResult)
        self.assertEqual(envelope.payload.out_path, "out/metals/costs.csv")
        mock_extractor_cls.assert_called_once_with(
            profile="gmail_personal",
            out_path="out/metals/costs.csv",
            days=365,
        )
        mock_extractor.run.assert_called_once()

    @patch("metals.gmail_costs_extract.GmailCostExtractor")
    def test_process_safe_extractor_error_surfaces_as_failed_envelope(
        self, mock_extractor_cls
    ):
        """An exception from the extractor returns a failed envelope."""
        mock_extractor = MagicMock()
        mock_extractor.run.side_effect = Exception("Gmail auth failed")
        mock_extractor_cls.return_value = mock_extractor

        request = GmailCostsRequest()
        processor = GmailCostsProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn(
            "Gmail auth failed",
            (envelope.diagnostics or {}).get("message", ""),
        )


# ---------------------------------------------------------------------------
# GmailCostsProducer
# ---------------------------------------------------------------------------

class TestGmailCostsProducer(unittest.TestCase):
    """Happy-path and sad-path output tests for GmailCostsProducer."""

    def test_produce_success_writes_expected_line(self):
        """Successful envelope causes producer to emit expected line via writer."""
        mock_writer = MagicMock()
        producer = GmailCostsProducer(writer=mock_writer)
        payload = GmailCostsResult(out_path="out/metals/costs.csv", row_count=7)
        envelope = ResultEnvelope(status="success", payload=payload)

        producer.produce(envelope)

        mock_writer.print.assert_called_once_with("wrote out/metals/costs.csv rows=7")

    def test_produce_error_writes_error_message(self):
        """Failed envelope causes producer to emit the error message via writer."""
        mock_writer = MagicMock()
        producer = GmailCostsProducer(writer=mock_writer)
        envelope = ResultEnvelope(
            status="error",
            diagnostics={"message": "credential load error"},
        )

        producer.produce(envelope)

        mock_writer.print_error.assert_called_once_with("credential load error")
        mock_writer.print.assert_not_called()


# ---------------------------------------------------------------------------
# OutlookCostsProcessor
# ---------------------------------------------------------------------------

class TestOutlookCostsProcessor(unittest.TestCase):
    """Happy-path and sad-path tests for OutlookCostsProcessor."""

    @patch("metals.outlook_costs.run")
    def test_process_safe_happy_path(self, mock_costs_run):
        """Consumer → processor → producer: outlook costs extraction delegates to run()."""
        mock_costs_run.return_value = 0

        request = OutlookCostsRequest(
            profile="outlook_personal",
            out_path="out/metals/costs.csv",
        )
        processor = OutlookCostsProcessor()
        envelope = processor.process(request)

        self.assertTrue(envelope.ok())
        self.assertIsNotNone(envelope.payload)
        self.assertIsInstance(envelope.payload, OutlookCostsResult)
        self.assertEqual(envelope.payload.out_path, "out/metals/costs.csv")
        mock_costs_run.assert_called_once_with(
            profile="outlook_personal",
            out_path="out/metals/costs.csv",
        )

    @patch("metals.outlook_costs.run")
    def test_process_safe_run_error_surfaces_as_failed_envelope(self, mock_costs_run):
        """An exception from the underlying run() returns a failed envelope."""
        mock_costs_run.side_effect = Exception("Outlook token expired")

        request = OutlookCostsRequest()
        processor = OutlookCostsProcessor()
        envelope = processor.process(request)

        self.assertFalse(envelope.ok())
        self.assertIn(
            "Outlook token expired",
            (envelope.diagnostics or {}).get("message", ""),
        )


# ---------------------------------------------------------------------------
# OutlookCostsProducer
# ---------------------------------------------------------------------------

class TestOutlookCostsProducer(unittest.TestCase):
    """Happy-path and sad-path output tests for OutlookCostsProducer."""

    def test_produce_success_writes_expected_line(self):
        """Successful envelope causes producer to emit expected line via writer."""
        mock_writer = MagicMock()
        producer = OutlookCostsProducer(writer=mock_writer)
        payload = OutlookCostsResult(out_path="out/metals/costs.csv", row_count=3)
        envelope = ResultEnvelope(status="success", payload=payload)

        producer.produce(envelope)

        mock_writer.print.assert_called_once_with("wrote out/metals/costs.csv rows=3")

    def test_produce_error_writes_error_message(self):
        """Failed envelope causes producer to emit the error message via writer."""
        mock_writer = MagicMock()
        producer = OutlookCostsProducer(writer=mock_writer)
        envelope = ResultEnvelope(
            status="error",
            diagnostics={"message": "Outlook token expired"},
        )

        producer.produce(envelope)

        mock_writer.print_error.assert_called_once_with("Outlook token expired")
        mock_writer.print.assert_not_called()


if __name__ == "__main__":
    unittest.main()
