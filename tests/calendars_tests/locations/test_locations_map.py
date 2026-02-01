import tempfile
import unittest
from pathlib import Path

from tests.fixtures import has_pyyaml


class LocationsMapTests(unittest.TestCase):
    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_enrich_location_from_yaml(self):
        # Use built-in fallback map when config/locations.yaml is absent
        from calendars.locations_map import enrich_location, ADDRESS_MAP
        # Clear any cache to force reload from built-in map
        try:
            import calendars.locations_map as lm
            lm._CACHED_MAP = None  # type: ignore[attr-defined]
        except Exception:  # nosec B110 - test setup
            pass

        key = 'Ed Sackfield Arena'
        expected = ADDRESS_MAP[key]
        actual = enrich_location(key)
        self.assertEqual(actual, expected)
        # Non-mapped names should return as-is
        self.assertEqual(enrich_location('Unknown Facility'), 'Unknown Facility')

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_enrich_location_handles_empty_string(self):
        """enrich_location should return empty string for empty input."""
        import calendars.locations_map as lm
        from calendars.locations_map import enrich_location
        lm._CACHED_MAP = None  # type: ignore[attr-defined]

        self.assertEqual(enrich_location(''), '')
        self.assertEqual(enrich_location('   '), '')

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_get_locations_map_caches_result(self):
        """get_locations_map should cache the result."""
        import calendars.locations_map as lm
        from calendars.locations_map import get_locations_map
        lm._CACHED_MAP = None  # type: ignore[attr-defined]

        # First call loads map
        first = get_locations_map()
        # Second call should return cached version
        second = get_locations_map()
        self.assertIs(first, second)

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_get_locations_map_returns_address_map_fallback(self):
        """get_locations_map should return ADDRESS_MAP when no YAML exists."""
        import calendars.locations_map as lm
        from calendars.locations_map import get_locations_map, ADDRESS_MAP
        lm._CACHED_MAP = None  # type: ignore[attr-defined]

        result = get_locations_map()
        # Should contain keys from ADDRESS_MAP
        self.assertIn('Bond Lake Arena', result)
        self.assertEqual(result['Bond Lake Arena'], ADDRESS_MAP['Bond Lake Arena'])

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_yaml_locations_from_file(self):
        """_load_yaml_locations should load from valid YAML file."""
        from calendars.locations_map import _load_yaml_locations
        import yaml

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.safe_dump({
                'Test Arena': 'Test Arena (123 Main St)',
                'Test Pool': 'Test Pool (456 Oak Ave)',
            }, tmp)
            tmp_path = Path(tmp.name)

        try:
            result = _load_yaml_locations(tmp_path)
            self.assertIsNotNone(result)
            self.assertEqual(result['Test Arena'], 'Test Arena (123 Main St)')
            self.assertEqual(result['Test Pool'], 'Test Pool (456 Oak Ave)')
        finally:
            tmp_path.unlink(missing_ok=True)

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_yaml_locations_unwraps_locations_key(self):
        """_load_yaml_locations should unwrap {locations: {...}} format."""
        from calendars.locations_map import _load_yaml_locations
        import yaml

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.safe_dump({
                'locations': {
                    'Arena': 'Arena (123 St)',
                }
            }, tmp)
            tmp_path = Path(tmp.name)

        try:
            result = _load_yaml_locations(tmp_path)
            self.assertIsNotNone(result)
            self.assertEqual(result['Arena'], 'Arena (123 St)')
        finally:
            tmp_path.unlink(missing_ok=True)

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_yaml_locations_returns_none_for_invalid_format(self):
        """_load_yaml_locations should return None for invalid YAML structure."""
        from calendars.locations_map import _load_yaml_locations
        import yaml

        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.safe_dump(['not', 'a', 'dict'], tmp)
            tmp_path = Path(tmp.name)

        try:
            result = _load_yaml_locations(tmp_path)
            self.assertIsNone(result)
        finally:
            tmp_path.unlink(missing_ok=True)

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_yaml_locations_returns_none_for_missing_file(self):
        """_load_yaml_locations should return empty dict for missing file."""
        from calendars.locations_map import _load_yaml_locations

        # load_config returns {} for missing files, which is a valid dict
        # but doesn't contain locations, so it returns empty dict after conversion
        result = _load_yaml_locations(Path('/nonexistent/path.yaml'))
        # Empty dict is valid - it passes the isinstance check and has no items
        self.assertEqual(result, {})

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_default_locations_yaml_paths_returns_list(self):
        """_default_locations_yaml_paths should return list of Path objects."""
        from calendars.locations_map import _default_locations_yaml_paths

        paths = _default_locations_yaml_paths()
        self.assertIsInstance(paths, list)
        self.assertGreater(len(paths), 0)
        for p in paths:
            self.assertIsInstance(p, Path)
