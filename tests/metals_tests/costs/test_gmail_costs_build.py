"""Tests for gmail_costs build-level helpers (patterns, anchored extraction, price kind, allocations)."""
from __future__ import annotations

import unittest

from metals.gmail_costs_extract import (
    OrderRowData,
    _allocate_costs,
    _build_order_rows,
    _compute_line_costs,
)
from metals.gmail_costs_qty_items import (
    ExtractionContext,
    _build_uoz_patterns,
)
from metals.gmail_costs_qty_price import (
    _determine_price_kind,
    _try_anchored_extraction,
)


class TestBuildUozPatterns(unittest.TestCase):
    """Tests for _build_uoz_patterns function."""

    def test_builds_pattern_for_whole_oz(self):
        """Test builds pattern for whole oz."""
        pat, texts = _build_uoz_patterns(1.0)
        self.assertIsNotNone(pat)
        self.assertTrue(pat.search("1 oz"))
        self.assertEqual(len(texts), 1)

    def test_builds_pattern_for_fractional_oz(self):
        """Test builds pattern including fraction for sub-oz."""
        pat, texts = _build_uoz_patterns(0.1)
        self.assertIsNotNone(pat)
        self.assertEqual(len(texts), 2)

    def test_returns_none_for_zero(self):
        """Test returns None pattern for zero oz."""
        pat, texts = _build_uoz_patterns(0.0)
        self.assertIsNone(pat)
        self.assertEqual(texts, [])

    def test_returns_none_for_none(self):
        """Test returns None pattern for None input."""
        pat, texts = _build_uoz_patterns(None)
        self.assertIsNone(pat)
        self.assertEqual(texts, [])


class TestTryAnchoredExtraction(unittest.TestCase):
    """Tests for _try_anchored_extraction function."""

    def test_extracts_from_compact_line(self):
        """Test extracts price from compact line."""
        ln = "1 oz Gold Maple $1,850.00"
        ctx = ExtractionContext(ln=ln, lower=ln.lower(), metal="gold", unit_oz=1.0, uoz_texts=[r"\b1\s*oz\b"], vendor="td")
        result = _try_anchored_extraction(ctx)
        self.assertIsNotNone(result)
        _, amt, _ = result
        self.assertAlmostEqual(amt, 1850.00)

    def test_returns_none_for_invalid_metal(self):
        """Test returns None for invalid metal."""
        ln = "1 oz Platinum $500.00"
        ctx = ExtractionContext(ln=ln, lower=ln.lower(), metal="platinum", unit_oz=1.0, uoz_texts=[r"\b1\s*oz\b"], vendor="td")
        result = _try_anchored_extraction(ctx)
        self.assertIsNone(result)

    def test_returns_none_for_empty_uoz_texts(self):
        """Test returns None for empty uoz_texts."""
        ln = "1 oz Gold $1,850.00"
        ctx = ExtractionContext(ln=ln, lower=ln.lower(), metal="gold", unit_oz=1.0, uoz_texts=[], vendor="td")
        result = _try_anchored_extraction(ctx)
        self.assertIsNone(result)

    def test_returns_none_when_price_too_far(self):
        """Test returns None when price is too far from anchor."""
        ln = "1 oz Gold " + "x" * 100 + " $1,850.00"
        ctx = ExtractionContext(ln=ln, lower=ln.lower(), metal="gold", unit_oz=1.0, uoz_texts=[r"\b1\s*oz\b"], vendor="td")
        result = _try_anchored_extraction(ctx)
        self.assertIsNone(result)


class TestDeterminePriceKind(unittest.TestCase):
    """Tests for _determine_price_kind function."""

    def test_unit_kind(self):
        """Test detects unit kind."""
        kind, mp, _ = _determine_price_kind("unit price $50", False, False)
        self.assertEqual(kind, "unit")
        self.assertTrue(mp)

    def test_each_kind(self):
        """Test detects each as unit kind."""
        kind, mp, _ = _determine_price_kind("$50 each", False, False)
        self.assertEqual(kind, "unit")
        self.assertTrue(mp)

    def test_line_total_kind(self):
        """Test detects line total kind."""
        kind, mp, mt = _determine_price_kind("line total $100", False, False)
        self.assertEqual(kind, "total")
        self.assertFalse(mp)
        self.assertTrue(mt)

    def test_item_total_kind(self):
        """Test detects item total kind."""
        kind, _, _ = _determine_price_kind("item total $100", False, False)
        self.assertEqual(kind, "total")

    def test_total_with_uoz_context(self):
        """Test total with unit-oz context."""
        kind, _, _ = _determine_price_kind("total $100", True, False)
        self.assertEqual(kind, "total")

    def test_unknown_kind(self):
        """Test defaults to unknown kind."""
        kind, _, _ = _determine_price_kind("$100.00", False, False)
        self.assertEqual(kind, "unknown")


class TestComputeLineCosts(unittest.TestCase):
    """Tests for _compute_line_costs function."""

    def test_computes_from_total_hit(self):
        """Test computes cost from total hit."""
        final_qty = {("gold", 1.0): 2.0}
        price_hits = {("gold", 1.0): [(3600.0, "total")]}
        result = _compute_line_costs(final_qty, price_hits, "TD")
        self.assertEqual(result["gold"], 3600.0)

    def test_computes_from_unit_hit(self):
        """Test computes cost from unit hit (multiplied by qty)."""
        final_qty = {("silver", 1.0): 10.0}
        price_hits = {("silver", 1.0): [(35.0, "unit")]}
        result = _compute_line_costs(final_qty, price_hits, "TD")
        self.assertEqual(result["silver"], 350.0)

    def test_costco_silver_heuristic(self):
        """Test Costco silver heuristic for high per-oz price."""
        final_qty = {("silver", 1.0): 25.0}
        price_hits = {("silver", 1.0): [(875.0, "unknown")]}
        result = _compute_line_costs(final_qty, price_hits, "Costco")
        self.assertEqual(result["silver"], 875.0)

    def test_handles_empty_hits(self):
        """Test handles empty price hits."""
        final_qty = {("gold", 1.0): 1.0}
        price_hits = {}
        result = _compute_line_costs(final_qty, price_hits, "TD")
        self.assertEqual(result["gold"], 0.0)


class TestAllocateCosts(unittest.TestCase):
    """Tests for _allocate_costs function."""

    def test_single_metal_uses_order_total(self):
        """Test single metal order uses order total."""
        oz = {"gold": 1.0, "silver": 0.0}
        line_cost = {"gold": 0.0, "silver": 0.0}
        alloc, strategy = _allocate_costs(oz, line_cost, 1800.0, "TD")
        self.assertEqual(alloc["gold"], 1800.0)
        self.assertEqual(strategy, "order-single-metal")

    def test_line_item_allocation(self):
        """Test line-item allocation when costs available."""
        oz = {"gold": 1.0, "silver": 10.0}
        line_cost = {"gold": 1800.0, "silver": 350.0}
        alloc, strategy = _allocate_costs(oz, line_cost, 2150.0, "Other")
        self.assertEqual(alloc["gold"], 1800.0)
        self.assertEqual(alloc["silver"], 350.0)
        self.assertEqual(strategy, "line-item")

    def test_proportional_allocation(self):
        """Test proportional allocation as fallback."""
        oz = {"gold": 1.0, "silver": 10.0}
        line_cost = {"gold": 0.0, "silver": 0.0}
        alloc, strategy = _allocate_costs(oz, line_cost, 1100.0, "Other")
        self.assertAlmostEqual(alloc["gold"], 100.0, places=1)
        self.assertAlmostEqual(alloc["silver"], 1000.0, places=1)
        self.assertEqual(strategy, "order-proportional")

    def test_td_remainder_to_silver(self):
        """Test TD allocates remainder to silver for mixed orders."""
        oz = {"gold": 0.5, "silver": 10.0}
        line_cost = {"gold": 1200.0, "silver": 0.0}
        alloc, _ = _allocate_costs(oz, line_cost, 1550.0, "TD")
        self.assertEqual(alloc["gold"], 1200.0)
        self.assertEqual(alloc["silver"], 350.0)


class TestBuildOrderRows(unittest.TestCase):
    """Tests for _build_order_rows function."""

    def test_builds_single_metal_row(self):
        """Test builds row for single metal."""
        data = OrderRowData(
            oid="123", vendor="TD", subject="Test Order", cur="C$", dt="2024-01-15",
            oz_by_metal={"gold": 1.0, "silver": 0.0},
            units_by_metal={"gold": {1.0: 1.0}, "silver": {}},
            cost_alloc={"gold": 1800.0, "silver": 0.0},
            alloc_strategy="order-single-metal"
        )
        rows = _build_order_rows(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metal"], "gold")
        self.assertEqual(rows[0]["cost_total"], 1800.0)
        self.assertEqual(rows[0]["cost_per_oz"], 1800.0)

    def test_builds_multi_metal_rows(self):
        """Test builds rows for multiple metals."""
        data = OrderRowData(
            oid="456", vendor="Costco", subject="Multi Order", cur="C$", dt="2024-01-16",
            oz_by_metal={"gold": 0.25, "silver": 25.0},
            units_by_metal={"gold": {0.25: 1.0}, "silver": {1.0: 25.0}},
            cost_alloc={"gold": 700.0, "silver": 875.0},
            alloc_strategy="line-item"
        )
        rows = _build_order_rows(data)
        self.assertEqual(len(rows), 2)
        metals = [r["metal"] for r in rows]
        self.assertIn("gold", metals)
        self.assertIn("silver", metals)

    def test_skips_zero_oz_metals(self):
        """Test skips metals with zero ounces."""
        data = OrderRowData(
            oid="789", vendor="TD", subject="Gold Only", cur="C$", dt="2024-01-17",
            oz_by_metal={"gold": 2.0, "silver": 0.0},
            units_by_metal={"gold": {1.0: 2.0}, "silver": {}},
            cost_alloc={"gold": 3600.0, "silver": 0.0},
            alloc_strategy="order-single-metal"
        )
        rows = _build_order_rows(data)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metal"], "gold")

    def test_currency_override_for_canadian_vendors(self):
        """Test Canadian vendors use C$ currency."""
        data = OrderRowData(
            oid="abc", vendor="Costco", subject="Test", cur="$", dt="2024-01-18",
            oz_by_metal={"gold": 0.0, "silver": 1.0},
            units_by_metal={"gold": {}, "silver": {1.0: 1.0}},
            cost_alloc={"gold": 0.0, "silver": 35.0},
            alloc_strategy="line-item"
        )
        rows = _build_order_rows(data)
        self.assertEqual(rows[0]["currency"], "C$")


if __name__ == "__main__":
    unittest.main()
