import unittest

from calendars.agentic import build_agentic_capsule, build_domain_map


class TestAgenticCapsules(unittest.TestCase):
    def test_agentic_capsule_contains_cli_tree(self):
        cap = build_agentic_capsule()
        self.assertIn('agentic: calendar', cap)
        self.assertIn('CLI Tree', cap)
        # Should mention outlook and gmail groups
        self.assertIn('outlook', cap)
        self.assertIn('gmail', cap)

    def test_domain_map_structure(self):
        dm = build_domain_map()
        self.assertIn('Top-Level', dm)
        # At least include flow map or cli tree
        self.assertTrue('Flow Map' in dm or 'CLI Tree' in dm)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

