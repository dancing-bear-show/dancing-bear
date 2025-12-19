import unittest
from pathlib import Path


class LocationsMapTests(unittest.TestCase):
    @unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML')
    def test_enrich_location_from_yaml(self):
        # Load expected mapping from repo config/locations.yaml
        import yaml
        repo_root = Path(__file__).resolve().parents[1]
        cfg_path = repo_root / 'config' / 'locations.yaml'
        self.assertTrue(cfg_path.exists(), 'config/locations.yaml missing')
        data = yaml.safe_load(cfg_path.read_text(encoding='utf-8')) or {}
        locs = data.get('locations') or {}
        # Pick a known key
        key = 'Ed Sackfield Arena'
        self.assertIn(key, locs, 'Expected test key not found in locations.yaml')
        expected = str(locs[key])

        from calendar_assistant.locations_map import enrich_location, _CACHED_MAP
        # Clear any cache to force reload from YAML
        try:
            import importlib
            import calendar_assistant.locations_map as lm
            lm._CACHED_MAP = None  # type: ignore[attr-defined]
        except Exception:
            pass

        actual = enrich_location(key)
        self.assertEqual(actual, expected)
        # Non-mapped names should return as-is
        self.assertEqual(enrich_location('Unknown Facility'), 'Unknown Facility')

