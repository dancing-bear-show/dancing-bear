import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout

from desk.cli import main


class TestCLI(unittest.TestCase):
    def test_cli_help(self):
        f = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stdout(f):
            main(["--help"])
        self.assertEqual(cm.exception.code, 0)
        out = f.getvalue()
        self.assertIn("desk-assistant", out)
        self.assertIn("scan", out)
        self.assertIn("plan", out)
        self.assertIn("apply", out)
        self.assertIn("rules", out)

    def test_rules_export_writes_file(self):
        with tempfile.TemporaryDirectory() as td:
            target = os.path.join(td, "rules.yaml")
            main(["rules", "export", "--out", target])
            self.assertTrue(os.path.exists(target))
            with open(target, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("rules:", content)

    def test_agentic_flag(self):
        f = io.StringIO()
        with redirect_stdout(f):
            main(["--agentic"])
        out = f.getvalue()
        self.assertIn("agentic: desk", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
