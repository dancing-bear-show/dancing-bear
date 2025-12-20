import sys
import subprocess
import unittest
from pathlib import Path


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class MakerCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, "-m", "maker", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Maker utilities CLI", proc.stdout)

    def test_help_via_executable_script(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / "bin" / "maker"
        self.assertTrue(wrapper.exists(), "bin/maker not found")
        proc = run([sys.executable, str(wrapper), "--help"], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Maker utilities CLI", proc.stdout)


if __name__ == "__main__":
    unittest.main()
