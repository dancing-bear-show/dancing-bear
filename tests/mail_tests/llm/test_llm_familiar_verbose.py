import unittest

from tests.fixtures import capture_stdout


class TestLLMFamiliarVerbose(unittest.TestCase):
    def test_familiar_verbose_includes_env_steps(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["familiar", "--stdout", "--verbose"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Verbose mode includes extended app agentic commands
        self.assertIn("--app resume agentic", out)
        self.assertIn("config inspect", out)
