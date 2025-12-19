import unittest

from calendar_assistant.locations_map import enrich_location, get_locations_map


class TestLocationsMap(unittest.TestCase):
    def test_enrich_known(self):
        m = get_locations_map()
        # Use a known key from ADDRESS_MAP fallback
        self.assertIn('Ed Sackfield Arena', m)
        out = enrich_location('Ed Sackfield Arena')
        self.assertIn('Ed Sackfield', out)
        self.assertIn('Richmond Hill', out)

    def test_enrich_unknown_returns_input(self):
        self.assertEqual(enrich_location('Unknown Facility'), 'Unknown Facility')


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

