import sys
import subprocess
import unittest
from pathlib import Path


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603


class TestWrappers(unittest.TestCase):
    def test_wrapper_mail_agentic(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'mail-assistant'
        self.assertTrue(wrapper.exists(), 'bin/mail-assistant not found')
        proc = run([str(wrapper), '--agentic'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: mail', proc.stdout)

    def test_wrapper_llm_domain_map(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'llm'
        self.assertTrue(wrapper.exists(), 'bin/llm not found')
        proc = run([str(wrapper), 'domain-map', '--stdout'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('CLI Tree', proc.stdout)
        self.assertIn('Flow Map', proc.stdout)
