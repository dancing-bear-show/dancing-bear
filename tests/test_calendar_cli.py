import os
import sys
import subprocess
import unittest
from pathlib import Path


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class CalendarCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'calendar_assistant', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Calendar Assistant CLI', proc.stdout)

    test_help_via_module_invocation = unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML to import CLI')(test_help_via_module_invocation)

    def test_help_via_assistant_wrapper(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'assistant'
        self.assertTrue(wrapper.exists(), 'bin/assistant not found')
        proc = run([sys.executable, str(wrapper), 'calendar', '--help'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Calendar Assistant CLI', proc.stdout)

    test_help_via_assistant_wrapper = unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML to import CLI')(test_help_via_assistant_wrapper)
