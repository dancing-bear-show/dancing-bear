"""Tests for metals outlook_costs extraction module."""
from __future__ import annotations

import unittest

from metals.outlook_costs import (
    G_PER_OZ,
    _strip_html,
    _extract_order_id,
    _extract_line_items,
    _extract_order_amount,
)


class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_grams_per_oz(self):
        """Test grams per troy ounce constant."""
        self.assertAlmostEqual(G_PER_OZ, 31.1035, places=4)


class TestStripHtml(unittest.TestCase):
    """Tests for _strip_html function."""

    def test_strips_html_tags(self):
        """Test strips HTML tags."""
        html = "<p>Hello <b>World</b></p>"
        result = _strip_html(html)
        self.assertNotIn("<", result)
        self.assertIn("Hello", result)
        self.assertIn("World", result)

    def test_converts_br_to_space(self):
        """Test converts <br> tags (whitespace collapsed)."""
        html = "Line1<br>Line2<br/>Line3"
        result = _strip_html(html)
        # After br->newline and whitespace collapse, should have content
        self.assertIn("Line1", result)
        self.assertIn("Line2", result)
        self.assertIn("Line3", result)

    def test_handles_empty_string(self):
        """Test handles empty string."""
        self.assertEqual(_strip_html(""), "")

    def test_unescapes_html_entities(self):
        """Test unescapes HTML entities."""
        html = "Price: &amp; discount"
        result = _strip_html(html)
        self.assertIn("&", result)
        self.assertIn("discount", result)


class TestExtractOrderId(unittest.TestCase):
    """Tests for _extract_order_id function."""

    def test_extracts_po_number_from_subject(self):
        """Test extracts PO number from subject."""
        result = _extract_order_id("Order Confirmation PO1616870", "")
        self.assertEqual(result, "PO1616870")

    def test_extracts_po_number_from_body(self):
        """Test extracts PO number from body."""
        result = _extract_order_id("Order Confirmation", "Your order PO1234567 has been received")
        self.assertEqual(result, "PO1234567")

    def test_returns_none_when_not_found(self):
        """Test returns None when no PO number."""
        result = _extract_order_id("Hello", "No order here")
        self.assertIsNone(result)


class TestExtractLineItems(unittest.TestCase):
    """Tests for _extract_line_items function."""

    def test_extracts_fractional_oz(self):
        """Test extracts 1/10 oz gold."""
        text = "1/10 oz Gold Maple Leaf"
        items, lines = _extract_line_items(text)
        self.assertGreater(len(items), 0)
        # At least one item should have unit_oz around 0.1
        oz_values = [it["unit_oz"] for it in items]
        self.assertTrue(any(abs(oz - 0.1) < 0.01 for oz in oz_values))

    def test_extracts_decimal_oz(self):
        """Test extracts decimal ounce."""
        text = "1 oz Gold Bar"
        items, lines = _extract_line_items(text)
        self.assertGreater(len(items), 0)

    def test_extracts_grams(self):
        """Test extracts grams."""
        text = "31.1035 gram Gold Bar"
        items, lines = _extract_line_items(text)
        self.assertGreater(len(items), 0)
        # Should be approximately 1 oz
        oz_values = [it["unit_oz"] for it in items]
        self.assertTrue(any(abs(oz - 1.0) < 0.1 for oz in oz_values))

    def test_handles_empty_text(self):
        """Test handles empty text."""
        items, lines = _extract_line_items("")
        self.assertEqual(items, [])

    def test_normalizes_unicode_dashes(self):
        """Test normalizes unicode dashes."""
        # 1/10-oz with en-dash
        text = "1/10\u2013oz Gold Maple"
        items, lines = _extract_line_items(text)
        # Should still find the item
        self.assertGreater(len(items), 0)

    def test_finds_quantity_on_same_line(self):
        """Test finds quantity on same line."""
        text = "1/10 oz Gold Maple Leaf Qty: 5"
        items, lines = _extract_line_items(text)
        self.assertGreater(len(items), 0)
        # Should find qty of 5
        qty_values = [it.get("qty", 1) for it in items]
        self.assertTrue(any(q == 5.0 for q in qty_values))


class TestExtractOrderAmount(unittest.TestCase):
    """Tests for _extract_order_amount function."""

    def test_extracts_total(self):
        """Test extracts Total amount."""
        text = "Total: C$520.00"
        result = _extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 520.00)

    def test_extracts_cad_currency(self):
        """Test extracts CAD formats."""
        text = "Total: CAD$1,234.56"
        result = _extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 1234.56)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        result = _extract_order_amount("")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
