# Source Generated with Decompyle++
# File: test_cli.cpython-39.pyc (Python 3.9)

import os
import sys
import unittest
from pathlib import Path

from tests.fixtures import run

class CLITests(unittest.TestCase):
    
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'mail_assistant', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Mail Assistant CLI', proc.stdout)

    test_help_via_module_invocation = unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML to import CLI')(test_help_via_module_invocation)
    
    def test_help_via_executable_script(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'mail_assistant'
        self.assertTrue(wrapper.exists(), 'bin/mail_assistant not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Mail Assistant CLI', proc.stdout)

    test_help_via_executable_script = unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML to import CLI')(test_help_via_executable_script)

    def test_outlook_calendar_help(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'mail_assistant'
        self.assertTrue(wrapper.exists(), 'bin/mail_assistant not found')
        proc = run([sys.executable, str(wrapper), 'outlook', 'calendar', '--help'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # Ensure subcommands are present in help output
        self.assertIn('add-recurring', proc.stdout)

    test_outlook_calendar_help = unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML to import CLI')(test_outlook_calendar_help)

    def test_env_setup_help(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'mail_assistant'
        self.assertTrue(wrapper.exists(), 'bin/mail_assistant not found')
        proc = run([sys.executable, str(wrapper), 'env', 'setup', '--help'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Virtualenv directory', proc.stdout)

    test_env_setup_help = unittest.skipUnless(__import__('importlib').util.find_spec('yaml') is not None, 'requires PyYAML to import CLI')(test_env_setup_help)
