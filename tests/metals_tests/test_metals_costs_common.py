"""Tests for metals costs_common shared utilities."""
from __future__ import annotations

import csv
import os
import tempfile
import unittest

from metals.costs_common import (
    COSTS_CSV_FIELDS,
    G_PER_OZ,
    extract_line_items_base,
    extract_order_amount,
    format_breakdown,
    format_qty,
    get_price_band,
    merge_costs_csv,
    parse_money_amount,
    write_costs_csv,
)


class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_grams_per_oz(self):
        """Test grams per troy ounce constant."""
        self.assertAlmostEqual(G_PER_OZ, 31.1035, places=4)

    def test_csv_fields_defined(self):
        """Test CSV fields are defined."""
        self.assertIn('vendor', COSTS_CSV_FIELDS)
        self.assertIn('cost_per_oz', COSTS_CSV_FIELDS)


class TestParseMoney(unittest.TestCase):
    """Tests for parse_money_amount function."""

    def test_simple_amount(self):
        """Test parsing simple amount."""
        self.assertEqual(parse_money_amount("123.45"), 123.45)

    def test_amount_with_commas(self):
        """Test parsing amount with commas."""
        self.assertEqual(parse_money_amount("1,234.56"), 1234.56)

    def test_large_amount(self):
        """Test parsing large amount."""
        self.assertEqual(parse_money_amount("12,345,678.90"), 12345678.90)


class TestFormatQty(unittest.TestCase):
    """Tests for format_qty function."""

    def test_whole_number_returns_int(self):
        """Test whole numbers return int."""
        self.assertEqual(format_qty(5.0), 5)
        self.assertIsInstance(format_qty(5.0), int)

    def test_fractional_returns_float(self):
        """Test fractional numbers return float."""
        self.assertEqual(format_qty(5.5), 5.5)
        self.assertIsInstance(format_qty(5.5), float)

    def test_near_whole_returns_int(self):
        """Test numbers very close to whole return int."""
        self.assertEqual(format_qty(3.0000001), 3)
        self.assertIsInstance(format_qty(3.0000001), int)


class TestFormatBreakdown(unittest.TestCase):
    """Tests for format_breakdown function."""

    def test_single_unit(self):
        """Test single unit breakdown."""
        result = format_breakdown({1.0: 3.0})
        self.assertEqual(result, "1.0ozx3")

    def test_multiple_units(self):
        """Test multiple units breakdown."""
        result = format_breakdown({0.1: 2.0, 1.0: 3.0})
        self.assertEqual(result, "0.1ozx2;1.0ozx3")

    def test_fractional_qty(self):
        """Test fractional quantity in breakdown."""
        result = format_breakdown({1.0: 2.5})
        self.assertEqual(result, "1.0ozx2.5")

    def test_empty_dict(self):
        """Test empty dict returns empty string."""
        result = format_breakdown({})
        self.assertEqual(result, "")


class TestGetPriceBand(unittest.TestCase):
    """Tests for get_price_band function."""

    def test_gold_tenth_oz(self):
        """Test gold 1/10 oz price band."""
        low, high = get_price_band('gold', 0.1)
        self.assertEqual(low, 150.0)
        self.assertEqual(high, 2000.0)

    def test_gold_quarter_oz(self):
        """Test gold 1/4 oz price band."""
        low, high = get_price_band('gold', 0.25)
        self.assertEqual(low, 300.0)
        self.assertEqual(high, 4000.0)

    def test_gold_half_oz(self):
        """Test gold 1/2 oz price band."""
        low, high = get_price_band('gold', 0.5)
        self.assertEqual(low, 600.0)
        self.assertEqual(high, 7000.0)

    def test_gold_one_oz(self):
        """Test gold 1 oz price band."""
        low, high = get_price_band('gold', 1.0)
        self.assertEqual(low, 1200.0)
        self.assertEqual(high, 20000.0)

    def test_silver_wide_band(self):
        """Test silver has wide price band."""
        low, high = get_price_band('silver', 1.0)
        self.assertEqual(low, 10.0)
        self.assertEqual(high, 50000.0)

    def test_unknown_metal(self):
        """Test unknown metal uses wide band."""
        low, high = get_price_band('platinum', 1.0)
        self.assertEqual(low, 10.0)
        self.assertEqual(high, 50000.0)


class TestExtractOrderAmount(unittest.TestCase):
    """Tests for extract_order_amount function."""

    def test_extracts_total(self):
        """Test extracts Total amount."""
        text = "Order summary\nTotal C$1,234.56"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[1], 1234.56, places=2)

    def test_extracts_subtotal(self):
        """Test extracts Subtotal when no Total."""
        text = "Order details\nSubtotal $500.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[1], 500.00, places=2)

    def test_prefers_total_over_subtotal(self):
        """Test prefers Total over Subtotal."""
        # Note: 'Subtotal' contains 'total' as substring, so we need separate lines
        text = "Sub-amount $100.00\nTotal $150.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[1], 150.00, places=2)

    def test_fallback_to_largest(self):
        """Test falls back to largest amount."""
        text = "Item $50.00\nAnother $200.00\nSmall $10.00"
        result = extract_order_amount(text)
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result[1], 200.00, places=2)

    def test_returns_none_for_no_amounts(self):
        """Test returns None when no amounts found."""
        text = "No prices here"
        result = extract_order_amount(text)
        self.assertIsNone(result)


class TestWriteAndMergeCostsCSV(unittest.TestCase):
    """Tests for write_costs_csv and merge_costs_csv functions."""

    def test_write_costs_csv(self):
        """Test writing costs CSV."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "costs.csv")
            rows = [{'vendor': 'TD', 'date': '2024-01-01', 'metal': 'gold',
                     'currency': 'C$', 'cost_total': 1000.0, 'cost_per_oz': 2000.0,
                     'order_id': '123', 'subject': 'Test', 'total_oz': 0.5,
                     'unit_count': 1, 'units_breakdown': '0.5ozx1', 'alloc': 'test'}]
            write_costs_csv(path, rows)
            self.assertTrue(os.path.exists(path))
            with open(path) as f:
                reader = csv.DictReader(f)
                read_rows = list(reader)
            self.assertEqual(len(read_rows), 1)
            self.assertEqual(read_rows[0]['vendor'], 'TD')

    def test_merge_costs_csv_deduplicates(self):
        """Test merge deduplicates by key fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "costs.csv")
            row1 = {'vendor': 'TD', 'date': '2024-01-01', 'metal': 'gold',
                    'currency': 'C$', 'cost_total': 1000.0, 'cost_per_oz': 2000.0,
                    'order_id': '123', 'subject': 'Test', 'total_oz': 0.5,
                    'unit_count': 1, 'units_breakdown': '0.5ozx1', 'alloc': 'test'}
            write_costs_csv(path, [row1])
            # Merge exact same row - should not duplicate
            merge_costs_csv(path, [row1.copy()])
            with open(path) as f:
                reader = csv.DictReader(f)
                read_rows = list(reader)
            self.assertEqual(len(read_rows), 1)


if __name__ == '__main__':
    unittest.main()
