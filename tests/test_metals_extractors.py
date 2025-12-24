"""Unit tests for metals extractors."""

import unittest

from metals.extractors import (
    MetalsAmount,
    extract_amounts,
    extract_order_id,
    normalize_text,
    G_PER_OZ,
)


class TestMetalsAmount(unittest.TestCase):
    """Tests for MetalsAmount dataclass."""

    def test_default_values(self):
        amt = MetalsAmount()
        self.assertEqual(amt.gold_oz, 0.0)
        self.assertEqual(amt.silver_oz, 0.0)

    def test_addition(self):
        a = MetalsAmount(gold_oz=1.0, silver_oz=2.0)
        b = MetalsAmount(gold_oz=0.5, silver_oz=1.5)
        result = a + b
        self.assertEqual(result.gold_oz, 1.5)
        self.assertEqual(result.silver_oz, 3.5)

    def test_has_metals_true(self):
        self.assertTrue(MetalsAmount(gold_oz=1.0).has_metals())
        self.assertTrue(MetalsAmount(silver_oz=1.0).has_metals())
        self.assertTrue(MetalsAmount(gold_oz=0.5, silver_oz=0.5).has_metals())

    def test_has_metals_false(self):
        self.assertFalse(MetalsAmount().has_metals())
        self.assertFalse(MetalsAmount(gold_oz=0.0, silver_oz=0.0).has_metals())


class TestNormalizeText(unittest.TestCase):
    """Tests for normalize_text function."""

    def test_replaces_unicode_dashes(self):
        # en-dash and em-dash
        text = "1\u20132 oz Gold \u2014 Silver"
        result = normalize_text(text)
        self.assertEqual(result, "1-2 oz Gold - Silver")

    def test_handles_none(self):
        self.assertEqual(normalize_text(None), "")

    def test_handles_empty_string(self):
        self.assertEqual(normalize_text(""), "")


class TestExtractOrderId(unittest.TestCase):
    """Tests for extract_order_id function."""

    def test_extracts_from_subject(self):
        subject = "Your Order #123456789 has shipped"
        self.assertEqual(extract_order_id(subject, ""), "123456789")

    def test_extracts_from_body(self):
        body = "Thank you for order 987654321"
        self.assertEqual(extract_order_id("", body), "987654321")

    def test_subject_takes_precedence(self):
        subject = "Order #111111111"
        body = "Order #222222222"
        self.assertEqual(extract_order_id(subject, body), "111111111")

    def test_returns_none_when_not_found(self):
        self.assertIsNone(extract_order_id("No order here", "Nothing"))

    def test_requires_minimum_digits(self):
        # Less than 6 digits should not match
        self.assertIsNone(extract_order_id("Order #12345", ""))


class TestExtractAmounts(unittest.TestCase):
    """Tests for extract_amounts function."""

    def test_extracts_decimal_oz_gold(self):
        text = "1 oz Gold Maple Leaf"
        result = extract_amounts(text)
        self.assertEqual(result.gold_oz, 1.0)
        self.assertEqual(result.silver_oz, 0.0)

    def test_extracts_decimal_oz_silver(self):
        text = "10 oz Silver Bar"
        result = extract_amounts(text)
        self.assertEqual(result.gold_oz, 0.0)
        self.assertEqual(result.silver_oz, 10.0)

    def test_extracts_fractional_oz(self):
        text = "1/10 oz Gold Eagle"
        result = extract_amounts(text)
        self.assertAlmostEqual(result.gold_oz, 0.1, places=3)

    def test_extracts_with_quantity(self):
        text = "1 oz Silver Maple x 5"
        result = extract_amounts(text)
        self.assertEqual(result.silver_oz, 5.0)

    def test_extracts_fractional_with_quantity(self):
        text = "1/4 oz Gold Coin x 4"
        result = extract_amounts(text)
        self.assertAlmostEqual(result.gold_oz, 1.0, places=3)

    def test_extracts_grams(self):
        text = f"{G_PER_OZ} g Gold Bar"
        result = extract_amounts(text)
        self.assertAlmostEqual(result.gold_oz, 1.0, places=3)

    def test_extracts_multiple_items(self):
        text = """
        1 oz Gold Maple Leaf
        10 oz Silver Bar
        1/10 oz Gold Eagle x 5
        """
        result = extract_amounts(text)
        self.assertAlmostEqual(result.gold_oz, 1.5, places=3)  # 1 + 0.5
        self.assertEqual(result.silver_oz, 10.0)

    def test_avoids_double_counting(self):
        # Same item repeated should only count once
        text = """
        1 oz Gold Coin
        1 oz Gold Coin
        """
        result = extract_amounts(text)
        self.assertEqual(result.gold_oz, 1.0)

    def test_case_insensitive(self):
        text = "1 OZ GOLD BAR"
        result = extract_amounts(text)
        self.assertEqual(result.gold_oz, 1.0)

    def test_handles_empty_text(self):
        result = extract_amounts("")
        self.assertEqual(result.gold_oz, 0.0)
        self.assertEqual(result.silver_oz, 0.0)

    def test_handles_no_metals(self):
        text = "Your order has been shipped"
        result = extract_amounts(text)
        self.assertFalse(result.has_metals())

    def test_decimal_ounces(self):
        text = "0.5 oz Gold Bar"
        result = extract_amounts(text)
        self.assertEqual(result.gold_oz, 0.5)

    def test_does_not_match_10_from_1_10(self):
        # Ensure "1/10 oz" doesn't also match as "10 oz"
        text = "1/10 oz Gold Eagle"
        result = extract_amounts(text)
        self.assertAlmostEqual(result.gold_oz, 0.1, places=3)


class TestExtractAmountsVendorPatterns(unittest.TestCase):
    """Tests for vendor-specific email patterns."""

    def test_td_precious_metals_pattern(self):
        text = """
        TD Precious Metals Order Confirmation
        1 oz Gold Maple Leaf - CAD $2,500.00
        10 oz Silver Bar - CAD $350.00
        """
        result = extract_amounts(text)
        self.assertEqual(result.gold_oz, 1.0)
        self.assertEqual(result.silver_oz, 10.0)

    def test_costco_pattern(self):
        text = """
        Your Costco.ca Order
        1 oz Gold Bar x 2
        1 oz Silver Coin x 10
        """
        result = extract_amounts(text)
        self.assertEqual(result.gold_oz, 2.0)
        self.assertEqual(result.silver_oz, 10.0)

    def test_rcm_pattern(self):
        text = """
        Royal Canadian Mint Order
        1/4 oz 99.99% Pure Gold Coin
        1 oz 99.99% Pure Silver Maple Leaf x 25
        """
        result = extract_amounts(text)
        self.assertAlmostEqual(result.gold_oz, 0.25, places=3)
        self.assertEqual(result.silver_oz, 25.0)


if __name__ == "__main__":
    unittest.main()
