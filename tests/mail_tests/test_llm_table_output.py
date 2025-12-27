import io
import sys
import unittest
from pathlib import Path


class TestLLMTableOutput(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_stale_table_with_status_has_header(self):
        import mail.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["stale", "--with-status", "--limit", "5"])  # default table format
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("| Area | Days | Status | Priority |", out)

    def test_deps_text_output_has_columns(self):
        import mail.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["deps", "--format", "text", "--order", "asc", "--limit", "10"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        lines = [ln for ln in buf.getvalue().splitlines() if "\t" in ln]
        # Text format: area\tdependencies\tdependents\tcombined
        for ln in lines:
            parts = ln.split("\t")
            self.assertEqual(len(parts), 4, f"Expected 4 columns, got: {ln}")

