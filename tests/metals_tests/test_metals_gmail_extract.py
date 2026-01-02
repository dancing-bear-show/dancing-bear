"""Tests for metals gmail_extract module."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from metals.gmail_extract import (
    G_PER_OZ,
    _extract_amounts,
    run,
    main,
)
from tests.metals_tests.fixtures import make_mock_gmail_client


class TestConstants(unittest.TestCase):
    """Tests for module constants."""

    def test_grams_per_oz(self):
        """Test grams per troy ounce constant."""
        self.assertAlmostEqual(G_PER_OZ, 31.1035, places=4)


class TestExtractAmounts(unittest.TestCase):
    """Tests for _extract_amounts function."""

    def test_extracts_oz_gold(self):
        """Test extracts ounce gold amounts."""
        text = "Your order contains 1 oz Gold Maple Leaf"
        gold, silver = _extract_amounts(text)
        self.assertEqual(gold, 1.0)
        self.assertEqual(silver, 0.0)

    def test_extracts_oz_silver(self):
        """Test extracts ounce silver amounts."""
        text = "10 oz Silver Bar - PAMP Suisse"
        gold, silver = _extract_amounts(text)
        self.assertEqual(gold, 0.0)
        self.assertEqual(silver, 10.0)

    def test_extracts_fractional_oz(self):
        """Test extracts fractional ounce amounts."""
        text = "1/10 oz Gold Eagle x 5"
        gold, silver = _extract_amounts(text)
        self.assertEqual(gold, 0.5)
        self.assertEqual(silver, 0.0)

    def test_extracts_with_quantity(self):
        """Test extracts amounts with quantity multiplier."""
        text = "1 oz Silver Maple Leaf x 10"
        gold, silver = _extract_amounts(text)
        self.assertEqual(gold, 0.0)
        self.assertEqual(silver, 10.0)

    def test_extracts_grams(self):
        """Test extracts gram amounts."""
        text = f"{G_PER_OZ} g Gold Bar"
        gold, silver = _extract_amounts(text)
        self.assertAlmostEqual(gold, 1.0, places=2)
        self.assertEqual(silver, 0.0)

    def test_extracts_multiple_items(self):
        """Test extracts multiple items from text."""
        text = """
        1 oz Gold Maple Leaf x 2
        10 oz Silver Bar x 1
        1/4 oz Gold Eagle x 4
        """
        gold, silver = _extract_amounts(text)
        self.assertEqual(gold, 3.0)  # 2 + 1 = 3 oz
        self.assertEqual(silver, 10.0)

    def test_handles_empty_text(self):
        """Test handles empty text."""
        gold, silver = _extract_amounts("")
        self.assertEqual(gold, 0.0)
        self.assertEqual(silver, 0.0)

    def test_handles_none_text(self):
        """Test handles None text."""
        gold, silver = _extract_amounts(None)
        self.assertEqual(gold, 0.0)
        self.assertEqual(silver, 0.0)

    def test_handles_unicode_dashes(self):
        """Test handles unicode dashes in text."""
        # en-dash and em-dash should be normalized
        text = "1 oz Gold \u2013 Maple Leaf"  # en-dash
        gold, silver = _extract_amounts(text)
        self.assertEqual(gold, 1.0)

    def test_deduplicates_same_item(self):
        """Test deduplicates same item appearing multiple times."""
        text = """
        1 oz Gold Maple x 2
        1 oz Gold Maple x 2
        """
        gold, silver = _extract_amounts(text)
        # Should only count once due to deduplication
        self.assertEqual(gold, 2.0)

    def test_case_insensitive(self):
        """Test case insensitive matching."""
        text = "1 OZ GOLD MAPLE LEAF"
        gold, silver = _extract_amounts(text)
        self.assertEqual(gold, 1.0)


class TestRun(unittest.TestCase):
    """Tests for run function."""

    @patch("metals.gmail_extract.GmailClient")
    @patch("metals.gmail_extract.resolve_paths_profile")
    def test_run_success(self, mock_resolve, mock_client_class):
        """Test successful run."""
        mock_resolve.return_value = ("cred.json", "token.json")

        # Create mock client with fixture
        mock_client = make_mock_gmail_client(
            message_ids=["msg1", "msg2"],
            messages={
                "msg1": {"id": "msg1", "internalDate": "1704067200000"},
                "msg2": {"id": "msg2", "internalDate": "1704153600000"},
            }
        )
        mock_client_class.return_value = mock_client
        mock_client_class.headers_to_dict.return_value = {"subject": "Order #123456"}

        # Mock message text extraction
        mock_client.get_message_text.side_effect = [
            "1 oz Gold x 2",
            "10 oz Silver x 1",
            "1 oz Gold x 2",  # Second call for same msg
            "10 oz Silver x 1",
        ]

        result = run(profile="test", days=30)
        self.assertEqual(result, 0)
        mock_client.authenticate.assert_called_once()

    @patch("metals.gmail_extract.GmailClient")
    @patch("metals.gmail_extract.resolve_paths_profile")
    def test_run_no_messages(self, mock_resolve, mock_client_class):
        """Test run with no messages found."""
        mock_resolve.return_value = ("cred.json", "token.json")

        # Create mock client with empty message list
        mock_client = make_mock_gmail_client(message_ids=[])
        mock_client_class.return_value = mock_client

        result = run(profile="test", days=30)
        self.assertEqual(result, 0)


class TestMain(unittest.TestCase):
    """Tests for main function."""

    @patch("metals.gmail_extract.run")
    def test_main_with_defaults(self, mock_run):
        """Test main with default arguments."""
        mock_run.return_value = 0
        result = main([])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            profile="gmail_personal",
            days=365,
        )

    @patch("metals.gmail_extract.run")
    def test_main_with_custom_args(self, mock_run):
        """Test main with custom arguments."""
        mock_run.return_value = 0
        result = main([
            "--profile", "work_gmail",
            "--days", "90",
        ])
        self.assertEqual(result, 0)
        mock_run.assert_called_once_with(
            profile="work_gmail",
            days=90,
        )


if __name__ == "__main__":
    unittest.main()
