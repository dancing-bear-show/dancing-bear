import unittest

from tests.fixtures import capture_stdout


class TestLLMTableOutput(unittest.TestCase):
    def test_stale_table_with_status_has_header(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["stale", "--with-status", "--limit", "5"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("| Area | Days | Status | Priority |", out)

    def test_deps_text_output_has_columns(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["deps", "--format", "text", "--order", "asc", "--limit", "10"])
        self.assertEqual(rc, 0)
        lines = [ln for ln in buf.getvalue().splitlines() if "\t" in ln]
        # Text format: area\tdependencies\tdependents\tcombined
        for ln in lines:
            parts = ln.split("\t")
            self.assertEqual(len(parts), 4, f"Expected 4 columns, got: {ln}")
