import io
import sys
import importlib
from pathlib import Path
import unittest


def load_main_module():
    # Ensure parent of package dir is importable so `import mail_assistant` works
    pkg_parent = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(pkg_parent))
    mod = importlib.import_module("mail_assistant.__main__")
    return mod


class TestAgenticFlag(unittest.TestCase):
    def test_agentic_outputs_capsule(self):
        mod = load_main_module()
        buf = io.StringIO()
        sys_stdout = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["--agentic"])  # should exit early and return 0
        finally:
            sys.stdout = sys_stdout
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: mail_assistant", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
