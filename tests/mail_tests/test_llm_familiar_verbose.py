import io
import sys
import unittest
from pathlib import Path


class TestLLMFamiliarVerbose(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_familiar_verbose_includes_env_steps(self):
        import mail.llm_cli as mod  # type: ignore
        buf = io.StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = mod.main(["familiar", "--stdout", "--verbose"])  # prints YAML
        finally:
            sys.stdout = old
        out = buf.getvalue()
        self.assertEqual(rc, 0)
        # Verbose mode includes extended app agentic commands
        self.assertIn("--app resume agentic", out)
        self.assertIn("config inspect", out)

