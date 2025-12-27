"""Tests for metals pipeline module."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from metals.pipeline import (
    ExtractRequest,
    ExtractResult,
    SpotPriceRequest,
    SpotPrice,
    SpotPriceResult,
    PremiumRequest,
    PremiumResult,
    GmailExtractProcessor,
    OutlookExtractProcessor,
    ExtractProducer,
    Result,
)
from metals.extractors import MetalsAmount, OrderExtraction


class TestExtractRequest(unittest.TestCase):
    """Tests for ExtractRequest dataclass."""

    def test_defaults(self):
        """Test default values."""
        req = ExtractRequest()
        self.assertEqual(req.profile, "gmail_personal")
        self.assertEqual(req.days, 365)
        self.assertEqual(req.provider, "gmail")

    def test_custom_values(self):
        """Test custom values."""
        req = ExtractRequest(profile="work", days=30, provider="outlook")
        self.assertEqual(req.profile, "work")
        self.assertEqual(req.days, 30)
        self.assertEqual(req.provider, "outlook")


class TestExtractResult(unittest.TestCase):
    """Tests for ExtractResult dataclass."""

    def test_creation(self):
        """Test result creation."""
        total = MetalsAmount(gold_oz=1.0, silver_oz=10.0)
        orders = [
            OrderExtraction(
                order_id="123",
                message_id="msg1",
                gold_oz=1.0,
                silver_oz=10.0,
            )
        ]
        result = ExtractResult(total=total, orders=orders, message_count=1)
        self.assertEqual(result.total.gold_oz, 1.0)
        self.assertEqual(result.total.silver_oz, 10.0)
        self.assertEqual(len(result.orders), 1)
        self.assertEqual(result.message_count, 1)


class TestSpotPriceDataclasses(unittest.TestCase):
    """Tests for spot price dataclasses."""

    def test_spot_price_request(self):
        """Test SpotPriceRequest."""
        req = SpotPriceRequest(metal="gold", start_date="2024-01-01")
        self.assertEqual(req.metal, "gold")
        self.assertEqual(req.start_date, "2024-01-01")
        self.assertIsNone(req.end_date)

    def test_spot_price(self):
        """Test SpotPrice."""
        price = SpotPrice(date="2024-01-01", price_usd=2000.0, price_cad=2700.0)
        self.assertEqual(price.date, "2024-01-01")
        self.assertEqual(price.price_usd, 2000.0)
        self.assertEqual(price.price_cad, 2700.0)

    def test_spot_price_result(self):
        """Test SpotPriceResult."""
        prices = [SpotPrice(date="2024-01-01", price_usd=2000.0, price_cad=2700.0)]
        result = SpotPriceResult(metal="gold", prices=prices)
        self.assertEqual(result.metal, "gold")
        self.assertEqual(len(result.prices), 1)


class TestPremiumDataclasses(unittest.TestCase):
    """Tests for premium dataclasses."""

    def test_premium_request(self):
        """Test PremiumRequest."""
        req = PremiumRequest()
        self.assertEqual(req.costs_path, "out/metals/costs.csv")
        self.assertEqual(req.spot_dir, "out/metals")

    def test_premium_result(self):
        """Test PremiumResult."""
        result = PremiumResult(metal="gold", avg_premium_pct=5.5)
        self.assertEqual(result.metal, "gold")
        self.assertEqual(result.avg_premium_pct, 5.5)
        self.assertEqual(result.orders, [])


class TestGmailExtractProcessor(unittest.TestCase):
    """Tests for GmailExtractProcessor."""

    @patch("mail.gmail_api.GmailClient")
    @patch("mail.config_resolver.resolve_paths_profile")
    def test_process_success(self, mock_resolve, mock_client_class):
        """Test successful extraction."""
        mock_resolve.return_value = ("cred.json", "token.json")
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.list_message_ids.return_value = ["msg1"]
        mock_client.get_message.return_value = {
            "id": "msg1",
            "internalDate": "1704067200000",
        }
        mock_client_class.headers_to_dict.return_value = {"subject": "Order #123456"}
        mock_client.get_message_text.return_value = "1 oz Gold x 2"

        processor = GmailExtractProcessor()
        request = ExtractRequest(profile="test", days=30, provider="gmail")
        result = processor.process(request)

        self.assertTrue(result.ok())
        self.assertIsNotNone(result.payload)
        self.assertEqual(result.payload.total.gold_oz, 2.0)

    @patch("mail.config_resolver.resolve_paths_profile")
    def test_process_auth_error(self, mock_resolve):
        """Test handling of authentication error."""
        mock_resolve.side_effect = Exception("Auth failed")

        processor = GmailExtractProcessor()
        request = ExtractRequest()
        result = processor.process(request)

        self.assertFalse(result.ok())
        self.assertIn("Auth failed", result.error)


class TestOutlookExtractProcessor(unittest.TestCase):
    """Tests for OutlookExtractProcessor."""

    @patch("mail.outlook_api.OutlookClient")
    @patch("core.auth.resolve_outlook_credentials")
    def test_process_success(self, mock_resolve, mock_client_class):
        """Test successful extraction."""
        mock_resolve.return_value = ("client_id", "tenant", "token.json")
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.search_messages.return_value = [
            {
                "id": "msg1",
                "subject": "Order #123456",
                "body": {"content": "1 oz Silver x 5"},
                "receivedDateTime": "2024-01-01T00:00:00Z",
            }
        ]

        processor = OutlookExtractProcessor()
        request = ExtractRequest(profile="test", days=30, provider="outlook")
        result = processor.process(request)

        self.assertTrue(result.ok())
        self.assertIsNotNone(result.payload)
        self.assertEqual(result.payload.total.silver_oz, 5.0)

    @patch("core.auth.resolve_outlook_credentials")
    def test_process_missing_credentials(self, mock_resolve):
        """Test handling of missing credentials."""
        mock_resolve.return_value = (None, None, None)

        processor = OutlookExtractProcessor()
        request = ExtractRequest()
        result = processor.process(request)

        self.assertFalse(result.ok())
        self.assertIn("Missing", result.error)

    @patch("mail.outlook_api.OutlookClient")
    @patch("core.auth.resolve_outlook_credentials")
    def test_process_search_error(self, mock_resolve, mock_client_class):
        """Test handling of search error."""
        mock_resolve.return_value = ("client_id", "tenant", "token.json")
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_client.search_messages.side_effect = Exception("Search failed")

        processor = OutlookExtractProcessor()
        request = ExtractRequest()
        result = processor.process(request)

        self.assertFalse(result.ok())
        self.assertIn("Search failed", result.error)


class TestExtractProducer(unittest.TestCase):
    """Tests for ExtractProducer."""

    def test_produce_error(self):
        """Test producing error result."""
        producer = ExtractProducer()
        result = Result[ExtractResult](error="Test error")
        # Should not raise
        producer.produce(result)

    def test_produce_success(self):
        """Test producing success result."""
        producer = ExtractProducer()
        payload = ExtractResult(
            total=MetalsAmount(gold_oz=1.0, silver_oz=10.0),
            orders=[
                OrderExtraction(
                    order_id="123",
                    message_id="msg1",
                    gold_oz=1.0,
                    silver_oz=10.0,
                )
            ],
            message_count=1,
        )
        result = Result[ExtractResult](payload=payload)
        # Should not raise
        producer.produce(result)

    def test_produce_empty_orders(self):
        """Test producing result with no orders."""
        producer = ExtractProducer()
        payload = ExtractResult(
            total=MetalsAmount(),
            orders=[],
            message_count=0,
        )
        result = Result[ExtractResult](payload=payload)
        # Should not raise
        producer.produce(result)


if __name__ == "__main__":
    unittest.main()
