import tempfile
import unittest
from pathlib import Path

from tests.fixtures import capture_stdout


class TestDeskLLMCLI(unittest.TestCase):
    def test_agentic_stdout(self):
        import desk.llm_cli as mod

        with capture_stdout() as buf:
            rc = mod.main(["agentic", "--stdout"])
        self.assertEqual(rc, 0)
        self.assertIn("agentic: desk", buf.getvalue())

    def test_derive_all_outputs_files(self):
        import desk.llm_cli as mod

        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(["derive-all", "--out-dir", td, "--include-generated", "--stdout"])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(td) / "AGENTIC_DESK.md").exists())
            self.assertTrue((Path(td) / "DOMAIN_MAP_DESK.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
