"""Tests for whatsapp meta module."""
from __future__ import annotations

import unittest

from whatsapp.meta import META


class TestMetaConstants(unittest.TestCase):
    """Tests for the whatsapp AppMeta declaration.

    Asserts the values this module actually declares. The rendering of each
    fallback string is AppMeta's behaviour and is covered by core's tests.
    """

    def test_app_id(self):
        """Test app_id is set correctly."""
        self.assertEqual(META.app_id, "whatsapp")

    def test_purpose(self):
        """Test purpose is a non-empty string."""
        self.assertIsInstance(META.purpose, str)
        self.assertGreater(len(META.purpose), 0)

    def test_display_name(self):
        """Test display_name keeps the capitalised spelling."""
        self.assertEqual(META.display_name, "WhatsApp")

    def test_agentic_fallback(self):
        """Test agentic_fallback contains app ID."""
        self.assertIn(META.app_id, META.agentic_fallback)
        self.assertIn("agentic:", META.agentic_fallback)

    def test_inventory_fallback(self):
        """Test inventory_fallback uses the display name."""
        self.assertIn("WhatsApp", META.inventory_fallback)

    def test_familiar_compact_fallback(self):
        """Test familiar_compact_fallback is valid YAML-like."""
        self.assertIn("meta:", META.familiar_compact_fallback)
        self.assertIn("steps:", META.familiar_compact_fallback)
        self.assertIn("whatsapp", META.familiar_compact_fallback)

    def test_familiar_extended_fallback(self):
        """Test familiar_extended_fallback uses the example command."""
        self.assertIn("search", META.familiar_extended_fallback)
        self.assertIn("whatsapp", META.familiar_extended_fallback)


if __name__ == "__main__":
    unittest.main()
