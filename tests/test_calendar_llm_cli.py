import io
import sys
import unittest

from tests.fixtures import repo_root


class TestCalendarLLMCLI(unittest.TestCase):
    def test_llm_calendar_agentic(self):
        root = repo_root()
        sys.path.insert(0, str(root.parent))
        import calendar_assistant.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["agentic", "--stdout"])  # prints capsule
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: calendar_assistant", out)

    def test_llm_calendar_derive_all(self):
        root = repo_root()
        sys.path.insert(0, str(root.parent))
        import calendar_assistant.llm_cli as mod  # type: ignore
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            buf = io.StringIO()
            old = sys.stdout
            try:
                sys.stdout = buf
                rc = mod.main(["derive-all", "--out-dir", td, "--stdout"])  # generate core capsules
            finally:
                sys.stdout = old
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("Generated:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
