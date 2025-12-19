import unittest
from pathlib import Path


class LocationsMapTests(unittest.TestCase):
    @unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML')
    def test_enrich_location_from_yaml(self):
        # Use built-in fallback map when config/locations.yaml is absent
        from calendar_assistant.locations_map import enrich_location, ADDRESS_MAP
        # Clear any cache to force reload from built-in map
        try:
            import calendar_assistant.locations_map as lm
            lm._CACHED_MAP = None  # type: ignore[attr-defined]
        except Exception:
            pass

        key = 'Ed Sackfield Arena'
        expected = ADDRESS_MAP[key]
        actual = enrich_location(key)
        self.assertEqual(actual, expected)
        # Non-mapped names should return as-is
        self.assertEqual(enrich_location('Unknown Facility'), 'Unknown Facility')
