import sys
import unittest

from tests.fixtures import bin_path, repo_root, run


class WifiCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, "-m", "wifi", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Wi-Fi + network diagnostic helper", proc.stdout)

    def test_help_via_executable_script(self):
        root = repo_root()
        wrapper = bin_path("wifi")
        self.assertTrue(wrapper.exists(), "bin/wifi not found")
        proc = run([sys.executable, str(wrapper), "--help"], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Wi-Fi + network diagnostic helper", proc.stdout)

    def test_help_via_legacy_script(self):
        root = repo_root()
        wrapper = bin_path("wifi-assistant")
        self.assertTrue(wrapper.exists(), "bin/wifi-assistant not found")
        proc = run([sys.executable, str(wrapper), "--help"], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Wi-Fi + network diagnostic helper", proc.stdout)


if __name__ == "__main__":
    unittest.main()
