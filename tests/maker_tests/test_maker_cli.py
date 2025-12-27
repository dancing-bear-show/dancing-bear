import sys
import unittest

from tests.fixtures import bin_path, repo_root, run


class MakerCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, "-m", "maker", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Maker utilities CLI", proc.stdout)

    def test_help_via_executable_script(self):
        root = repo_root()
        wrapper = bin_path("maker")
        self.assertTrue(wrapper.exists(), "bin/maker not found")
        proc = run([sys.executable, str(wrapper), "--help"], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Maker utilities CLI", proc.stdout)


if __name__ == "__main__":
    unittest.main()
