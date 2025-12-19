import io
import os
import sys
import unittest
from pathlib import Path


class TestLLMCheckOutput(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_check_outputs_status_table(self):
        import mail_assistant.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["check", "--root", ".", "--limit", "5", "--agg", "max"])  # emits table with status
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("| Target | Staleness (days) | SLA (days) | Status |", out)

