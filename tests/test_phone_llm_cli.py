import io
import sys
import unittest
from pathlib import Path


class TestPhoneLlmCli(unittest.TestCase):
    def test_agentic_stdout(self):
        repo_root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(repo_root.parent))
        import phone.llm_cli as mod  # type: ignore

        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["agentic", "--stdout"])
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: phone", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
