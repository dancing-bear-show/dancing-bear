import json
import unittest

from tests.fixtures import capture_stdout


class TestLLMDepsStale(unittest.TestCase):
    def test_deps_json_structure(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["deps", "--format", "json", "--limit", "5"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        if data:
            self.assertIn("area", data[0])
            self.assertIn("dependencies", data[0])
            self.assertIn("dependents", data[0])
            self.assertIn("combined", data[0])

    def test_stale_json_structure(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["stale", "--format", "json", "--limit", "5"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        if data:
            self.assertIn("area", data[0])
            self.assertIn("staleness_days", data[0])
