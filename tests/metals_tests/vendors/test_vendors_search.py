"""Tests for metals vendor registry and sender lookup."""
from __future__ import annotations

import unittest

from metals.vendors_search import (
    ALL_VENDORS,
    GMAIL_VENDORS,
    OUTLOOK_VENDORS,
    get_vendor_for_sender,
)
from metals.vendors_parse_vendor import RCMParser

from tests.metals_tests.fixtures import VENDOR_EMAILS


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

if __name__ == '__main__':
    unittest.main()
