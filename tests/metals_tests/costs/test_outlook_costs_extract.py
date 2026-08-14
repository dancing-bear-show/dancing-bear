"""Tests for outlook_costs extract-level helpers."""
from __future__ import annotations

import math
import unittest

from core.text_utils import html_to_text
from metals.costs_common import extract_order_amount
from metals.vendors_parse_vendor import RCMParser


class TestClassifySubject(unittest.TestCase):
    """Tests for RCMParser.classify_email method."""

    def setUp(self):
        self.parser = RCMParser()

    def test_confirmation_with_order_number(self):
        """Test detects confirmation for order number."""
        email_type, priority = self.parser.classify_email("Confirmation for order number PO1234567")
        self.assertEqual(email_type, "confirmation")
        self.assertEqual(priority, 3)

    def test_confirmation_without_number(self):
        """Test detects confirmation for order (without 'number')."""
        email_type, priority = self.parser.classify_email("Confirmation for order PO1234567")
        self.assertEqual(email_type, "confirmation")
        self.assertEqual(priority, 3)

    def test_confirmation_case_insensitive(self):
        """Test confirmation detection is case insensitive."""
        email_type, priority = self.parser.classify_email("CONFIRMATION FOR ORDER NUMBER PO123")
        self.assertEqual(email_type, "confirmation")
        self.assertEqual(priority, 3)

    def test_shipping_confirmation(self):
        """Test detects shipping confirmation."""
        email_type, priority = self.parser.classify_email("Shipping Confirmation for your order")
        self.assertEqual(email_type, "shipping")
        self.assertEqual(priority, 2)

    def test_was_shipped(self):
        """Test detects 'was shipped' pattern."""
        email_type, priority = self.parser.classify_email("Your order was shipped")
        self.assertEqual(email_type, "shipping")
        self.assertEqual(priority, 2)

    def test_request_received(self):
        """Test detects request received."""
        email_type, priority = self.parser.classify_email("We received your request")
        self.assertEqual(email_type, "request")
        self.assertEqual(priority, 1)

    def test_other_subject(self):
        """Test returns 'other' for unrecognized subjects."""
        email_type, priority = self.parser.classify_email("Random email subject")
        self.assertEqual(email_type, "other")
        self.assertEqual(priority, 0)

    def test_empty_subject(self):
        """Test handles empty subject."""
        email_type, priority = self.parser.classify_email("")
        self.assertEqual(email_type, "other")
        self.assertEqual(priority, 0)

    def test_none_subject(self):
        """Test handles None subject."""
        email_type, priority = self.parser.classify_email(None)
        self.assertEqual(email_type, "other")
        self.assertEqual(priority, 0)


class TestHtmlToText(unittest.TestCase):
    """Tests for html_to_text function (from core.text_utils)."""

    def test_strips_html_tags(self):
        """Test strips HTML tags."""
        html = "<p>Hello <b>World</b></p>"
        result = html_to_text(html)
        self.assertNotIn("<", result)
        self.assertIn("Hello", result)
        self.assertIn("World", result)

    def test_converts_br_to_space(self):
        """Test converts <br> tags (whitespace collapsed)."""
        html = "Line1<br>Line2<br/>Line3"
        result = html_to_text(html)
        self.assertIn("Line1", result)
        self.assertIn("Line2", result)
        self.assertIn("Line3", result)

    def test_handles_empty_string(self):
        """Test handles empty string."""
        self.assertEqual(html_to_text(""), "")

    def test_unescapes_html_entities(self):
        """Test unescapes HTML entities."""
        html = "Price: &amp; discount"
        result = html_to_text(html)
        self.assertIn("&", result)
        self.assertIn("discount", result)


class TestExtractOrderId(unittest.TestCase):
    """Tests for RCMParser.extract_order_id method."""

    def setUp(self):
        self.parser = RCMParser()

    def test_extracts_po_number_from_subject(self):
        """Test extracts PO number from subject."""
        result = self.parser.extract_order_id("Order Confirmation PO1616870", "")
        self.assertEqual(result, "PO1616870")

    def test_extracts_po_number_from_body(self):
        """Test extracts PO number from body."""
        result = self.parser.extract_order_id("Order Confirmation", "Your order PO1234567 has been received")
        self.assertEqual(result, "PO1234567")

    def test_returns_none_when_not_found(self):
        """Test returns None when no PO number."""
        result = self.parser.extract_order_id("Hello", "No order here")
        self.assertIsNone(result)


class TestExtractLineItems(unittest.TestCase):
    """Tests for RCMParser.extract_line_items method."""

    def setUp(self):
        self.parser = RCMParser()

    def test_extracts_fractional_oz(self):
        """Test extracts 1/10 oz gold."""
        text = "1/10 oz Gold Maple Leaf"
        items, _lines = self.parser.extract_line_items(text)
        self.assertGreater(len(items), 0)
        oz_values = [it.unit_oz for it in items]
        self.assertTrue(any(abs(oz - 0.1) < 0.01 for oz in oz_values))

    def test_extracts_decimal_oz(self):
        """Test extracts decimal ounce."""
        text = "1 oz Gold Bar"
        items, _lines = self.parser.extract_line_items(text)
        self.assertGreater(len(items), 0)

    def test_extracts_grams(self):
        """Test extracts grams."""
        text = "31.1035 gram Gold Bar"
        items, _lines = self.parser.extract_line_items(text)
        self.assertGreater(len(items), 0)
        oz_values = [it.unit_oz for it in items]
        self.assertTrue(any(abs(oz - 1.0) < 0.1 for oz in oz_values))

    def test_handles_empty_text(self):
        """Test handles empty text."""
        items, _lines = self.parser.extract_line_items("")
        self.assertEqual(items, [])

    def test_normalizes_unicode_dashes(self):
        """Test normalizes unicode dashes."""
        text = "1/10–oz Gold Maple"
        items, _lines = self.parser.extract_line_items(text)
        self.assertGreater(len(items), 0)

    def test_finds_quantity_on_same_line(self):
        """Test finds quantity on same line."""
        text = "1/10 oz Gold Maple Leaf Qty: 5"
        items, _lines = self.parser.extract_line_items(text)
        self.assertGreater(len(items), 0)
        qty_values = [it.qty for it in items]
        self.assertTrue(any(math.isclose(q, 5.0) for q in qty_values))


class TestExtractOrderAmount(unittest.TestCase):
    """Tests for extract_order_amount function."""

    def test_extracts_total(self):
        """Test extracts Total amount."""
        text = "Total: C$520.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _cur, amt = result
        self.assertEqual(amt, 520.00)

    def test_extracts_cad_currency(self):
        """Test extracts CAD formats."""
        text = "Total: CAD$1,234.56"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _cur, amt = result
        self.assertEqual(amt, 1234.56)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        result = extract_order_amount("")
        self.assertIsNone(result)


class TestAmountNearItem(unittest.TestCase):
    """Tests for RCMParser.extract_price_near_item method."""

    def setUp(self):
        self.parser = RCMParser()

    def test_finds_total_on_same_line(self):
        """Test finds 'total' labeled amount."""
        lines = ["1/10 oz Gold Maple Leaf", "Total C$350.00"]
        result = self.parser.extract_price_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNotNone(result)
        self.assertEqual(result.amount, 350.00)
        self.assertEqual(result.kind, "total")

    def test_finds_unit_price(self):
        """Test finds unit price when no 'total' label."""
        lines = ["1/10 oz Gold Maple Leaf", "C$350.00"]
        result = self.parser.extract_price_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNotNone(result)
        self.assertEqual(result.amount, 350.00)
        self.assertEqual(result.kind, "unit")

    def test_skips_banned_lines(self):
        """Test skips subtotal/tax/shipping lines."""
        lines = [
            "1/10 oz Gold Maple Leaf",
            "Subtotal C$350.00",
            "Shipping C$15.00",
            "Tax C$45.00",
            "Total C$410.00",
        ]
        result = self.parser.extract_price_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNotNone(result)
        self.assertEqual(result.amount, 410.00)
        self.assertEqual(result.kind, "total")

    def test_returns_none_when_no_amount(self):
        """Test returns None when no valid amount found."""
        lines = ["1/10 oz Gold Maple Leaf", "Description only"]
        result = self.parser.extract_price_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNone(result)

    def test_filters_by_price_range_for_gold(self):
        """Test filters amounts by expected price range."""
        lines = ["1/10 oz Gold Maple Leaf", "C$50.00"]
        result = self.parser.extract_price_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNone(result)


class TestExtractConfirmationItemTotals(unittest.TestCase):
    """Tests for RCMParser.extract_confirmation_totals method."""

    def setUp(self):
        self.parser = RCMParser()

    def test_extracts_single_total(self):
        """Test extracts single item total."""
        text = "Product: Gold Coin\nTotal $350.00 CAD"
        totals = self.parser.extract_confirmation_totals(text)
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0], 350.00)

    def test_extracts_multiple_totals(self):
        """Test extracts multiple item totals."""
        text = "Product 1: Gold Coin\nTotal $350.00 CAD\nProduct 2: Gold Bar\nTotal $1,500.00 CAD"
        totals = self.parser.extract_confirmation_totals(text)
        self.assertEqual(len(totals), 2)
        self.assertEqual(totals[0], 350.00)
        self.assertEqual(totals[1], 1500.00)

    def test_skips_free_shipping_threshold(self):
        """Test skips lines with free shipping threshold."""
        text = "Product: Gold Coin\nTotal $350.00 CAD\nOrders over $500 qualify for free shipping"
        totals = self.parser.extract_confirmation_totals(text)
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0], 350.00)

    def test_skips_subtotal_lines(self):
        """Test skips subtotal lines."""
        text = "Item Total $350.00 CAD\nSubtotal $350.00 CAD"
        totals = self.parser.extract_confirmation_totals(text)
        self.assertEqual(len(totals), 1)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        totals = self.parser.extract_confirmation_totals("")
        self.assertEqual(totals, [])

    def test_handles_cad_formats(self):
        """Test handles various CAD formats."""
        text = "Total C$350.00 CAD"
        totals = self.parser.extract_confirmation_totals(text)
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0], 350.00)


if __name__ == "__main__":
    unittest.main()
