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
        self.assertIn("| Target | Staleness (days) | SLA (days) | Status |", out)

    def test_deps_text_sorted_by_dependents_asc(self):
        import mail.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["deps", "--format", "text", "--by", "dependents", "--order", "asc", "--limit", "10"])  # prints lines area\tval
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        lines = [ln for ln in buf.getvalue().splitlines() if "\t" in ln]
        vals = []
        for ln in lines:
            try:
                area, val = ln.split("\t", 1)
                vals.append(int(val.strip()))
            except Exception:  # noqa: S112 - skip on error
                continue
        self.assertTrue(all(vals[i] <= vals[i+1] for i in range(len(vals)-1)))

