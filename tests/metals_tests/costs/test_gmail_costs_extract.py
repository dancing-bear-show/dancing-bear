"""Tests for gmail_costs extract-level helpers."""
from __future__ import annotations

import unittest

from metals.costs_common import G_PER_OZ, extract_order_amount
from metals.gmail_costs import (
    _classify_vendor,
    _extract_line_items,
    _is_cancelled,
    _is_order_confirmation,
    _parse_frac_match,
    _parse_gram_match,
    _parse_oz_match,
    _PAT_FRAC,
    _PAT_G,
    _PAT_OZ,
)


class TestExtractLineItems(unittest.TestCase):
    """Tests for _extract_line_items function."""

    def test_extracts_oz_gold(self):
        """Test extracts ounce gold amounts."""
        text = "1 oz Gold Maple Leaf"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "gold")
        self.assertEqual(items[0]["unit_oz"], 1.0)
        self.assertEqual(items[0]["qty"], 1.0)

    def test_extracts_oz_silver(self):
        """Test extracts ounce silver amounts."""
        text = "10 oz Silver Bar"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "silver")
        self.assertEqual(items[0]["unit_oz"], 10.0)

    def test_extracts_fractional_oz(self):
        """Test extracts fractional ounce amounts."""
        text = "1/10 oz Gold Eagle x 5"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "gold")
        self.assertAlmostEqual(items[0]["unit_oz"], 0.1, places=2)
        self.assertEqual(items[0]["qty"], 5.0)

    def test_extracts_with_quantity(self):
        """Test extracts amounts with quantity multiplier."""
        text = "1 oz Silver Maple Leaf x 10"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 10.0)

    def test_extracts_grams(self):
        """Test extracts gram amounts."""
        text = "31.1035 g Gold Bar"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["unit_oz"], 1.0, places=2)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        result = _extract_line_items("")
        self.assertIsNone(result)

    def test_handles_unicode_dashes(self):
        """Test normalizes unicode dashes."""
        text = "1 oz Gold – Maple"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)

    def test_handles_nbsp(self):
        """Test normalizes non-breaking spaces."""
        text = "1 oz Gold Maple"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)

    def test_leading_quantity(self):
        """Test handles leading quantity like '25 x 1 oz'."""
        text = "25 x 1 oz Silver Maple Leaf"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 25.0)

    def test_extracts_quarter_oz_gold(self):
        """Test extracts 1/4 oz gold."""
        text = "1/4 oz Gold Maple Leaf"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["unit_oz"], 0.25, places=2)

    def test_extracts_half_oz_gold(self):
        """Test extracts 1/2 oz gold."""
        text = "1/2 oz Gold Eagle x 2"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["unit_oz"], 0.5, places=2)
        self.assertEqual(items[0]["qty"], 2.0)

    def test_extracts_gram_unit(self):
        """Test extracts gram amounts with 'gram' spelling."""
        text = "50 gram Gold Bar"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["unit_oz"], 50 / G_PER_OZ, places=3)

    def test_extracts_grams_plural(self):
        """Test extracts 'grams' plural spelling."""
        text = "100 grams Silver Bar"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["unit_oz"], 100 / G_PER_OZ, places=3)

    def test_case_insensitive_metal(self):
        """Test metal detection is case insensitive."""
        text = "1 oz GOLD Maple"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "gold")

    def test_case_insensitive_silver(self):
        """Test silver detection is case insensitive."""
        text = "10 oz SILVER Bar"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["metal"], "silver")


class TestExtractOrderAmount(unittest.TestCase):
    """Tests for extract_order_amount function."""

    def test_extracts_total(self):
        """Test extracts Total amount."""
        text = "Total: C$2,520.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 2520.00)

    def test_extracts_subtotal_when_no_total(self):
        """Test extracts Subtotal when no Total."""
        text = "Item: 1 oz Silver\nSubtotal: C$35.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 35.00)

    def test_extracts_cad_currency(self):
        """Test extracts CAD currency format."""
        text = "Total: CAD$1,234.56"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 1234.56)

    def test_extracts_largest_when_no_keywords(self):
        """Test extracts largest amount when no Total/Subtotal."""
        text = "Price: $100.00\nExtended: $500.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 500.00)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        result = extract_order_amount("")
        self.assertIsNone(result)

    def test_handles_commas_in_amounts(self):
        """Test handles comma separators."""
        text = "Total: C$10,500.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 10500.00)

    def test_total_takes_precedence_over_subtotal(self):
        """Test Total takes precedence over Subtotal."""
        text = "Total: C$113.00\nTax: C$13.00\nSub-Total: C$100.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 113.00)

    def test_handles_usd_currency(self):
        """Test handles plain $ (USD) format."""
        text = "Total: $999.99"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 999.99)

    def test_handles_amount_without_cents(self):
        """Test handles amounts without decimal cents."""
        text = "Total: C$500"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        _, amt = result
        self.assertEqual(amt, 500.0)


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


class TestIsOrderConfirmation(unittest.TestCase):
    """Tests for _is_order_confirmation function."""

    def test_td_order_confirmation(self):
        """Test TD order confirmation detection."""
        result = _is_order_confirmation("Order Confirmation - TD Precious Metals", "noreply@td.com")
        self.assertTrue(result)

    def test_costco_order_confirmation(self):
        """Test Costco order confirmation detection."""
        result = _is_order_confirmation("Your Costco.ca Order Number 12345", "orders@costco.ca")
        self.assertTrue(result)

    def test_generic_order_confirmation(self):
        """Test generic order confirmation detection."""
        result = _is_order_confirmation("Order Confirmation #12345", "shop@example.com")
        self.assertTrue(result)

    def test_not_confirmation(self):
        """Test non-confirmation email."""
        result = _is_order_confirmation("Your order has shipped", "noreply@td.com")
        self.assertFalse(result)

    def test_handles_none(self):
        """Test handles None inputs."""
        result = _is_order_confirmation(None, None)
        self.assertFalse(result)


class TestIsCancelled(unittest.TestCase):
    """Tests for _is_cancelled function."""

    def test_cancelled_in_subject(self):
        """Test detects cancelled in subject."""
        result = _is_cancelled("Order Cancelled", "orders@costco.ca")
        self.assertTrue(result)

    def test_canceled_spelling(self):
        """Test detects American spelling (canceled)."""
        result = _is_cancelled("Order Canceled", "orders@costco.ca")
        self.assertTrue(result)

    def test_not_cancelled(self):
        """Test non-cancelled order."""
        result = _is_cancelled("Order Confirmed", "orders@costco.ca")
        self.assertFalse(result)

    def test_handles_none(self):
        """Test handles None inputs."""
        result = _is_cancelled(None, None)
        self.assertFalse(result)

    def test_case_insensitive(self):
        """Test case insensitive matching."""
        result = _is_cancelled("ORDER CANCELLED", "")
        self.assertTrue(result)


class TestParseMatchFunctions(unittest.TestCase):
    """Tests for _parse_frac_match, _parse_oz_match, _parse_gram_match."""

    def test_parse_frac_match_basic(self):
        """Test parses fractional oz match."""
        m = _PAT_FRAC.search("1/10 oz Gold x 5")
        unit_oz, metal, qty, explicit = _parse_frac_match(m)
        self.assertAlmostEqual(unit_oz, 0.1, places=2)
        self.assertEqual(metal, "gold")
        self.assertEqual(qty, 5.0)
        self.assertTrue(explicit)

    def test_parse_frac_match_no_qty(self):
        """Test parses fractional oz without explicit quantity."""
        m = _PAT_FRAC.search("1/4 oz Gold Maple")
        unit_oz, metal, qty, explicit = _parse_frac_match(m)
        self.assertAlmostEqual(unit_oz, 0.25, places=2)
        self.assertEqual(metal, "gold")
        self.assertEqual(qty, 1.0)
        self.assertFalse(explicit)

    def test_parse_oz_match_basic(self):
        """Test parses decimal oz match."""
        m = _PAT_OZ.search("10 oz Silver Bar")
        unit_oz, metal, qty, explicit = _parse_oz_match(m)
        self.assertEqual(unit_oz, 10.0)
        self.assertEqual(metal, "silver")
        self.assertEqual(qty, 1.0)
        self.assertFalse(explicit)

    def test_parse_oz_match_with_qty(self):
        """Test parses oz with explicit quantity."""
        m = _PAT_OZ.search("1 oz Silver Maple x 25")
        unit_oz, metal, qty, explicit = _parse_oz_match(m)
        self.assertEqual(unit_oz, 1.0)
        self.assertEqual(metal, "silver")
        self.assertEqual(qty, 25.0)
        self.assertTrue(explicit)

    def test_parse_gram_match_basic(self):
        """Test parses gram match."""
        m = _PAT_G.search("50 g Gold Bar")
        unit_oz, metal, qty, explicit = _parse_gram_match(m)
        self.assertAlmostEqual(unit_oz, 50 / G_PER_OZ, places=3)
        self.assertEqual(metal, "gold")
        self.assertEqual(qty, 1.0)
        self.assertFalse(explicit)

    def test_parse_gram_match_with_qty(self):
        """Test parses gram with quantity."""
        m = _PAT_G.search("100 grams Silver x 2")
        unit_oz, metal, qty, explicit = _parse_gram_match(m)
        self.assertAlmostEqual(unit_oz, 100 / G_PER_OZ, places=3)
        self.assertEqual(metal, "silver")
        self.assertEqual(qty, 2.0)
        self.assertTrue(explicit)


if __name__ == "__main__":
    unittest.main()
