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
        # Verbose mode surfaces the visualization + orchestration wrappers
        self.assertIn("./bin/charts --help", out)
        self.assertIn("./bin/diagrams --help", out)
        self.assertIn("./bin/workflow --help", out)

    def test_familiar_fast_path_omits_viz_wrappers(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["familiar", "--stdout"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Fast (non-verbose) path stays lean: viz/orchestration wrappers are on-demand
        self.assertNotIn("./bin/charts", out)
        self.assertNotIn("./bin/diagrams", out)
        self.assertNotIn("./bin/workflow", out)
