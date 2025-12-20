import os
import sys
import unittest
from pathlib import Path

from tests.fixtures import run

class PhoneCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'phone', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_help_via_executable_script(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'phone'
        self.assertTrue(wrapper.exists(), 'bin/phone not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_help_via_legacy_script(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'phone-assistant'
        self.assertTrue(wrapper.exists(), 'bin/phone-assistant not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Phone Assistant CLI', proc.stdout)

    def test_agentic_flag(self):
        proc = run([sys.executable, '-m', 'phone', '--agentic'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: phone', proc.stdout)
