import tempfile
import unittest

from tests.fixtures import capture_stdout


class TestCalendarLLMCLI(unittest.TestCase):
    def test_llm_calendar_agentic(self):
        import calendars.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: calendar", out)

    def test_llm_calendar_derive_all(self):
        import calendars.llm_cli as mod

        with tempfile.TemporaryDirectory() as td:
            with capture_stdout() as buf:
                rc = mod.main(["derive-all", "--out-dir", td, "--stdout"])
            out = buf.getvalue()
            self.assertEqual(rc, 0)
            self.assertIn("Generated:", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
