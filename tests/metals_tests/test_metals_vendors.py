"""Tests for metals vendors module."""
from __future__ import annotations

import unittest

from metals.vendors import (
    ALL_VENDORS,
    GMAIL_VENDORS,
    OUTLOOK_VENDORS,
    CostcoParser,
    LineItem,
    PriceHit,
    RCMParser,
    TDParser,
    dedupe_line_items,
    extract_basic_line_items,
    extract_price_from_lines,
    find_qty_near,
    get_vendor_for_sender,
    infer_metal_from_context,
    iter_nearby_lines,
)

from tests.metals_tests.fixtures import LINES_3, LINES_5, VENDOR_EMAILS, make_price_lines


class TestVendorLists(unittest.TestCase):
    """Tests for vendor list constants."""

    def test_all_vendors_has_three(self):
        """Test ALL_VENDORS has three parsers."""
        self.assertEqual(len(ALL_VENDORS), 3)

    def test_gmail_vendors_matches_all(self):
        """Test GMAIL_VENDORS includes all vendors."""
        self.assertEqual(GMAIL_VENDORS, ALL_VENDORS)

    def test_outlook_vendors_has_rcm_only(self):
        """Test OUTLOOK_VENDORS has only RCM."""
        self.assertEqual(len(OUTLOOK_VENDORS), 1)
        self.assertIsInstance(OUTLOOK_VENDORS[0], RCMParser)


class TestGetVendorForSender(unittest.TestCase):
    """Tests for get_vendor_for_sender function."""

    def test_matches_td(self):
        """Test matches TD sender."""
        vendor = get_vendor_for_sender(VENDOR_EMAILS["TD"][0])
        self.assertIsNotNone(vendor)
        self.assertEqual(vendor.name, "TD")

    def test_matches_costco(self):
        """Test matches Costco sender."""
        vendor = get_vendor_for_sender(VENDOR_EMAILS["Costco"][0])
        self.assertIsNotNone(vendor)
        self.assertEqual(vendor.name, "Costco")

    def test_matches_rcm(self):
        """Test matches RCM sender."""
        vendor = get_vendor_for_sender(VENDOR_EMAILS["RCM"][0])
        self.assertIsNotNone(vendor)
        self.assertEqual(vendor.name, "RCM")

    def test_returns_none_for_unknown(self):
        """Test returns None for unknown sender."""
        vendor = get_vendor_for_sender(VENDOR_EMAILS["unknown"][0])
        self.assertIsNone(vendor)

    def test_case_insensitive(self):
        """Test matching is case insensitive."""
        vendor = get_vendor_for_sender(VENDOR_EMAILS["TD"][2])  # NoReply@TD.COM
        self.assertIsNotNone(vendor)
        self.assertEqual(vendor.name, "TD")


class TestTDParser(unittest.TestCase):
    """Tests for TDParser class."""

    def setUp(self):
        self.parser = TDParser()

    def test_name(self):
        """Test parser name."""
        self.assertEqual(self.parser.name, "TD")

    def test_matches_td_sender(self):
        """Test matches TD sender."""
        self.assertTrue(self.parser.matches_sender(VENDOR_EMAILS["TD"][0]))
        self.assertTrue(self.parser.matches_sender(VENDOR_EMAILS["TD"][1]))

    def test_does_not_match_other(self):
        """Test does not match other senders."""
        self.assertFalse(self.parser.matches_sender(VENDOR_EMAILS["Costco"][0]))

    def test_extract_line_items_gold(self):
        """Test extracts gold line items."""
        text = "1 oz Gold Maple Leaf\nPrice: $2500"
        items, lines = self.parser.extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metal, "gold")
        self.assertAlmostEqual(items[0].unit_oz, 1.0, places=2)

    def test_extract_line_items_silver(self):
        """Test extracts silver line items."""
        text = "10 oz Silver Bar\nPrice: $350"
        items, lines = self.parser.extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metal, "silver")
        self.assertAlmostEqual(items[0].unit_oz, 10.0, places=2)


class TestCostcoParser(unittest.TestCase):
    """Tests for CostcoParser class."""

    def setUp(self):
        self.parser = CostcoParser()

    def test_name(self):
        """Test parser name."""
        self.assertEqual(self.parser.name, "Costco")

    def test_matches_costco_sender(self):
        """Test matches Costco sender."""
        self.assertTrue(self.parser.matches_sender(VENDOR_EMAILS["Costco"][0]))
        self.assertTrue(self.parser.matches_sender(VENDOR_EMAILS["Costco"][1]))

    def test_does_not_match_other(self):
        """Test does not match other senders."""
        self.assertFalse(self.parser.matches_sender(VENDOR_EMAILS["TD"][0]))


class TestRCMParser(unittest.TestCase):
    """Tests for RCMParser class."""

    def setUp(self):
        self.parser = RCMParser()

    def test_name(self):
        """Test parser name."""
        self.assertEqual(self.parser.name, "RCM")

    def test_matches_rcm_sender(self):
        """Test matches RCM sender."""
        self.assertTrue(self.parser.matches_sender(VENDOR_EMAILS["RCM"][0]))
        self.assertTrue(self.parser.matches_sender(VENDOR_EMAILS["RCM"][1]))

    def test_does_not_match_other(self):
        """Test does not match other senders."""
        self.assertFalse(self.parser.matches_sender(VENDOR_EMAILS["TD"][0]))

    def test_classify_email_confirmation(self):
        """Test classifies confirmation email."""
        cat, rank = self.parser.classify_email("Confirmation for order number PO123")
        self.assertEqual(cat, "confirmation")
        self.assertEqual(rank, 3)

    def test_classify_email_shipping(self):
        """Test classifies shipping email."""
        cat, rank = self.parser.classify_email("Shipping Confirmation for your order")
        self.assertEqual(cat, "shipping")
        self.assertEqual(rank, 2)

    def test_classify_email_request(self):
        """Test classifies request email."""
        cat, rank = self.parser.classify_email("We received your request for order")
        self.assertEqual(cat, "request")
        self.assertEqual(rank, 1)

    def test_classify_email_other(self):
        """Test classifies other email."""
        cat, rank = self.parser.classify_email("Some other subject")
        self.assertEqual(cat, "other")
        self.assertEqual(rank, 0)

    def test_extract_order_id_from_subject(self):
        """Test extracts order ID from subject."""
        order_id = self.parser.extract_order_id("Order PO1234567 confirmed", "")
        self.assertEqual(order_id, "PO1234567")

    def test_extract_order_id_from_body(self):
        """Test extracts order ID from body."""
        order_id = self.parser.extract_order_id("Your order", "Order number: PO7654321")
        self.assertEqual(order_id, "PO7654321")

    def test_extract_order_id_none(self):
        """Test returns None when no order ID found."""
        order_id = self.parser.extract_order_id("Hello", "No order here")
        self.assertIsNone(order_id)

    def test_extract_confirmation_totals(self):
        """Test extracts confirmation totals."""
        text = "Item 1\nTotal $250.00 CAD\nItem 2\nTotal $500.00 CAD"
        totals = self.parser.extract_confirmation_totals(text)
        self.assertEqual(len(totals), 2)
        self.assertAlmostEqual(totals[0], 250.00, places=2)
        self.assertAlmostEqual(totals[1], 500.00, places=2)


class TestFindQtyNear(unittest.TestCase):
    """Tests for find_qty_near function."""

    def test_finds_qty_with_x(self):
        """Test finds quantity with x prefix."""
        lines = ["1 oz Gold", "x 5", "Price"]
        qty = find_qty_near(lines, 0)
        self.assertEqual(qty, 5.0)

    def test_finds_qty_label(self):
        """Test finds quantity with Qty label."""
        lines = ["1 oz Gold", "Qty: 3", "Price"]
        qty = find_qty_near(lines, 0)
        self.assertEqual(qty, 3.0)

    def test_returns_none_when_not_found(self):
        """Test returns None when no quantity found."""
        lines = ["1 oz Gold", "Price: $100"]
        qty = find_qty_near(lines, 0)
        self.assertIsNone(qty)

    def test_respects_window(self):
        """Test respects window parameter."""
        lines = ["Line 0", "Line 1", "Line 2", "x 5", "Line 4"]
        # Window of 2 should not reach line 3
        qty = find_qty_near(lines, 0, window=2)
        self.assertIsNone(qty)


class TestInferMetalFromContext(unittest.TestCase):
    """Tests for infer_metal_from_context function."""

    def test_infers_gold(self):
        """Test infers gold from context."""
        self.assertEqual(infer_metal_from_context("This is a gold coin"), "gold")

    def test_infers_silver(self):
        """Test infers silver from context."""
        self.assertEqual(infer_metal_from_context("Silver bar 10oz"), "silver")

    def test_returns_empty_for_unknown(self):
        """Test returns empty string for unknown."""
        self.assertEqual(infer_metal_from_context("Just some text"), "")


class TestExtractBasicLineItems(unittest.TestCase):
    """Tests for extract_basic_line_items function."""

    def test_extracts_fractional_oz(self):
        """Test extracts fractional ounce items."""
        text = "1/10 oz Gold Eagle"
        items, lines = extract_basic_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metal, "gold")
        self.assertAlmostEqual(items[0].unit_oz, 0.1, places=2)

    def test_extracts_decimal_oz(self):
        """Test extracts decimal ounce items."""
        text = "1.5 oz Silver Round"
        items, lines = extract_basic_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metal, "silver")
        self.assertAlmostEqual(items[0].unit_oz, 1.5, places=2)

    def test_extracts_grams(self):
        """Test extracts gram items."""
        text = "31.1 grams Gold"
        items, lines = extract_basic_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].metal, "gold")
        self.assertAlmostEqual(items[0].unit_oz, 1.0, places=1)


class TestDedupeLineItems(unittest.TestCase):
    """Tests for dedupe_line_items function."""

    def test_removes_duplicates(self):
        """Test removes duplicate items."""
        items = [
            LineItem(metal="gold", unit_oz=1.0, qty=1.0, idx=0),
            LineItem(metal="gold", unit_oz=1.0, qty=1.0, idx=0),
        ]
        deduped = dedupe_line_items(items)
        self.assertEqual(len(deduped), 1)

    def test_keeps_different_items(self):
        """Test keeps different items."""
        items = [
            LineItem(metal="gold", unit_oz=1.0, qty=1.0, idx=0),
            LineItem(metal="silver", unit_oz=10.0, qty=1.0, idx=1),
        ]
        deduped = dedupe_line_items(items)
        self.assertEqual(len(deduped), 2)


class TestDataclasses(unittest.TestCase):
    """Tests for dataclass structures."""

    def test_line_item_creation(self):
        """Test LineItem dataclass."""
        item = LineItem(metal="gold", unit_oz=1.0, qty=2.0, idx=5)
        self.assertEqual(item.metal, "gold")
        self.assertEqual(item.unit_oz, 1.0)
        self.assertEqual(item.qty, 2.0)
        self.assertEqual(item.idx, 5)

    def test_price_hit_creation(self):
        """Test PriceHit dataclass."""
        hit = PriceHit(amount=1500.0, kind="unit")
        self.assertEqual(hit.amount, 1500.0)
        self.assertEqual(hit.kind, "unit")


class TestIterNearbyLines(unittest.TestCase):
    """Tests for iter_nearby_lines function."""

    def test_returns_center_line_first(self):
        """Test returns the center line at idx first."""
        result = iter_nearby_lines(LINES_5, 2, window=3)
        self.assertEqual(result[0], (2, "line2"))

    def test_expands_bidirectionally(self):
        """Test expands both forward and backward from idx."""
        result = iter_nearby_lines(LINES_5, 2, window=2)
        indices = [idx for idx, _ in result]
        self.assertIn(1, indices)  # backward
        self.assertIn(3, indices)  # forward

    def test_forward_only_mode(self):
        """Test forward_only=True only searches forward."""
        result = iter_nearby_lines(LINES_5, 2, window=3, forward_only=True)
        indices = [idx for idx, _ in result]
        self.assertIn(2, indices)
        self.assertIn(3, indices)
        self.assertIn(4, indices)
        self.assertNotIn(1, indices)
        self.assertNotIn(0, indices)

    def test_respects_window_size(self):
        """Test respects window parameter."""
        result = iter_nearby_lines(LINES_5, 2, window=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], (2, "line2"))

    def test_handles_boundary_start(self):
        """Test handles idx at start of list."""
        result = iter_nearby_lines(LINES_3, 0, window=3)
        indices = [idx for idx, _ in result]
        self.assertIn(0, indices)
        self.assertIn(1, indices)
        self.assertNotIn(-1, indices)

    def test_handles_boundary_end(self):
        """Test handles idx at end of list."""
        result = iter_nearby_lines(LINES_3, 2, window=3)
        indices = [idx for idx, _ in result]
        self.assertIn(2, indices)
        self.assertIn(1, indices)
        self.assertNotIn(3, indices)

    def test_no_duplicates(self):
        """Test returns no duplicate indices."""
        result = iter_nearby_lines(LINES_5, 2, window=5)
        indices = [idx for idx, _ in result]
        self.assertEqual(len(indices), len(set(indices)))

    def test_empty_lines_handled(self):
        """Test handles empty string lines."""
        lines = ["line0", "", "line2"]
        result = iter_nearby_lines(lines, 1, window=2)
        self.assertEqual(result[0], (1, ""))


class TestExtractPriceFromLines(unittest.TestCase):
    """Tests for extract_price_from_lines function."""

    def test_finds_unit_price(self):
        """Test finds price with 'each' keyword."""
        lines = make_price_lines(price_kind="unit")
        hit = extract_price_from_lines(lines, 0, "gold", 1.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.kind, "unit")
        self.assertAlmostEqual(hit.amount, 2500.0, places=2)

    def test_finds_total_price(self):
        """Test finds price with 'total' keyword."""
        lines = make_price_lines(price_kind="total")
        hit = extract_price_from_lines(lines, 0, "gold", 1.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.kind, "total")

    def test_returns_unknown_for_no_keyword(self):
        """Test returns 'unknown' when no unit/total keyword."""
        lines = make_price_lines(price_kind="unknown")
        hit = extract_price_from_lines(lines, 0, "gold", 1.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.kind, "unknown")

    def test_skips_banned_terms(self):
        """Test skips lines with banned terms like 'shipping'."""
        lines = make_price_lines(item_desc="1 oz Gold", include_banned=True)
        hit = extract_price_from_lines(lines, 0, "gold", 1.0)
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.amount, 2500.0, places=2)

    def test_skips_subtotal(self):
        """Test skips subtotal lines."""
        lines = ["1 oz Gold", "Subtotal: $2,500.00", "Unit: $2,400.00"]
        hit = extract_price_from_lines(lines, 0, "gold", 1.0)
        self.assertIsNotNone(hit)
        self.assertEqual(hit.kind, "unit")
        self.assertAlmostEqual(hit.amount, 2400.0, places=2)

    def test_respects_price_band(self):
        """Test filters prices outside expected band."""
        lines = make_price_lines(price=50.0, price_kind="unknown")  # Too low for 1oz gold
        hit = extract_price_from_lines(lines, 0, "gold", 1.0)
        self.assertIsNone(hit)

    def test_respects_window(self):
        """Test respects window parameter."""
        lines = LINES_3 + ["$2,500.00 gold"]
        hit = extract_price_from_lines(lines, 0, "gold", 1.0, window=2)
        self.assertIsNone(hit)  # Price is at line 3, window=2 won't reach it

    def test_returns_none_when_no_price(self):
        """Test returns None when no price found."""
        lines = ["1 oz Gold Coin", "Beautiful design"]
        hit = extract_price_from_lines(lines, 0, "gold", 1.0)
        self.assertIsNone(hit)

    def test_handles_comma_in_price(self):
        """Test handles prices with commas."""
        lines = make_price_lines(item_desc="Item", price=12500.0, price_kind="unknown")
        hit = extract_price_from_lines(lines, 0, "gold", 5.0)  # ~5oz gold
        self.assertIsNotNone(hit)
        self.assertAlmostEqual(hit.amount, 12500.0, places=2)


if __name__ == '__main__':
    unittest.main()
