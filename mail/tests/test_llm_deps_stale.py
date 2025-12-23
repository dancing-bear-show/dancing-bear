import io
import json
import sys
import unittest
from pathlib import Path


class TestLLMDepsStale(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_deps_json_structure(self):
        import mail_assistant.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["deps", "--format", "json", "--limit", "5"])  # prints JSON list
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        if data:
            self.assertIn("area", data[0])
            self.assertIn("dependencies", data[0])
            self.assertIn("dependents", data[0])
            self.assertIn("combined", data[0])

    def test_stale_json_structure(self):
        import mail_assistant.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["stale", "--format", "json", "--limit", "5"])  # prints JSON list
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        if data:
            self.assertIn("key", data[0])
            self.assertIn("staleness_days", data[0])

