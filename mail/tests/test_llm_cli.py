import io
import sys
import importlib
from pathlib import Path
import unittest


def load_llm_cli():
    pkg_parent = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(pkg_parent))
    mod = importlib.import_module("mail.llm_cli")
    return mod


class TestLLMAgentic(unittest.TestCase):
    def test_llm_agentic_outputs(self):
        mod = load_llm_cli()
        buf = io.StringIO()
        sys_stdout = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["agentic", "--stdout"])  # prints and returns 0
        finally:
            sys.stdout = sys_stdout
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: mail", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)

