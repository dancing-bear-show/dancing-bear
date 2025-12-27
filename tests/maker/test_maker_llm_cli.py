import io
import sys
import unittest

from tests.fixtures import repo_root


class TestMakerLLMCLI(unittest.TestCase):
    def test_llm_maker_agentic(self):
        root = repo_root()
        sys.path.insert(0, str(root))
        sys.path.insert(0, str(root.parent))
        import maker.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["agentic", "--stdout"])  # prints capsule
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("agentic: maker", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
