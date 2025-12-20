import os
import subprocess
import sys
import unittest

from tests.fixtures import bin_path, repo_root


class IntegrationCLITests(unittest.TestCase):
    def test_wrapper_direct_execution_help(self):
        root = repo_root()
        wrapper = bin_path('mail_assistant')
        self.assertTrue(wrapper.exists(), 'bin/mail_assistant not found')

        # Ensure it is executable for this run
        try:
            mode = os.stat(wrapper).st_mode
            os.chmod(wrapper, mode | 0o111)
        except Exception:
            pass

        proc = subprocess.run([str(wrapper), '--help'], cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Mail Assistant CLI', proc.stdout)


if __name__ == '__main__':
    unittest.main()
