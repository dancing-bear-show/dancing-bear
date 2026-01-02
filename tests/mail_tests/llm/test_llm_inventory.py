import json
import unittest

from tests.fixtures import capture_stdout


class TestLLMInventory(unittest.TestCase):
    def test_inventory_json(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["inventory", "--format", "json", "--stdout"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        # Expected top-level keys
        self.assertIn('wrappers', data)
        self.assertIn('areas', data)
        self.assertIn('mail_groups', data)
