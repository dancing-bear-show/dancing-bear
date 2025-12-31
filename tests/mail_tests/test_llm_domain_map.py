import tempfile
import unittest
from pathlib import Path

from tests.fixtures import capture_stdout


class TestLLMDomainMap(unittest.TestCase):
    def test_llm_domain_map_stdout(self):
        import mail.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["domain-map", "--stdout"])
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Should include CLI Tree and Flows Index headings
        self.assertIn("CLI Tree", out)
        self.assertIn("Flows Index", out)

    def test_llm_derive_all_includes_generated(self):
        import mail.llm_cli as mod

        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(["derive-all", "--out-dir", td, "--include-generated", "--stdout"])
            self.assertEqual(rc, 0)
            p1 = Path(td) / "AGENTIC.md"
            p2 = Path(td) / "DOMAIN_MAP.md"
            # Files should be created when --include-generated is provided
            self.assertTrue(p1.exists())
            self.assertTrue(p2.exists())
