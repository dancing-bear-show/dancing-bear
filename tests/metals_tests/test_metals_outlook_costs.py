"""Tests for metals outlook_costs extraction module."""
from __future__ import annotations

import csv
import os
import unittest

from tests.fixtures import TempDirMixin

from core.text_utils import html_to_text
from metals.costs_common import (
    G_PER_OZ,
    extract_order_amount,
    merge_costs_csv,
)
from metals.outlook_costs import (
    _amount_near_item,
    _classify_subject,
    _extract_confirmation_item_totals,
    _extract_line_items,
    _extract_order_id,
)


class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_grams_per_oz(self):
        """Test grams per troy ounce constant."""
        self.assertAlmostEqual(G_PER_OZ, 31.1035, places=4)


class TestClassifySubject(unittest.TestCase):
    """Tests for _classify_subject function."""

    def test_confirmation_with_order_number(self):
        """Test detects confirmation for order number."""
        result = _classify_subject("Confirmation for order number PO1234567")
        self.assertEqual(result, "confirmation")

    def test_confirmation_without_number(self):
        """Test detects confirmation for order (without 'number')."""
        result = _classify_subject("Confirmation for order PO1234567")
        self.assertEqual(result, "confirmation")

    def test_confirmation_case_insensitive(self):
        """Test confirmation detection is case insensitive."""
        result = _classify_subject("CONFIRMATION FOR ORDER NUMBER PO123")
        self.assertEqual(result, "confirmation")

    def test_shipping_confirmation(self):
        """Test detects shipping confirmation."""
        result = _classify_subject("Shipping Confirmation for your order")
        self.assertEqual(result, "shipping")

    def test_was_shipped(self):
        """Test detects 'was shipped' pattern."""
        result = _classify_subject("Your order was shipped")
        self.assertEqual(result, "shipping")

    def test_request_received(self):
        """Test detects request received."""
        result = _classify_subject("We received your request")
        self.assertEqual(result, "request")

    def test_other_subject(self):
        """Test returns 'other' for unrecognized subjects."""
        result = _classify_subject("Random email subject")
        self.assertEqual(result, "other")

    def test_empty_subject(self):
        """Test handles empty subject."""
        result = _classify_subject("")
        self.assertEqual(result, "other")

    def test_none_subject(self):
        """Test handles None subject."""
        result = _classify_subject(None)
        self.assertEqual(result, "other")


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
        # After br->newline and whitespace collapse, should have content
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
    """Tests for extract_order_amount function."""

    def test_extracts_total(self):
        """Test extracts Total amount."""
        text = "Total: C$520.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 520.00)

    def test_extracts_cad_currency(self):
        """Test extracts CAD formats."""
        text = "Total: CAD$1,234.56"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        cur, amt = result
        self.assertEqual(amt, 1234.56)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        result = extract_order_amount("")
        self.assertIsNone(result)


class TestAmountNearItem(unittest.TestCase):
    """Tests for _amount_near_item function."""

    def test_finds_total_on_same_line(self):
        """Test finds 'total' labeled amount."""
        lines = [
            "1/10 oz Gold Maple Leaf",
            "Total C$350.00",
        ]
        result = _amount_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNotNone(result)
        amt, kind = result
        self.assertEqual(amt, 350.00)
        self.assertEqual(kind, "total")

    def test_finds_unit_price(self):
        """Test finds unit price when no 'total' label."""
        lines = [
            "1/10 oz Gold Maple Leaf",
            "C$350.00",
        ]
        result = _amount_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNotNone(result)
        amt, kind = result
        self.assertEqual(amt, 350.00)
        self.assertEqual(kind, "unit")

    def test_skips_banned_lines(self):
        """Test skips subtotal/tax/shipping lines."""
        lines = [
            "1/10 oz Gold Maple Leaf",
            "Subtotal C$350.00",
            "Shipping C$15.00",
            "Tax C$45.00",
            "Total C$410.00",
        ]
        # The function should skip subtotal/shipping/tax
        result = _amount_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNotNone(result)
        amt, kind = result
        self.assertEqual(amt, 410.00)  # Should get the Total, not subtotal
        self.assertEqual(kind, "total")

    def test_returns_none_when_no_amount(self):
        """Test returns None when no valid amount found."""
        lines = ["1/10 oz Gold Maple Leaf", "Description only"]
        result = _amount_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNone(result)

    def test_filters_by_price_range_for_gold(self):
        """Test filters amounts by expected price range."""
        lines = [
            "1/10 oz Gold Maple Leaf",
            "C$50.00",  # Too low for gold
        ]
        result = _amount_near_item(lines, 0, metal="gold", unit_oz=0.1)
        self.assertIsNone(result)  # Should reject $50 as too low


class TestExtractConfirmationItemTotals(unittest.TestCase):
    """Tests for _extract_confirmation_item_totals function."""

    def test_extracts_single_total(self):
        """Test extracts single item total."""
        text = "Product: Gold Coin\nTotal $350.00 CAD"
        totals = _extract_confirmation_item_totals(text)
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0], 350.00)

    def test_extracts_multiple_totals(self):
        """Test extracts multiple item totals."""
        text = """
        Product 1: Gold Coin
        Total $350.00 CAD
        Product 2: Gold Bar
        Total $1,500.00 CAD
        """
        totals = _extract_confirmation_item_totals(text)
        self.assertEqual(len(totals), 2)
        self.assertEqual(totals[0], 350.00)
        self.assertEqual(totals[1], 1500.00)

    def test_skips_free_shipping_threshold(self):
        """Test skips lines with free shipping threshold."""
        text = """
        Product: Gold Coin
        Total $350.00 CAD
        Orders over $500 qualify for free shipping
        """
        totals = _extract_confirmation_item_totals(text)
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0], 350.00)

    def test_skips_subtotal_lines(self):
        """Test skips subtotal lines."""
        text = """
        Item Total $350.00 CAD
        Subtotal $350.00 CAD
        """
        # Only the item total, not subtotal
        totals = _extract_confirmation_item_totals(text)
        self.assertEqual(len(totals), 1)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        totals = _extract_confirmation_item_totals("")
        self.assertEqual(totals, [])

    def test_handles_cad_formats(self):
        """Test handles various CAD formats."""
        text = "Total C$350.00 CAD"
        totals = _extract_confirmation_item_totals(text)
        self.assertEqual(len(totals), 1)
        self.assertEqual(totals[0], 350.00)


class TestMergeWrite(TempDirMixin, unittest.TestCase):
    """Tests for merge_costs_csv function."""

    def test_writes_new_file(self):
        """Test writes new CSV file."""
        path = os.path.join(self.tmpdir, "costs.csv")
        rows = [
            {
                "vendor": "RCM",
                "date": "2024-01-15",
                "metal": "gold",
                "currency": "C$",
                "cost_total": 350.00,
                "cost_per_oz": 3500.00,
                "order_id": "PO1234567",
                "subject": "Confirmation",
                "total_oz": 0.1,
                "unit_count": 1,
                "units_breakdown": "0.1ozx1",
                "alloc": "line-item",
            }
        ]
        merge_costs_csv(path, rows)

        self.assertTrue(os.path.exists(path))
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            result = list(reader)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["vendor"], "RCM")
        self.assertEqual(result[0]["order_id"], "PO1234567")

    def test_merges_with_existing_file(self):
        """Test merges new rows with existing file."""
        path = os.path.join(self.tmpdir, "costs.csv")

        # Write initial file
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "vendor", "date", "metal", "currency", "cost_total",
                    "cost_per_oz", "order_id", "subject", "total_oz",
                    "unit_count", "units_breakdown", "alloc"
                ],
            )
            w.writeheader()
            w.writerow({
                "vendor": "RCM",
                "date": "2024-01-10",
                "metal": "gold",
                "currency": "C$",
                "cost_total": "300.00",
                "cost_per_oz": "3000.00",
                "order_id": "PO1111111",
                "subject": "First Order",
                "total_oz": "0.1",
                "unit_count": "1",
                "units_breakdown": "0.1ozx1",
                "alloc": "line-item",
            })

        # Merge new rows
        new_rows = [
            {
                "vendor": "RCM",
                "date": "2024-01-15",
                "metal": "gold",
                "currency": "C$",
                "cost_total": 350.00,
                "cost_per_oz": 3500.00,
                "order_id": "PO2222222",
                "subject": "Second Order",
                "total_oz": 0.1,
                "unit_count": 1,
                "units_breakdown": "0.1ozx1",
                "alloc": "line-item",
            }
        ]
        merge_costs_csv(path, new_rows)

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            result = list(reader)
        self.assertEqual(len(result), 2)

    def test_deduplicates_rows(self):
        """Test deduplicates identical rows."""
        path = os.path.join(self.tmpdir, "costs.csv")

        rows = [
            {
                "vendor": "RCM",
                "date": "2024-01-15",
                "metal": "gold",
                "currency": "C$",
                "cost_total": 350.00,
                "cost_per_oz": 3500.00,
                "order_id": "PO1234567",
                "subject": "Confirmation",
                "total_oz": 0.1,
                "unit_count": 1,
                "units_breakdown": "0.1ozx1",
                "alloc": "line-item",
            },
            {
                "vendor": "RCM",
                "date": "2024-01-15",
                "metal": "gold",
                "currency": "C$",
                "cost_total": 350.00,
                "cost_per_oz": 3500.00,
                "order_id": "PO1234567",
                "subject": "Confirmation",
                "total_oz": 0.1,
                "unit_count": 1,
                "units_breakdown": "0.1ozx1",
                "alloc": "line-item",
            },
        ]
        merge_costs_csv(path, rows)

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            result = list(reader)
        self.assertEqual(len(result), 1)  # Should dedupe

    def test_prefers_confirmation_over_shipping(self):
        """Test prefers confirmation emails over shipping."""
        path = os.path.join(self.tmpdir, "costs.csv")

        rows = [
            {
                "vendor": "RCM",
                "date": "2024-01-15",
                "metal": "gold",
                "currency": "C$",
                "cost_total": 350.00,
                "cost_per_oz": 3500.00,
                "order_id": "PO1234567",
                "subject": "Shipping confirmation",
                "total_oz": 0.1,
                "unit_count": 1,
                "units_breakdown": "0.1ozx1",
                "alloc": "line-item",
            },
            {
                "vendor": "RCM",
                "date": "2024-01-15",
                "metal": "gold",
                "currency": "C$",
                "cost_total": 350.00,
                "cost_per_oz": 3500.00,
                "order_id": "PO1234567",
                "subject": "Confirmation for order number PO1234567",
                "total_oz": 0.1,
                "unit_count": 1,
                "units_breakdown": "0.1ozx1",
                "alloc": "line-item",
            },
        ]
        merge_costs_csv(path, rows)

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            result = list(reader)
        # Should keep the confirmation, drop shipping
        self.assertEqual(len(result), 1)
        self.assertIn("Confirmation for order", result[0]["subject"])


if __name__ == "__main__":
    unittest.main()
