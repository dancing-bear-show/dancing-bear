"""Tests for CostExtractor base class, MessageInfo and OrderData dataclasses."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from metals.cost_extractor import CostExtractor, MessageInfo, OrderData
from tests.metals_tests.fixtures import make_message_info


class MockCostExtractor(CostExtractor):
    """Mock implementation for testing base class."""

    def __init__(self, profile: str, out_path: str, days: int = 365):
        super().__init__(profile, out_path, days)
        self.authenticated = False
        self.fetched_ids = []
        self.processed_orders = []

    def _authenticate(self) -> None:
        self.authenticated = True

    def _fetch_message_ids(self):
        return self.fetched_ids

    def _get_message_info(self, msg_id: str) -> MessageInfo:
        return make_message_info(
            msg_id=msg_id,
            subject=f"Subject {msg_id}",
            from_header="test@example.com",
            body_text=f"Body {msg_id}",
            received_date="2024-01-15"
        )

    def _extract_order_id(self, msg: MessageInfo) -> str | None:
        if msg.msg_id.startswith("ord"):
            order_id = msg.msg_id.replace("msg", "order")
            order_id = order_id.replace("-dup", "")
            return order_id
        return None

    def _select_best_message(self, messages):
        return messages[0] if messages else None

    def _process_order_to_rows(self, order: OrderData):
        self.processed_orders.append(order.order_id)
        return [{"order_id": order.order_id, "vendor": order.vendor}]


class TestCostExtractorBaseClass(unittest.TestCase):
    """Tests for CostExtractor base class template method pattern."""

    def test_run_orchestrates_workflow(self):
        """Test run() orchestrates the full workflow."""
        extractor = MockCostExtractor("test", "out/test.csv")
        extractor.fetched_ids = ["ord-msg1", "ord-msg2"]

        with patch("metals.cost_extractor.merge_costs_csv") as mock_merge:
            result = extractor.run()
            self.assertTrue(extractor.authenticated)
            self.assertEqual(result, 0)
            mock_merge.assert_called_once()
            args, _ = mock_merge.call_args
            rows = args[1]
            self.assertEqual(len(rows), 2)

    def test_run_returns_one_when_no_messages(self):
        """Test run() returns 1 when no messages found."""
        extractor = MockCostExtractor("test", "out/test.csv")
        extractor.fetched_ids = []
        result = extractor.run()
        self.assertEqual(result, 1)
        self.assertTrue(extractor.authenticated)

    def test_run_returns_one_when_no_orders(self):
        """Test run() returns 1 when no orders extracted."""
        extractor = MockCostExtractor("test", "out/test.csv")
        extractor.fetched_ids = ["msg1", "msg2"]
        result = extractor.run()
        self.assertEqual(result, 1)
        self.assertEqual(len(extractor.processed_orders), 0)

    def test_group_by_order_groups_messages(self):
        """Test _group_by_order groups messages by order ID."""
        extractor = MockCostExtractor("test", "out/test.csv")
        extractor.fetched_ids = ["ord-msg1", "ord-msg2", "ord-msg1-dup"]
        by_order = extractor._group_by_order(extractor.fetched_ids)
        self.assertEqual(len(by_order), 2)
        self.assertIn("ord-order1", by_order)
        self.assertIn("ord-order2", by_order)
        self.assertEqual(len(by_order["ord-order1"]), 2)

    def test_build_order_data_selects_best_message(self):
        """Test _build_order_data selects best message."""
        extractor = MockCostExtractor("test", "out/test.csv")
        messages = [
            make_message_info(msg_id="msg1", subject="Subject 1", from_header="test@ex.com", body_text="Body 1", received_date="2024-01-15"),
            make_message_info(msg_id="msg2", subject="Subject 2", from_header="test@ex.com", body_text="Body 2", received_date="2024-01-16"),
        ]
        order_data = extractor._build_order_data("ORD123", messages)
        self.assertEqual(order_data.order_id, "ORD123")
        self.assertEqual(len(order_data.messages), 2)
        self.assertEqual(order_data.vendor, "Unknown")

    def test_classify_vendor_returns_unknown_by_default(self):
        """Test _classify_vendor returns Unknown by default."""
        extractor = MockCostExtractor("test", "out/test.csv")
        vendor = extractor._classify_vendor("unknown@example.com")
        self.assertEqual(vendor, "Unknown")

    def test_run_returns_one_when_orders_found_but_no_cost_rows(self):
        """Test run() returns 1 when orders produce no cost rows."""
        class EmptyRowsExtractor(MockCostExtractor):
            def _process_order_to_rows(self, order: OrderData):
                self.processed_orders.append(order.order_id)
                return []

        extractor = EmptyRowsExtractor("test", "out/test.csv")
        extractor.fetched_ids = ["ord-msg1", "ord-msg2"]

        with patch("metals.cost_extractor.merge_costs_csv") as mock_merge:
            result = extractor.run()
            self.assertEqual(result, 1)
            mock_merge.assert_not_called()
            self.assertEqual(len(extractor.processed_orders), 2)


class TestMessageInfo(unittest.TestCase):
    """Tests for MessageInfo dataclass."""

    def test_message_info_creation(self):
        """Test MessageInfo can be created."""
        msg = make_message_info(
            msg_id="msg123", subject="Test Subject", from_header="test@example.com",
            body_text="Test body", received_date="2024-01-15"
        )
        self.assertEqual(msg.msg_id, "msg123")
        self.assertEqual(msg.subject, "Test Subject")
        self.assertEqual(msg.from_header, "test@example.com")
        self.assertEqual(msg.body_text, "Test body")
        self.assertEqual(msg.received_date, "2024-01-15")

    def test_message_info_with_received_ms(self):
        """Test MessageInfo with received_ms field."""
        msg = make_message_info(
            msg_id="msg123", subject="Test", from_header="test@example.com",
            body_text="Body", received_date="2024-01-15", received_ms=1705334400000
        )
        self.assertEqual(msg.received_ms, 1705334400000)


class TestOrderData(unittest.TestCase):
    """Tests for OrderData dataclass."""

    def test_order_data_creation(self):
        """Test OrderData can be created."""
        messages = [
            make_message_info(msg_id="msg1", subject="Subject 1", from_header="test@ex.com", body_text="Body 1", received_date="2024-01-15"),
            make_message_info(msg_id="msg2", subject="Subject 2", from_header="test@ex.com", body_text="Body 2", received_date="2024-01-16"),
        ]
        order = OrderData(order_id="ORD123", messages=messages, vendor="TestVendor")
        self.assertEqual(order.order_id, "ORD123")
        self.assertEqual(len(order.messages), 2)
        self.assertEqual(order.vendor, "TestVendor")


if __name__ == "__main__":
    unittest.main()
