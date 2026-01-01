import unittest

from tests.fixtures import capture_stdout


class TestCLITreeIntegrity(unittest.TestCase):
    def test_cli_tree_contains_core_subcommands(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Ensure filters and labels lines include expected subcommands
        lines = out.splitlines()
        filters_line = next((ln for ln in lines if ln.startswith("- filters:")), "")
        labels_line = next((ln for ln in lines if ln.startswith("- labels:")), "")
        self.assertIn("plan", filters_line)
        self.assertIn("sync", filters_line)
        self.assertIn("export", labels_line)
        self.assertIn("sync", labels_line)
