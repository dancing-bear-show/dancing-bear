import io
import sys
import unittest
from pathlib import Path


class TestCLITreeIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_cli_tree_contains_core_subcommands(self):
        import mail.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["agentic", "--stdout"])  # prints capsule with CLI Tree
        finally:
            sys.stdout = old
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

