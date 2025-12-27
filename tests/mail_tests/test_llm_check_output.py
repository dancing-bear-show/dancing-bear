import io
import sys
import unittest
from pathlib import Path


class TestLLMCheckOutput(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_check_returns_zero_when_no_sla(self):
        import mail.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            # check command returns 0 when no LLM_SLA env is set (no threshold to check)
            rc = mod.main(["check", "--root", ".", "--limit", "5", "--agg", "max"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)

