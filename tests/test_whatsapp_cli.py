# Source Generated with Decompyle++
# File: test_whatsapp_cli.cpython-39.pyc (Python 3.9)

import sys
import unittest

from tests.fixtures import bin_path, repo_root, run


class WhatsAppCLITests(unittest.TestCase):

    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'whatsapp', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('WhatsApp Assistant CLI', proc.stdout)

    def test_help_via_executable_script(self):
        root = repo_root()
        wrapper = bin_path('whatsapp')
        self.assertTrue(wrapper.exists(), 'bin/whatsapp not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('WhatsApp Assistant CLI', proc.stdout)
