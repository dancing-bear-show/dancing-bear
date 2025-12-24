import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import repo_root


class TestCalendarDeriveAllGenerated(unittest.TestCase):
    def test_calendar_llm_derive_all_includes_generated(self):
        root = repo_root()
        sys.path.insert(0, str(root.parent))
        import calendars.llm_cli as mod  # type: ignore
        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(["derive-all", "--out-dir", td, "--include-generated", "--stdout"])  # generate files
            self.assertEqual(rc, 0)
            p1 = Path(td) / "AGENTIC_CALENDAR.md"
            p2 = Path(td) / "DOMAIN_MAP_CALENDAR.md"
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())
            self.assertIn("agentic: calendar", p1.read_text(encoding='utf-8'))
            self.assertIn("Top-Level", p2.read_text(encoding='utf-8'))
