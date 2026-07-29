"""Tests for gmail_costs quantity extraction helpers."""
from __future__ import annotations

import unittest

from metals.gmail_costs import (
    _bundle_qty_near,
    _explicit_qty_near,
    _extract_amount_near_line,
    _extract_first_match_group,
    _extract_line_items,
    _unit_oz_override_near,
    _PAT_QTY_LIST,
)


class TestExtractAmountNearLine(unittest.TestCase):
    """Tests for _extract_amount_near_line function."""

    def test_finds_price_same_line(self):
        """Test finds price on same line as item."""
        lines = ["1 oz Gold Maple Leaf $1,850.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        _, amt, _ = result
        self.assertAlmostEqual(amt, 1850.00)

    def test_finds_price_adjacent_line(self):
        """Test finds price on adjacent line."""
        lines = ["1 oz Gold Maple Leaf", "Price: $1,850.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        _, amt, _ = result
        self.assertAlmostEqual(amt, 1850.00)

    def test_skips_subtotal_line(self):
        """Test skips lines with subtotal."""
        lines = ["1 oz Gold Maple", "Subtotal: $5,000.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_skips_shipping_line(self):
        """Test skips lines with shipping."""
        lines = ["1 oz Gold Maple", "Shipping: $25.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_skips_tax_line(self):
        """Test skips lines with tax."""
        lines = ["1 oz Gold", "Tax: $150.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_detects_unit_price(self):
        """Test detects unit price kind."""
        lines = ["1 oz Gold - Unit Price: $1,800.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        _, _, kind = result
        self.assertEqual(kind, "unit")

    def test_detects_each_price(self):
        """Test detects 'each' as unit price."""
        lines = ["1 oz Silver - each $35.00"]
        result = _extract_amount_near_line(lines, 0, "silver", 1.0, "TD")
        self.assertIsNotNone(result)
        _, _, kind = result
        self.assertEqual(kind, "unit")

    def test_handles_empty_lines(self):
        """Test handles empty lines list."""
        result = _extract_amount_near_line([], 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_handles_out_of_bounds_idx(self):
        """Test handles out of bounds index gracefully."""
        lines = ["Some line"]
        result = _extract_amount_near_line(lines, 10, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_cad_currency_format(self):
        """Test handles CAD currency format."""
        lines = ["1 oz Gold C$2,100.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        cur, amt, _ = result
        self.assertIn("$", cur)
        self.assertAlmostEqual(amt, 2100.00)


class TestBundleAndSKUDetection(unittest.TestCase):
    """Tests for bundle and SKU-based quantity detection."""

    def test_roll_of_25_same_line(self):
        """Test detects roll of 25 on same line."""
        text = "1 oz Silver Maple Leaf roll of 25"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 25.0)

    def test_tube_of_25_same_line(self):
        """Test detects tube of 25 on same line."""
        text = "1 oz Silver Maple tube of 25"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 25.0)

    def test_25_pack_same_line(self):
        """Test detects 25-pack on same line."""
        text = "1 oz Silver Coin 25-pack"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 25.0)

    def test_pack_of_20_same_line(self):
        """Test detects pack of 20 on same line."""
        text = "1 oz Silver Bar pack of 20"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 20.0)

    def test_qty_explicit_same_line(self):
        """Test detects Qty: N format on same line."""
        text = "1 oz Silver Maple Qty: 10"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 10.0)

    def test_quantity_explicit_same_line(self):
        """Test detects Quantity: N format on same line."""
        text = "1 oz Gold Bar Quantity: 5"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 5.0)

    def test_coins_count_same_line(self):
        """Test detects N coins format on same line."""
        text = "1 oz Silver Eagle 10 coins"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 10.0)

    def test_ct_count_same_line(self):
        """Test detects N ct format on same line."""
        text = "1 oz Gold Maple 5 ct"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 5.0)

    def test_sku_bundle_map_same_line(self):
        """Test SKU-based bundle size detection on same line."""
        text = "Item 3796875 1 oz Silver Maple"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 25.0)

    def test_sku_unit_oz_override_silver_same_line(self):
        """Test SKU-based unit oz override for silver on same line."""
        text = "Item 2796876 1 oz Silver Bar"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["unit_oz"], 10.0)

    def test_sku_unit_oz_override_gold_same_line(self):
        """Test SKU-based unit oz override for gold on same line."""
        text = "Item 5882020 1 oz Gold Maple"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertAlmostEqual(items[0]["unit_oz"], 0.25, places=2)

    def test_phrase_override_silver_same_line(self):
        """Test phrase-based unit oz override on same line."""
        text = "Magnificent Maple Leaves Silver Coin 1 oz Silver"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["unit_oz"], 10.0)

    def test_bundle_only_for_1oz_items(self):
        """Test bundle qty only applied to ~1 oz items."""
        text = "10 oz Silver Bar tube of 25"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 1.0)

    def test_explicit_qty_over_bundle(self):
        """Test explicit qty takes precedence over bundle."""
        text = "1 oz Silver Maple x 5 tube of 25"
        items, _ = _extract_line_items(text)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["qty"], 5.0)


class TestExtractAmountNearLineAdvanced(unittest.TestCase):
    """Advanced tests for _extract_amount_near_line function."""

    def test_finds_line_total(self):
        """Test detects line total kind."""
        lines = ["1 oz Gold - Line Total: $3,600.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        _, _, kind = result
        self.assertEqual(kind, "total")

    def test_finds_item_total(self):
        """Test detects item total kind."""
        lines = ["1 oz Silver Item Total: $70.00"]
        result = _extract_amount_near_line(lines, 0, "silver", 1.0, "TD")
        self.assertIsNotNone(result)
        _, _, kind = result
        self.assertEqual(kind, "total")

    def test_per_unit_price(self):
        """Test detects 'per' as unit price."""
        lines = ["1 oz Gold per unit $1,900.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNotNone(result)
        _, _, kind = result
        self.assertEqual(kind, "unit")

    def test_fractional_oz_anchor(self):
        """Test handles fractional oz in anchor matching."""
        lines = ["1/10 oz Gold Eagle $250.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 0.1, "TD")
        self.assertIsNotNone(result)
        _, amt, _ = result
        self.assertAlmostEqual(amt, 250.00)

    def test_costco_vendor_qty_handling(self):
        """Test Costco vendor-specific quantity handling."""
        lines = ["1 oz Silver Maple x 25 $875.00"]
        result = _extract_amount_near_line(lines, 0, "silver", 1.0, "Costco")
        self.assertIsNotNone(result)
        _, _, kind = result
        self.assertEqual(kind, "unit")

    def test_td_vendor_qty_handling(self):
        """Test TD vendor-specific quantity handling."""
        lines = ["1 oz Silver Maple x 10 $350.00"]
        result = _extract_amount_near_line(lines, 0, "silver", 1.0, "TD")
        self.assertIsNotNone(result)
        _, _, kind = result
        self.assertEqual(kind, "total")

    def test_neighbor_uoz_check(self):
        """Test unit-oz check on neighbor line."""
        lines = ["Price: $35.00", "1 oz Silver Maple"]
        result = _extract_amount_near_line(lines, 1, "silver", 1.0, "TD")
        self.assertIsNotNone(result)
        _, amt, _ = result
        self.assertAlmostEqual(amt, 35.00)

    def test_skips_order_number_line(self):
        """Test skips lines with order number."""
        lines = ["1 oz Gold", "Order Number: 123456 $2,000.00"]
        result = _extract_amount_near_line(lines, 0, "gold", 1.0, "TD")
        self.assertIsNone(result)

    def test_none_unit_oz(self):
        """Test handles None unit_oz."""
        lines = ["Gold item Price: $1,800.00"]
        result = _extract_amount_near_line(lines, 0, "gold", None, "TD")
        self.assertIsNotNone(result)
        _, amt, _ = result
        self.assertAlmostEqual(amt, 1800.00)


class TestExtractFirstMatchGroup(unittest.TestCase):
    """Tests for _extract_first_match_group function."""

    def test_finds_match_in_range(self):
        """Test finds matching number within range."""
        pat = _PAT_QTY_LIST[0]
        result = _extract_first_match_group(pat, "Qty: 5", 1, 200)
        self.assertEqual(result, 5.0)

    def test_returns_none_below_range(self):
        """Test returns None when match is below min."""
        pat = _PAT_QTY_LIST[0]
        result = _extract_first_match_group(pat, "Qty: 0", 1, 200)
        self.assertIsNone(result)

    def test_returns_none_above_range(self):
        """Test returns None when match is above max."""
        pat = _PAT_QTY_LIST[0]
        result = _extract_first_match_group(pat, "Qty: 500", 1, 200)
        self.assertIsNone(result)

    def test_returns_none_no_match(self):
        """Test returns None when no match found."""
        pat = _PAT_QTY_LIST[0]
        result = _extract_first_match_group(pat, "no quantity here", 1, 200)
        self.assertIsNone(result)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        pat = _PAT_QTY_LIST[0]
        result = _extract_first_match_group(pat, "", 1, 200)
        self.assertIsNone(result)

    def test_handles_none_text(self):
        """Test handles None text."""
        pat = _PAT_QTY_LIST[0]
        result = _extract_first_match_group(pat, None, 1, 200)
        self.assertIsNone(result)


class TestExplicitQtyNear(unittest.TestCase):
    """Tests for _explicit_qty_near function."""

    def test_finds_qty_same_line(self):
        """Test finds quantity on same line."""
        lines = ["1 oz Silver Qty: 10"]
        result = _explicit_qty_near(lines, 0)
        self.assertEqual(result, 10.0)

    def test_finds_qty_next_line(self):
        """Test finds quantity on next line."""
        lines = ["1 oz Silver", "Qty: 5"]
        result = _explicit_qty_near(lines, 0)
        self.assertEqual(result, 5.0)

    def test_finds_qty_previous_line(self):
        """Test finds quantity on previous line."""
        lines = ["x 3", "1 oz Gold"]
        result = _explicit_qty_near(lines, 1)
        self.assertEqual(result, 3.0)

    def test_returns_none_no_qty(self):
        """Test returns None when no quantity found."""
        lines = ["1 oz Gold Maple Leaf"]
        result = _explicit_qty_near(lines, 0)
        self.assertIsNone(result)

    def test_handles_empty_lines(self):
        """Test handles empty lines list."""
        result = _explicit_qty_near([], 0)
        self.assertIsNone(result)


class TestBundleQtyNear(unittest.TestCase):
    """Tests for _bundle_qty_near function."""

    def test_finds_roll_of(self):
        """Test finds 'roll of N' pattern."""
        lines = ["1 oz Silver roll of 25"]
        result = _bundle_qty_near(lines, 0)
        self.assertEqual(result, 25.0)

    def test_finds_tube_of(self):
        """Test finds 'tube of N' pattern."""
        lines = ["1 oz Gold tube of 20"]
        result = _bundle_qty_near(lines, 0)
        self.assertEqual(result, 20.0)

    def test_finds_pack(self):
        """Test finds 'N-pack' pattern."""
        lines = ["Silver coins 10-pack"]
        result = _bundle_qty_near(lines, 0)
        self.assertEqual(result, 10.0)

    def test_finds_sku_bundle(self):
        """Test finds bundle by SKU mapping."""
        lines = ["Item 3796875 Silver Maple"]
        result = _bundle_qty_near(lines, 0)
        self.assertEqual(result, 25.0)

    def test_returns_none_no_bundle(self):
        """Test returns None when no bundle found."""
        lines = ["1 oz Gold"]
        result = _bundle_qty_near(lines, 0)
        self.assertIsNone(result)

    def test_ignores_qty_of_1(self):
        """Test ignores bundle quantity of 1."""
        lines = ["1 coin Silver"]
        result = _bundle_qty_near(lines, 0)
        self.assertIsNone(result)


class TestUnitOzOverrideNear(unittest.TestCase):
    """Tests for _unit_oz_override_near function."""

    def test_silver_sku_override(self):
        """Test silver SKU override."""
        lines = ["Item 2796876 Silver Bar"]
        result = _unit_oz_override_near(lines, 0, "silver")
        self.assertEqual(result, 10.0)

    def test_gold_sku_override(self):
        """Test gold SKU override."""
        lines = ["Item 5882020 Gold Maple"]
        result = _unit_oz_override_near(lines, 0, "gold")
        self.assertEqual(result, 0.25)

    def test_silver_phrase_override(self):
        """Test silver phrase override."""
        lines = ["Magnificent Maple Leaves Silver Coin"]
        result = _unit_oz_override_near(lines, 0, "silver")
        self.assertEqual(result, 10.0)

    def test_returns_none_no_override(self):
        """Test returns None when no override matches."""
        lines = ["1 oz Gold Maple"]
        result = _unit_oz_override_near(lines, 0, "gold")
        self.assertIsNone(result)

    def test_sku_metal_mismatch(self):
        """Test SKU does not apply when metal does not match."""
        lines = ["Item 2796876 Silver Bar"]
        result = _unit_oz_override_near(lines, 0, "gold")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
