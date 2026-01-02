import unittest

from tests.fixtures import capture_stdout


class TestLLMCheckOutput(unittest.TestCase):
    def test_check_returns_zero_when_no_sla(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            # check command returns 0 when no LLM_SLA env is set (no threshold to check)
            rc = mod.main(["check", "--root", ".", "--limit", "5", "--agg", "max"])
        self.assertEqual(rc, 0)
