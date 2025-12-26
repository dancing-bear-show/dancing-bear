import unittest

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
        except Exception:  # noqa: S110 - test setup
            pass

        key = 'Ed Sackfield Arena'
        expected = ADDRESS_MAP[key]
        actual = enrich_location(key)
        self.assertEqual(actual, expected)
        # Non-mapped names should return as-is
        self.assertEqual(enrich_location('Unknown Facility'), 'Unknown Facility')
