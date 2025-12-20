import sys
import unittest

from tests.fixtures import bin_path, repo_root, run


class PhoneCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'phone', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_help_via_executable_script(self):
        root = repo_root()
        wrapper = bin_path('phone')
        self.assertTrue(wrapper.exists(), 'bin/phone not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_help_via_legacy_script(self):
        root = repo_root()
        wrapper = bin_path('phone-assistant')
        self.assertTrue(wrapper.exists(), 'bin/phone-assistant not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_agentic_flag(self):
        proc = run([sys.executable, '-m', 'phone', '--agentic'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: phone', proc.stdout)
