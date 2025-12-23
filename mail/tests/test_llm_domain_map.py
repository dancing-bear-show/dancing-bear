import io
import sys
import unittest
from pathlib import Path


class TestLLMDomainMap(unittest.TestCase):
    def setUp(self) -> None:
        # Ensure parent of package dir is importable
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_llm_domain_map_stdout(self):
        import mail_assistant.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["domain-map", "--stdout"])  # prints and returns 0
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Should include CLI Tree and Flow Map headings
        self.assertIn("CLI Tree", out)
        self.assertIn("Flow Map", out)

    def test_llm_derive_all_includes_generated(self):
        import tempfile
        import mail_assistant.llm_cli as mod  # type: ignore
        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(["derive-all", "--out-dir", td, "--include-generated", "--stdout"])  # generate files
            self.assertEqual(rc, 0)
            p1 = Path(td) / "AGENTIC.md"
            p2 = Path(td) / "DOMAIN_MAP.md"
            # Files should be created when --include-generated is provided
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())

