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
    find_bundle_qty,
    find_qty_near,
    get_vendor_for_sender,
    infer_metal_from_context,
    iter_nearby_lines,
    _parse_weight_match,
    _WEIGHT_PATTERNS,
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


class TestParseWeightMatch(unittest.TestCase):
    """Tests for _parse_weight_match helper function."""

    def test_parses_fractional_oz(self):
        """Test parses fractional ounce pattern."""
        pat, _ = _WEIGHT_PATTERNS[0]  # PAT_FRAC_OZ
        m = pat.search("1/10 oz gold x 5")
        result = _parse_weight_match(m, 'frac')
        self.assertIsNotNone(result)
        unit_oz, metal, qty = result
        self.assertAlmostEqual(unit_oz, 0.1, places=2)
        self.assertEqual(metal, "gold")
        self.assertEqual(qty, 5.0)

    def test_parses_decimal_oz(self):
        """Test parses decimal ounce pattern."""
        pat, _ = _WEIGHT_PATTERNS[1]  # PAT_DECIMAL_OZ
        m = pat.search("1.5 oz silver x 3")
        result = _parse_weight_match(m, 'decimal')
        self.assertIsNotNone(result)
        unit_oz, metal, qty = result
        self.assertAlmostEqual(unit_oz, 1.5, places=2)
        self.assertEqual(metal, "silver")
        self.assertEqual(qty, 3.0)

    def test_parses_grams(self):
        """Test parses grams pattern."""
        pat, _ = _WEIGHT_PATTERNS[2]  # PAT_GRAMS
        m = pat.search("31.1 grams gold")
        result = _parse_weight_match(m, 'grams')
        self.assertIsNotNone(result)
        unit_oz, metal, qty = result
        self.assertAlmostEqual(unit_oz, 1.0, places=1)
        self.assertEqual(metal, "gold")

    def test_returns_none_for_invalid_type(self):
        """Test returns None for unknown pattern type."""
        pat, _ = _WEIGHT_PATTERNS[0]
        m = pat.search("1/10 oz gold")
        result = _parse_weight_match(m, 'invalid')
        self.assertIsNone(result)

    def test_defaults_qty_to_one(self):
        """Test defaults quantity to 1 when not specified."""
        pat, _ = _WEIGHT_PATTERNS[1]
        m = pat.search("1 oz gold")
        result = _parse_weight_match(m, 'decimal')
        self.assertIsNotNone(result)
        _, _, qty = result
        self.assertEqual(qty, 1.0)


class TestFindBundleQty(unittest.TestCase):
    """Tests for find_bundle_qty shared function."""

    def test_finds_pack_pattern(self):
        """Test finds X-pack pattern."""
        lines = ["1 oz Silver", "25-pack", "Price"]
        qty = find_bundle_qty(lines, 0)
        self.assertEqual(qty, 25.0)

    def test_finds_pack_of_pattern(self):
        """Test finds pack of X pattern."""
        lines = ["1 oz Silver", "pack of 20", "Price"]
        qty = find_bundle_qty(lines, 0)
        self.assertEqual(qty, 20.0)

    def test_finds_coins_pattern(self):
        """Test finds X coins pattern."""
        lines = ["1 oz Gold", "10 coins", "Price"]
        qty = find_bundle_qty(lines, 0)
        self.assertEqual(qty, 10.0)

    def test_finds_roll_of_pattern(self):
        """Test finds roll of X pattern."""
        lines = ["Silver Eagle", "roll of 25", "Price"]
        qty = find_bundle_qty(lines, 0)
        self.assertEqual(qty, 25.0)

    def test_finds_tube_of_pattern(self):
        """Test finds tube of X pattern."""
        lines = ["Silver Maple", "tube of 25", "Price"]
        qty = find_bundle_qty(lines, 0)
        self.assertEqual(qty, 25.0)

    def test_uses_sku_map(self):
        """Test uses SKU mapping when provided."""
        lines = ["Item #: 3796875", "1 oz Silver"]
        sku_map = {"3796875": 25.0}
        qty = find_bundle_qty(lines, 1, sku_map=sku_map)
        self.assertEqual(qty, 25.0)

    def test_ignores_qty_of_one(self):
        """Test ignores bundle qty of 1."""
        lines = ["1 oz Gold", "1 coin", "Price"]
        qty = find_bundle_qty(lines, 0)
        self.assertIsNone(qty)

    def test_returns_none_when_not_found(self):
        """Test returns None when no bundle found."""
        lines = ["1 oz Gold", "Price: $2500"]
        qty = find_bundle_qty(lines, 0)
        self.assertIsNone(qty)

    def test_respects_window(self):
        """Test respects window parameter."""
        lines = ["1 oz Silver", "Line 1", "Line 2", "Line 3", "25-pack"]
        qty = find_bundle_qty(lines, 0, window=2)
        self.assertIsNone(qty)

    def test_finds_ct_pattern(self):
        """Test finds X ct pattern."""
        lines = ["1 oz Silver", "25 ct", "Price"]
        qty = find_bundle_qty(lines, 0)
        self.assertEqual(qty, 25.0)


class TestRCMParserExtractWeights(unittest.TestCase):
    """Tests for RCMParser._extract_weights method."""

    def setUp(self):
        self.parser = RCMParser()

    def test_extracts_fractional_oz(self):
        """Test extracts fractional ounce weights."""
        weights = self.parser._extract_weights("1/4 oz Gold Maple")
        self.assertEqual(len(weights), 1)
        self.assertAlmostEqual(weights[0], 0.25, places=2)

    def test_extracts_decimal_oz(self):
        """Test extracts decimal ounce weights."""
        weights = self.parser._extract_weights("1.5 oz Silver Bar")
        self.assertEqual(len(weights), 1)
        self.assertAlmostEqual(weights[0], 1.5, places=2)

    def test_extracts_grams(self):
        """Test extracts gram weights and converts to oz."""
        weights = self.parser._extract_weights("31.1 grams Gold")
        self.assertEqual(len(weights), 1)
        self.assertAlmostEqual(weights[0], 1.0, places=1)

    def test_extracts_multiple_weights(self):
        """Test extracts multiple weights from same line."""
        weights = self.parser._extract_weights("1 oz and 10 oz options")
        self.assertGreaterEqual(len(weights), 1)

    def test_returns_empty_for_no_weights(self):
        """Test returns empty list when no weights found."""
        weights = self.parser._extract_weights("No weights here")
        self.assertEqual(weights, [])


class TestRCMParserClassifyEmailLookup(unittest.TestCase):
    """Tests for RCMParser classify_email with lookup table."""

    def setUp(self):
        self.parser = RCMParser()

    def test_classify_all_types(self):
        """Test classifies all email types via lookup."""
        cases = [
            ("Confirmation for order number PO123", "confirmation", 3),
            ("Confirmation for order PO456", "confirmation", 3),
            ("Your order was shipped", "shipping", 2),
            ("Shipping update: was shipped today", "shipping", 2),
            ("We received your request", "request", 1),
            ("Random subject line", "other", 0),
        ]
        for subject, expected_type, expected_rank in cases:
            with self.subTest(subject=subject):
                cat, rank = self.parser.classify_email(subject)
                self.assertEqual(cat, expected_type)
                self.assertEqual(rank, expected_rank)

    def test_case_insensitive(self):
        """Test classification is case insensitive."""
        cat, rank = self.parser.classify_email("CONFIRMATION FOR ORDER NUMBER")
        self.assertEqual(cat, "confirmation")


class TestRCMParserSubjectRank(unittest.TestCase):
    """Tests for RCMParser.SUBJECT_RANK attribute."""

    def test_subject_rank_exists(self):
        """Test SUBJECT_RANK class attribute exists."""
        self.assertTrue(hasattr(RCMParser, 'SUBJECT_RANK'))

    def test_subject_rank_values(self):
        """Test SUBJECT_RANK has expected values."""
        rank = RCMParser.SUBJECT_RANK
        self.assertEqual(rank['confirmation'], 3)
        self.assertEqual(rank['shipping'], 2)
        self.assertEqual(rank['request'], 1)
        self.assertEqual(rank['other'], 0)


class TestWeightPatternsList(unittest.TestCase):
    """Tests for _WEIGHT_PATTERNS configuration."""

    def test_has_three_patterns(self):
        """Test _WEIGHT_PATTERNS has three pattern configs."""
        self.assertEqual(len(_WEIGHT_PATTERNS), 3)

    def test_pattern_types(self):
        """Test pattern type keys are correct."""
        types = [ptype for _, ptype in _WEIGHT_PATTERNS]
        self.assertEqual(types, ['frac', 'decimal', 'grams'])


class TestExtractBasicLineItemsConsolidated(unittest.TestCase):
    """Additional tests for extract_basic_line_items using consolidated patterns."""

    def test_extracts_all_pattern_types(self):
        """Test extracts items from all pattern types in one text."""
        text = """
        1/10 oz Gold Eagle
        1.5 oz Silver Round
        31 grams Gold Bar
        """
        items, lines = extract_basic_line_items(text)
        self.assertGreaterEqual(len(items), 3)

    def test_multiple_items_same_line(self):
        """Test handles multiple patterns on same line."""
        text = "Buy 1 oz gold or 10 oz silver"
        items, lines = extract_basic_line_items(text)
        self.assertEqual(len(items), 2)

    def test_handles_mixed_case(self):
        """Test handles mixed case metal names."""
        cases = [
            ("1 oz GOLD", "gold"),
            ("1 oz Gold", "gold"),
            ("1 oz SILVER", "silver"),
        ]
        for text, expected_metal in cases:
            with self.subTest(text=text):
                items, _ = extract_basic_line_items(text)
                self.assertEqual(len(items), 1)
                self.assertEqual(items[0].metal, expected_metal)


if __name__ == '__main__':
    unittest.main()
