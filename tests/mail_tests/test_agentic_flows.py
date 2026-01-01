import unittest

from tests.fixtures import capture_stdout


class TestAgenticFlows(unittest.TestCase):
    def test_agentic_includes_forwarding_and_auto(self):
        import mail.__main__ as mod

        with capture_stdout() as buf:
            rc = mod.main(["--agentic"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Specific flow entries should be present when CLI supports them
        self.assertIn("Forwarding + Filters", out)
        self.assertIn("Auto (categorize + archive)", out)

    def test_agentic_includes_outlook_categories_and_folders(self):
        import mail.__main__ as mod

        with capture_stdout() as buf:
            rc = mod.main(["--agentic"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("Outlook Categories", out)
        self.assertIn("Outlook Folders", out)
