import unittest
from pathlib import Path

from tests.fixtures import run

def _has_pyyaml() -> bool:
    try:
        import importlib.util

        return importlib.util.find_spec("yaml") is not None
    except Exception:
        return False


@unittest.skipUnless(_has_pyyaml(), "requires PyYAML")
class ForwardingHelpTests(unittest.TestCase):
    def test_forwarding_group_help_lists_subcommands(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / "bin" / "mail_assistant"
        self.assertTrue(wrapper.exists(), "bin/mail_assistant not found")
        proc = run([str(wrapper), "forwarding", "--help"], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = proc.stdout
        # Expect key subcommands present in help
        self.assertIn("list", out)
        self.assertIn("add", out)
        self.assertIn("status", out)
        self.assertIn("enable", out)
        self.assertIn("disable", out)


if __name__ == "__main__":
    unittest.main()
