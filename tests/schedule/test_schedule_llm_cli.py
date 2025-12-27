import io
import sys
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import repo_root


class TestScheduleLLMCLI(unittest.TestCase):
    def _import_mod(self):
        root = repo_root()
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root.parent))
        import schedule.llm_cli as mod  # type: ignore

        return mod

    def test_agentic_stdout(self):
        mod = self._import_mod()
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["agentic", "--stdout"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        self.assertIn("agentic: schedule", buf.getvalue())

    def test_derive_all_outputs_files(self):
        mod = self._import_mod()
        with tempfile.TemporaryDirectory() as td:
            rc = mod.main(["derive-all", "--out-dir", td, "--include-generated", "--stdout"])
            self.assertEqual(rc, 0)
            self.assertTrue((Path(td) / "AGENTIC_SCHEDULE.md").exists())
            self.assertTrue((Path(td) / "DOMAIN_MAP_SCHEDULE.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
