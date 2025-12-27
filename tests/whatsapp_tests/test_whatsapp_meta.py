"""Tests for whatsapp meta module."""
from __future__ import annotations

import unittest

from whatsapp import meta


class TestMetaConstants(unittest.TestCase):
    """Tests for meta module constants."""

    def test_app_id(self):
        """Test APP_ID is set correctly."""
        self.assertEqual(meta.APP_ID, "whatsapp")

    def test_purpose(self):
        """Test PURPOSE is a non-empty string."""
        self.assertIsInstance(meta.PURPOSE, str)
        self.assertGreater(len(meta.PURPOSE), 0)

    def test_agentic_fallback(self):
        """Test AGENTIC_FALLBACK contains app ID."""
        self.assertIn(meta.APP_ID, meta.AGENTIC_FALLBACK)
        self.assertIn("agentic:", meta.AGENTIC_FALLBACK)

    def test_domain_map_fallback(self):
        """Test DOMAIN_MAP_FALLBACK is a string."""
        self.assertIsInstance(meta.DOMAIN_MAP_FALLBACK, str)

    def test_inventory_fallback(self):
        """Test INVENTORY_FALLBACK contains WhatsApp."""
        self.assertIn("WhatsApp", meta.INVENTORY_FALLBACK)

    def test_familiar_compact_fallback(self):
        """Test FAMILIAR_COMPACT_FALLBACK is valid YAML-like."""
        self.assertIn("meta:", meta.FAMILIAR_COMPACT_FALLBACK)
        self.assertIn("steps:", meta.FAMILIAR_COMPACT_FALLBACK)
        self.assertIn("whatsapp", meta.FAMILIAR_COMPACT_FALLBACK)

    def test_familiar_extended_fallback(self):
        """Test FAMILIAR_EXTENDED_FALLBACK has search command."""
        self.assertIn("search", meta.FAMILIAR_EXTENDED_FALLBACK)
        self.assertIn("whatsapp", meta.FAMILIAR_EXTENDED_FALLBACK)

    def test_policies_fallback(self):
        """Test POLICIES_FALLBACK has policies section."""
        self.assertIn("policies:", meta.POLICIES_FALLBACK)
        self.assertIn("style:", meta.POLICIES_FALLBACK)
        self.assertIn("tests:", meta.POLICIES_FALLBACK)


if __name__ == "__main__":
    unittest.main()
