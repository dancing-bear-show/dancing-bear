"""Additional tests for calendars/locations_map.py."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import calendars.locations_map as locations_map_mod


def _reset_cache():
    """Force re-read from disk by clearing the module-level cache."""
    locations_map_mod._CACHED_MAP = None


class TestEnrichLocation(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def tearDown(self):
        _reset_cache()

    def test_known_arena_enriched(self):
        result = locations_map_mod.enrich_location("Bond Lake Arena")
        self.assertIn("Bond Lake Arena", result)
        self.assertIn("Richmond Hill", result)

    def test_unknown_name_returned_unchanged(self):
        result = locations_map_mod.enrich_location("Mystery Venue 9000")
        self.assertEqual(result, "Mystery Venue 9000")

    def test_empty_string_returned_unchanged(self):
        result = locations_map_mod.enrich_location("")
        self.assertEqual(result, "")

    def test_whitespace_only_stripped_and_empty_returned(self):
        result = locations_map_mod.enrich_location("   ")
        self.assertEqual(result, "")

    def test_strips_input_whitespace_for_lookup(self):
        result = locations_map_mod.enrich_location("  Bond Lake Arena  ")
        # Stripped → known entry → enriched
        self.assertIn("Bond Lake Arena", result)

    def test_sarc_pool_enriched(self):
        result = locations_map_mod.enrich_location("S.A.R.C. Pool")
        self.assertIn("Aurora", result)

    def test_aflc_enriched(self):
        result = locations_map_mod.enrich_location("A.F.L.C.")
        self.assertIn("Aurora", result)


class TestGetLocationsMap(unittest.TestCase):
    def setUp(self):
        _reset_cache()

    def tearDown(self):
        _reset_cache()

    def test_returns_dict(self):
        m = locations_map_mod.get_locations_map()
        self.assertIsInstance(m, dict)
        self.assertGreater(len(m), 0)

    def test_cached_after_first_call(self):
        m1 = locations_map_mod.get_locations_map()
        m2 = locations_map_mod.get_locations_map()
        self.assertIs(m1, m2)

    def test_fallback_to_address_map_when_no_yaml(self):
        """When no config/locations.yaml exists, falls back to ADDRESS_MAP."""
        with patch.object(locations_map_mod, "_default_locations_yaml_paths", return_value=[]):
            _reset_cache()
            m = locations_map_mod.get_locations_map()
        self.assertIn("Bond Lake Arena", m)

    def test_loads_yaml_when_present(self):
        """When a valid locations.yaml is present it overrides the built-in map."""
        import yaml

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        data = {"Custom Arena": "Custom Arena (123 Fake St, Test City, ON)"}
        yaml.safe_dump(data, tmp)
        tmp.flush()
        tmp_path = tmp.name
        tmp.close()

        from pathlib import Path
        try:
            with patch.object(
                locations_map_mod,
                "_default_locations_yaml_paths",
                return_value=[Path(tmp_path)],
            ):
                _reset_cache()
                m = locations_map_mod.get_locations_map()
            self.assertIn("Custom Arena", m)
            self.assertEqual(m["Custom Arena"], "Custom Arena (123 Fake St, Test City, ON)")
        finally:
            os.unlink(tmp_path)
            _reset_cache()

    def test_yaml_with_locations_key(self):
        """Handles {locations: {...}} wrapper format."""
        import yaml

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        data = {"locations": {"Wrapped Arena": "Wrapped Arena (1 Main St, City, ON)"}}
        yaml.safe_dump(data, tmp)
        tmp.flush()
        tmp_path = tmp.name
        tmp.close()

        from pathlib import Path
        try:
            with patch.object(
                locations_map_mod,
                "_default_locations_yaml_paths",
                return_value=[Path(tmp_path)],
            ):
                _reset_cache()
                m = locations_map_mod.get_locations_map()
            self.assertIn("Wrapped Arena", m)
        finally:
            os.unlink(tmp_path)
            _reset_cache()

    def test_invalid_yaml_falls_back_to_address_map(self):
        """When YAML loading raises, falls back to ADDRESS_MAP."""
        import yaml
        from pathlib import Path

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        tmp.write(": : : invalid yaml :::")
        tmp.flush()
        tmp_path = tmp.name
        tmp.close()

        try:
            with patch.object(
                locations_map_mod,
                "_default_locations_yaml_paths",
                return_value=[Path(tmp_path)],
            ):
                _reset_cache()
                m = locations_map_mod.get_locations_map()
            # Should fall back to ADDRESS_MAP which has Bond Lake Arena
            self.assertIn("Bond Lake Arena", m)
        finally:
            os.unlink(tmp_path)
            _reset_cache()

    def test_yaml_with_non_string_values_ignored(self):
        """YAML with non-string values should not be used (falls back)."""
        import yaml
        from pathlib import Path

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        )
        # value is a list not str → fails validation
        data = {"Bad Entry": ["not", "a", "string"]}
        yaml.safe_dump(data, tmp)
        tmp.flush()
        tmp_path = tmp.name
        tmp.close()

        try:
            with patch.object(
                locations_map_mod,
                "_default_locations_yaml_paths",
                return_value=[Path(tmp_path)],
            ):
                _reset_cache()
                m = locations_map_mod.get_locations_map()
            # Falls back to ADDRESS_MAP
            self.assertIn("Bond Lake Arena", m)
        finally:
            os.unlink(tmp_path)
            _reset_cache()


class TestDefaultLocationsPaths(unittest.TestCase):
    def test_returns_list_of_paths(self):
        from pathlib import Path
        paths = locations_map_mod._default_locations_yaml_paths()
        self.assertIsInstance(paths, list)
        for p in paths:
            self.assertIsInstance(p, Path)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
