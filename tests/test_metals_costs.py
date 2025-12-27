"""Tests for metals costs extraction module."""
from __future__ import annotations

import unittest

from metals.costs import (
    G_PER_OZ,
    _extract_line_items,
    _extract_order_amount,
    _extract_amount_near_line,
    _classify_vendor,
)


class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_grams_per_oz(self):
        """Test grams per troy ounce constant."""
        self.assertAlmostEqual(G_PER_OZ, 31.1035, places=4)


class TestExtractLineItems(unittest.TestCase):
    """Tests for _extract_line_items function."""

    def test_extracts_oz_gold(self):
        """Test extracts ounce gold amounts."""
        text = "1 oz Gold Maple Leaf"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "gold")
        self.assertEqual(items[0]["unit_oz"], 1.0)
        self.assertEqual(items[0]["qty"], 1.0)

    def test_extracts_oz_silver(self):
        """Test extracts ounce silver amounts."""
        text = "10 oz Silver Bar"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "silver")
        self.assertEqual(items[0]["unit_oz"], 10.0)

    def test_extracts_fractional_oz(self):
        """Test extracts fractional ounce amounts."""
        text = "1/10 oz Gold Eagle x 5"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "gold")
        self.assertAlmostEqual(items[0]["unit_oz"], 0.1, places=2)
        self.assertEqual(items[0]["qty"], 5.0)

    def test_extracts_with_quantity(self):
        """Test extracts amounts with quantity multiplier."""
        text = "1 oz Silver Maple Leaf x 10"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 10.0)

    def test_extracts_grams(self):
        """Test extracts gram amounts."""
        text = "31.1035 g Gold Bar"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["unit_oz"], 1.0, places=2)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        result = _extract_line_items("")
        # Returns None for empty text
        self.assertIsNone(result)

    def test_handles_unicode_dashes(self):
        """Test normalizes unicode dashes."""
        # en-dash
        text = "1 oz Gold \u2013 Maple"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)

    def test_handles_nbsp(self):
        """Test normalizes non-breaking spaces."""
        text = "1\u00A0oz Gold Maple"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)

    def test_extracts_first_line_items(self):
        """Test extracts items from first non-empty line only."""
        # Note: function returns after processing first non-empty line
        text = "1 oz Gold Maple x 2"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 2.0)

    def test_leading_quantity(self):
        """Test handles leading quantity like '25 x 1 oz'."""
        text = "25 x 1 oz Silver Maple Leaf"
        items, lines = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 25.0)


class TestExtractOrderAmount(unittest.TestCase):
    """Tests for _extract_order_amount function."""

    def test_extracts_total(self):
        """Test extracts Total amount."""
        text = "Total: C$2,520.00"
        result = _extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 2520.00)

    def test_extracts_subtotal_when_no_total(self):
        """Test extracts Subtotal when no Total."""
        text = """
        Item: 1 oz Silver
        Subtotal: C$35.00
        """
        result = _extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 35.00)

    def test_extracts_cad_currency(self):
        """Test extracts CAD currency format."""
        text = "Total: CAD$1,234.56"
        result = _extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 1234.56)

    def test_extracts_largest_when_no_keywords(self):
        """Test extracts largest amount when no Total/Subtotal."""
        text = """
        Price: $100.00
        Extended: $500.00
        """
        result = _extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 500.00)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        result = _extract_order_amount("")
        self.assertIsNone(result)

    def test_handles_commas_in_amounts(self):
        """Test handles comma separators."""
        text = "Total: C$10,500.00"
        result = _extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 10500.00)


class TestClassifyVendor(unittest.TestCase):
    """Tests for _classify_vendor function."""

    def test_classifies_td(self):
        """Test classifies TD vendor."""
        self.assertEqual(_classify_vendor("noreply@td.com"), "TD")
        self.assertEqual(_classify_vendor("<noreply@td.com>"), "TD")
        self.assertEqual(_classify_vendor("TD <noreply@tdsecurities.com>"), "TD")

    def test_classifies_costco(self):
        """Test classifies Costco vendor."""
        self.assertEqual(_classify_vendor("orderstatus@costco.ca"), "Costco")
        self.assertEqual(_classify_vendor("<orders@costco.com>"), "Costco")

    def test_classifies_rcm(self):
        """Test classifies RCM vendor."""
        self.assertEqual(_classify_vendor("noreply@email.mint.ca"), "RCM")
        self.assertEqual(_classify_vendor("info@mint.ca"), "RCM")
        self.assertEqual(_classify_vendor("shop@royalcanadianmint.ca"), "RCM")

    def test_classifies_other(self):
        """Test classifies unknown vendor as Other."""
        self.assertEqual(_classify_vendor("unknown@example.com"), "Other")
        self.assertEqual(_classify_vendor(""), "Other")

    def test_handles_none(self):
        """Test handles None input."""
        self.assertEqual(_classify_vendor(None), "Other")


class TestExtractAmountNearLine(unittest.TestCase):
    """Tests for _extract_amount_near_line function."""

    def test_finds_price_same_line(self):
        """Test finds price on same line as item."""
        lines = ["1 oz Gold Maple Leaf $1,850.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        cur, amt, kind = result
        self.assertAlmostEqual(amt, 1850.00)

    def test_finds_price_adjacent_line(self):
        """Test finds price on adjacent line."""
        lines = [
            "1 oz Gold Maple Leaf",
            "Price: $1,850.00",
        ]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        cur, amt, kind = result
        self.assertAlmostEqual(amt, 1850.00)

    def test_skips_subtotal_line(self):
        """Test skips lines with subtotal."""
        lines = [
            "1 oz Gold Maple",
            "Subtotal: $5,000.00",
        ]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_skips_shipping_line(self):
        """Test skips lines with shipping."""
        lines = [
            "1 oz Gold Maple",
            "Shipping: $25.00",
        ]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_skips_tax_line(self):
        """Test skips lines with tax."""
        lines = [
            "1 oz Gold",
            "Tax: $150.00",
        ]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_detects_unit_price(self):
        """Test detects unit price kind."""
        lines = ["1 oz Gold - Unit Price: $1,800.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        cur, amt, kind = result
        self.assertEqual(kind, "unit")

    def test_detects_each_price(self):
        """Test detects 'each' as unit price."""
        # 'each' must appear between the anchor (metal/unit-oz) and the price
        lines = ["1 oz Silver - each $35.00"]
        result = _extract_amount_near_line(lines, 0, "silver", 1.0, "TD")
        self.assertIsNotNone(result)
        cur, amt, kind = result
        self.assertEqual(kind, "unit")

    def test_handles_empty_lines(self):
        """Test handles empty lines list."""
        result = _extract_amount_near_line([], 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_handles_out_of_bounds_idx(self):
        """Test handles out of bounds index gracefully."""
        lines = ["Some line"]
        result = _extract_amount_near_line(lines, 10, "gold", 1.0, "TD")
        # Should search available lines
        self.assertIsNone(result)

    def test_cad_currency_format(self):
        """Test handles CAD currency format."""
        lines = ["1 oz Gold C$2,100.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        cur, amt, kind = result
        self.assertIn("$", cur)
        self.assertAlmostEqual(amt, 2100.00)


if __name__ == "__main__":
    unittest.main()
