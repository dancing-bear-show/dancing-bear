"""Tests for core.meta_base.AppMeta.

The fallback strings are rendered here rather than in each app's meta tests:
the rendering is AppMeta's behaviour, identical for every app that declares
one, so it is asserted once.
"""
from __future__ import annotations

import unittest

from core.meta_base import AppMeta


class TestAppMetaDefaults(unittest.TestCase):
    """Defaults derived from app_id when optional fields are omitted."""

    def setUp(self):
        self.meta = AppMeta(app_id="demo", purpose="Demo purpose")

    def test_display_name_defaults_to_title_cased_app_id(self):
        self.assertEqual(self.meta._display_name, "Demo")

    def test_display_name_replaces_underscores(self):
        meta = AppMeta(app_id="apple_music", purpose="p")
        self.assertEqual(meta._display_name, "Apple Music")

    def test_explicit_display_name_wins(self):
        meta = AppMeta(app_id="wifi", purpose="p", display_name="Wi-Fi")
        self.assertEqual(meta._display_name, "Wi-Fi")

    def test_familiar_compact_defaults_to_bin_help(self):
        self.assertIn("./bin/demo --help", self.meta.familiar_compact_fallback)

    def test_familiar_extended_defaults_to_bin_help(self):
        self.assertIn("./bin/demo --help", self.meta.familiar_extended_fallback)


class TestAppMetaOverrides(unittest.TestCase):
    """Optional fields override the app_id-derived defaults."""

    def test_bin_name_override_is_used(self):
        meta = AppMeta(app_id="qlty", purpose="p", bin_name="./bin/qlty-assistant")
        self.assertIn("./bin/qlty-assistant --help", meta.familiar_compact_fallback)

    def test_help_cmd_override_is_used(self):
        meta = AppMeta(app_id="demo", purpose="p", help_cmd="./bin/demo doctor")
        self.assertIn("./bin/demo doctor", meta.familiar_compact_fallback)

    def test_example_cmd_override_is_used(self):
        meta = AppMeta(app_id="demo", purpose="p", example_cmd="./bin/demo run --json")
        self.assertIn("./bin/demo run --json", meta.familiar_extended_fallback)


class TestAppMetaFallbackStrings(unittest.TestCase):
    """Rendered fallback strings."""

    def setUp(self):
        self.meta = AppMeta(app_id="demo", purpose="Demo purpose")

    def test_agentic_fallback_carries_id_and_purpose(self):
        self.assertIn("agentic: demo", self.meta.agentic_fallback)
        self.assertIn("purpose: Demo purpose", self.meta.agentic_fallback)

    def test_domain_map_fallback_is_a_string(self):
        self.assertIsInstance(self.meta.domain_map_fallback, str)
        self.assertEqual(self.meta.domain_map_fallback, "Domain Map not available")

    def test_inventory_fallback_uses_display_name(self):
        self.assertIn("Demo", self.meta.inventory_fallback)
        self.assertIn("LLM Agent Inventory", self.meta.inventory_fallback)

    def test_policies_fallback_has_expected_sections(self):
        policies = self.meta.policies_fallback
        self.assertIn("policies:", policies)
        self.assertIn("style:", policies)
        self.assertIn("tests:", policies)

    def test_familiar_compact_is_yaml_like(self):
        compact = self.meta.familiar_compact_fallback
        self.assertIn("meta:", compact)
        self.assertIn("steps:", compact)
        self.assertIn("demo_familiarize", compact)


class TestAppMetaIsFrozen(unittest.TestCase):
    """AppMeta is a frozen dataclass -- app metadata is not mutable at runtime."""

    def test_assignment_raises(self):
        meta = AppMeta(app_id="demo", purpose="p")
        with self.assertRaises(Exception):
            meta.app_id = "other"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
