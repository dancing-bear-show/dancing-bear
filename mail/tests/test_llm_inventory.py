import io
import sys
import unittest
from pathlib import Path


class TestLLMInventory(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_inventory_json(self):
        import json
        import mail.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["inventory", "--format", "json", "--stdout"])  # prints JSON
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        # Expected top-level keys
        self.assertIn('wrappers', data)
        self.assertIn('areas', data)
        self.assertIn('mail_groups', data)

