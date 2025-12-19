import io
import sys
import tempfile
import unittest
from pathlib import Path


class TestCalendarDeriveAllGenerated(unittest.TestCase):
    def test_calendar_llm_derive_all_includes_generated(self):
        repo_root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(repo_root.parent))
        import calendar_assistant.llm_cli as mod  # type: ignore
        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(["derive-all", "--out-dir", td, "--include-generated", "--stdout"])  # generate files
            self.assertEqual(rc, 0)
            p1 = Path(td) / "AGENTIC_CALENDAR.md"
            p2 = Path(td) / "DOMAIN_MAP_CALENDAR.md"
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())
            self.assertIn("agentic: calendar_assistant", p1.read_text(encoding='utf-8'))
            self.assertIn("Top-Level", p2.read_text(encoding='utf-8'))

