"""Tests for metals outlook_costs extraction module."""
from __future__ import annotations

import csv
import os
import unittest
from unittest.mock import MagicMock, patch

from tests.fixtures import TempDirMixin

from core.text_utils import html_to_text
from metals.costs_common import extract_order_amount, merge_costs_csv
from metals.outlook_costs import (
    _amount_near_item,
    _build_gold_row,
    _classify_subject,
    _compute_confirmation_line_costs,
    _compute_proximity_line_costs,
    _extract_confirmation_item_totals,
    _extract_line_items,
    _extract_order_id,
    _fetch_rcm_message_ids,
    _filter_and_group_by_order,
    _summarize_ounces,
    _trim_disclaimer_lines,
    _try_upgrade_to_confirmation,
    _RCM_QUERIES,
)


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


class TestTrimDisclaimerLines(unittest.TestCase):
    """Tests for _trim_disclaimer_lines function."""

    def test_trims_at_exceptions(self):
        """Test trims at 'exceptions:' line."""
        lines = ["Product info", "Price $100", "Exceptions: See terms", "More terms"]
        result = _trim_disclaimer_lines(lines)
        self.assertEqual(result, ["Product info", "Price $100"])

    def test_trims_at_customer_service(self):
        """Test trims at customer service line."""
        lines = ["Product", "Customer Service Solutions Centre", "Contact us"]
        result = _trim_disclaimer_lines(lines)
        self.assertEqual(result, ["Product"])

    def test_trims_at_returns(self):
        """Test trims at returns line."""
        lines = ["Item 1", "Item 2", "Returns policy", "30 days"]
        result = _trim_disclaimer_lines(lines)
        self.assertEqual(result, ["Item 1", "Item 2"])

    def test_trims_at_refund(self):
        """Test trims at refund line."""
        lines = ["Order", "Refund information", "Details"]
        result = _trim_disclaimer_lines(lines)
        self.assertEqual(result, ["Order"])

    def test_returns_all_when_no_disclaimer(self):
        """Test returns all lines when no disclaimer found."""
        lines = ["Product 1", "Product 2", "Total"]
        result = _trim_disclaimer_lines(lines)
        self.assertEqual(result, lines)

    def test_handles_empty_list(self):
        """Test handles empty list."""
        result = _trim_disclaimer_lines([])
        self.assertEqual(result, [])


class TestSummarizeOunces(unittest.TestCase):
    """Tests for _summarize_ounces function."""

    def test_summarizes_gold_items(self):
        """Test summarizes gold items."""
        items = [{'metal': 'gold', 'unit_oz': 0.1, 'qty': 2}]
        oz, units = _summarize_ounces(items, '')
        self.assertAlmostEqual(oz['gold'], 0.2)
        self.assertEqual(units['gold'], {0.1: 2})

    def test_summarizes_silver_items(self):
        """Test summarizes silver items."""
        items = [{'metal': 'silver', 'unit_oz': 1.0, 'qty': 10}]
        oz, units = _summarize_ounces(items, '')
        self.assertAlmostEqual(oz['silver'], 10.0)
        self.assertEqual(units['silver'], {1.0: 10})

    def test_uses_metal_guess_when_empty(self):
        """Test uses metal_guess when item metal is empty."""
        items = [{'metal': '', 'unit_oz': 0.5, 'qty': 1}]
        oz, units = _summarize_ounces(items, 'gold')
        self.assertAlmostEqual(oz['gold'], 0.5)

    def test_handles_multiple_unit_sizes(self):
        """Test handles multiple unit sizes."""
        items = [
            {'metal': 'gold', 'unit_oz': 0.1, 'qty': 5},
            {'metal': 'gold', 'unit_oz': 0.25, 'qty': 2},
        ]
        oz, units = _summarize_ounces(items, '')
        self.assertAlmostEqual(oz['gold'], 1.0)  # 0.5 + 0.5
        self.assertEqual(units['gold'], {0.1: 5, 0.25: 2})

    def test_handles_empty_items(self):
        """Test handles empty items list."""
        oz, units = _summarize_ounces([], '')
        self.assertEqual(oz, {'gold': 0.0, 'silver': 0.0})


class TestComputeConfirmationLineCosts(unittest.TestCase):
    """Tests for _compute_confirmation_line_costs function."""

    def test_computes_costs_from_totals(self):
        """Test computes costs from Total $X CAD sequence."""
        body = "Product\nTotal $350.00 CAD"
        gold_items = [{'metal': 'gold', 'unit_oz': 0.1, 'qty': 1, 'idx': 0}]
        line_cost, rows = _compute_confirmation_line_costs(body, gold_items, 'PO123', 'Test', '2024-01-15T10:00:00')
        self.assertEqual(line_cost, 350.0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['cost_total'], 350.0)

    def test_skips_out_of_band_prices(self):
        """Test skips prices outside expected band."""
        body = "Product\nTotal $50.00 CAD"  # Too low for gold
        gold_items = [{'metal': 'gold', 'unit_oz': 0.1, 'qty': 1, 'idx': 0}]
        line_cost, rows = _compute_confirmation_line_costs(body, gold_items, 'PO123', 'Test', '2024-01-15')
        self.assertEqual(line_cost, 0.0)
        self.assertEqual(len(rows), 0)

    def test_handles_empty_items(self):
        """Test handles empty gold items."""
        body = "Total $350.00 CAD"
        line_cost, rows = _compute_confirmation_line_costs(body, [], 'PO123', 'Test', '2024-01-15')
        self.assertEqual(line_cost, 0.0)
        self.assertEqual(rows, [])


class TestComputeProximityLineCosts(unittest.TestCase):
    """Tests for _compute_proximity_line_costs function."""

    def test_computes_from_unit_price(self):
        """Test computes cost from unit price."""
        lines = ["1/10 oz Gold Maple", "C$350.00"]
        gold_items = [{'metal': 'gold', 'unit_oz': 0.1, 'qty': 2, 'idx': 0}]
        line_cost = _compute_proximity_line_costs(gold_items, lines)
        self.assertEqual(line_cost, 700.0)  # 350 * 2

    def test_computes_from_total_price(self):
        """Test computes cost from total price."""
        lines = ["1/10 oz Gold Maple", "Total C$350.00"]
        gold_items = [{'metal': 'gold', 'unit_oz': 0.1, 'qty': 1, 'idx': 0}]
        line_cost = _compute_proximity_line_costs(gold_items, lines)
        self.assertEqual(line_cost, 350.0)

    def test_handles_empty_items(self):
        """Test handles empty items."""
        lines = ["C$350.00"]
        line_cost = _compute_proximity_line_costs([], lines)
        self.assertEqual(line_cost, 0.0)


class TestBuildGoldRow(unittest.TestCase):
    """Tests for _build_gold_row function."""

    def test_builds_basic_row(self):
        """Test builds basic gold row."""
        row = _build_gold_row('PO123', 'Test Subject', '2024-01-15T10:00:00', 350.0, 0.1, {0.1: 1.0}, 350.0)
        self.assertEqual(row['vendor'], 'RCM')
        self.assertEqual(row['date'], '2024-01-15')
        self.assertEqual(row['metal'], 'gold')
        self.assertEqual(row['cost_total'], 350.0)
        self.assertEqual(row['cost_per_oz'], 3500.0)
        self.assertEqual(row['order_id'], 'PO123')
        self.assertEqual(row['alloc'], 'line-item')

    def test_alloc_strategy_order_single_metal(self):
        """Test uses order-single-metal when line_cost is 0."""
        row = _build_gold_row('PO123', 'Test', '2024-01-15', 350.0, 0.1, {0.1: 1.0}, 0.0)
        self.assertEqual(row['alloc'], 'order-single-metal')

    def test_formats_breakdown(self):
        """Test formats units breakdown."""
        row = _build_gold_row('PO123', 'Test', '2024-01-15', 700.0, 0.2, {0.1: 2.0}, 700.0)
        self.assertEqual(row['units_breakdown'], '0.1ozx2')
        self.assertEqual(row['unit_count'], 2)

    def test_handles_multiple_unit_sizes(self):
        """Test handles multiple unit sizes in breakdown."""
        row = _build_gold_row('PO123', 'Test', '2024-01-15', 1000.0, 0.35, {0.1: 1.0, 0.25: 1.0}, 1000.0)
        self.assertIn('0.1ozx1', row['units_breakdown'])
        self.assertIn('0.25ozx1', row['units_breakdown'])


class TestRcmQueries(unittest.TestCase):
    """Tests for _RCM_QUERIES constant."""

    def test_queries_defined(self):
        """Test RCM queries are defined."""
        self.assertIsInstance(_RCM_QUERIES, list)
        self.assertGreater(len(_RCM_QUERIES), 0)

    def test_queries_contain_mint_ca(self):
        """Test queries include mint.ca search."""
        self.assertTrue(any('mint.ca' in q.lower() for q in _RCM_QUERIES))

    def test_queries_contain_confirmation(self):
        """Test queries include confirmation search."""
        self.assertTrue(any('confirmation' in q.lower() for q in _RCM_QUERIES))


class TestFetchRcmMessageIds(unittest.TestCase):
    """Tests for _fetch_rcm_message_ids function."""

    @patch("requests.get")
    def test_fetches_and_deduplicates_ids(self, mock_get):
        """Test fetches IDs from multiple queries and deduplicates."""
        mock_cli = MagicMock()
        mock_cli.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_cli._headers_search.return_value = {"Authorization": "Bearer token"}

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "value": [{"id": "msg-1"}, {"id": "msg-2"}],
            "@odata.nextLink": None,
        }
        mock_get.return_value = mock_response

        result = _fetch_rcm_message_ids(mock_cli)
        self.assertIsInstance(result, list)
        self.assertGreaterEqual(mock_get.call_count, len(_RCM_QUERIES))

    @patch("requests.get")
    def test_handles_api_error(self, mock_get):
        """Test handles API errors gracefully."""
        mock_cli = MagicMock()
        mock_cli.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_cli._headers_search.return_value = {}

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_get.return_value = mock_response

        result = _fetch_rcm_message_ids(mock_cli)
        self.assertEqual(result, [])

    @patch("requests.get")
    def test_follows_pagination(self, mock_get):
        """Test follows pagination links."""
        mock_cli = MagicMock()
        mock_cli.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_cli._headers_search.return_value = {}

        responses = [
            MagicMock(status_code=200, json=MagicMock(return_value={
                "value": [{"id": "msg-1"}],
                "@odata.nextLink": "https://next-page",
            })),
            MagicMock(status_code=200, json=MagicMock(return_value={
                "value": [{"id": "msg-2"}],
                "@odata.nextLink": None,
            })),
            MagicMock(status_code=200, json=MagicMock(return_value={
                "value": [],
                "@odata.nextLink": None,
            })),
        ]
        mock_get.side_effect = responses * len(_RCM_QUERIES)

        result = _fetch_rcm_message_ids(mock_cli)
        self.assertIn("msg-1", result)


class TestFilterAndGroupByOrder(unittest.TestCase):
    """Tests for _filter_and_group_by_order function."""

    def test_filters_non_mint_ca_senders(self):
        """Test filters out non-mint.ca senders."""
        mock_cli = MagicMock()
        mock_cli.get_message.return_value = {
            "from": {"emailAddress": {"address": "other@example.com"}},
            "subject": "Test",
            "body": {"content": ""},
            "receivedDateTime": "2024-01-15T10:00:00Z",
        }

        result = _filter_and_group_by_order(mock_cli, ["msg-1"])
        self.assertEqual(result, {})

    def test_groups_by_order_id(self):
        """Test groups messages by order ID."""
        mock_cli = MagicMock()
        mock_cli.get_message.return_value = {
            "from": {"emailAddress": {"address": "email@mint.ca"}},
            "subject": "Confirmation for order number PO1234567",
            "body": {"content": "<p>Order PO1234567</p>"},
            "receivedDateTime": "2024-01-15T10:00:00Z",
        }

        result = _filter_and_group_by_order(mock_cli, ["msg-1"])
        self.assertIn("PO1234567", result)
        self.assertEqual(result["PO1234567"]["cat"], "confirmation")

    def test_prefers_higher_rank_category(self):
        """Test keeps higher-ranked email category."""
        mock_cli = MagicMock()

        def side_effect(mid, select_body=False):
            if mid == "msg-1":
                return {
                    "from": {"emailAddress": {"address": "email@mint.ca"}},
                    "subject": "Shipping for PO1234567",
                    "body": {"content": "<p>PO1234567</p>"},
                    "receivedDateTime": "2024-01-14T10:00:00Z",
                }
            return {
                "from": {"emailAddress": {"address": "email@mint.ca"}},
                "subject": "Confirmation for order number PO1234567",
                "body": {"content": "<p>PO1234567</p>"},
                "receivedDateTime": "2024-01-15T10:00:00Z",
            }

        mock_cli.get_message.side_effect = side_effect

        result = _filter_and_group_by_order(mock_cli, ["msg-1", "msg-2"])
        self.assertEqual(result["PO1234567"]["cat"], "confirmation")


class TestTryUpgradeToConfirmation(unittest.TestCase):
    """Tests for _try_upgrade_to_confirmation function."""

    @patch("requests.get")
    def test_returns_original_when_no_confirmation_found(self, mock_get):
        """Test returns original record when no confirmation found."""
        mock_cli = MagicMock()
        mock_cli.search_inbox_messages.return_value = []
        mock_cli.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_cli._headers_search.return_value = {}

        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"value": []})
        )
        rec = {"id": "msg-1", "cat": "shipping", "sub": "Shipping", "body": "", "recv": ""}
        result = _try_upgrade_to_confirmation(mock_cli, "PO123", rec)
        self.assertEqual(result, rec)

    def test_upgrades_when_confirmation_found(self):
        """Test upgrades to confirmation when found."""
        mock_cli = MagicMock()
        mock_cli.search_inbox_messages.return_value = ["conf-msg"]
        mock_cli.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_cli.get_message.side_effect = [
            {"subject": "Confirmation for order number PO123"},
            {
                "subject": "Confirmation for order number PO123",
                "body": {"content": "<p>Confirmed</p>"},
                "receivedDateTime": "2024-01-15T10:00:00Z",
            },
        ]

        rec = {"id": "msg-1", "cat": "shipping", "sub": "Shipping", "body": "", "recv": ""}
        result = _try_upgrade_to_confirmation(mock_cli, "PO123", rec)
        self.assertEqual(result["cat"], "confirmation")
        self.assertIn("Confirmation", result["sub"])

    @patch("requests.get")
    def test_handles_search_exception(self, mock_get):
        """Test handles exception during inbox search."""
        mock_cli = MagicMock()
        mock_cli.search_inbox_messages.side_effect = Exception("API error")
        mock_cli.GRAPH = "https://graph.microsoft.com/v1.0"
        mock_cli._headers_search.return_value = {}

        mock_get.return_value = MagicMock(
            status_code=200,
            json=MagicMock(return_value={"value": []})
        )
        rec = {"id": "msg-1", "cat": "shipping"}
        result = _try_upgrade_to_confirmation(mock_cli, "PO123", rec)
        self.assertEqual(result, rec)


if __name__ == "__main__":
    unittest.main()
