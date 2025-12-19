import subprocess
import unittest
from pathlib import Path


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class TestMoreWrappers(unittest.TestCase):
    def test_wrapper_llm_calendar_agentic(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / '..' / 'bin' / 'llm-calendar'
        self.assertTrue(wrapper.exists(), 'bin/llm-calendar not found')
        proc = run([str(wrapper), 'agentic', '--stdout'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: calendar_assistant', proc.stdout)

    def test_wrapper_llm_maker_agentic(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / '..' / 'bin' / 'llm-maker'
        self.assertTrue(wrapper.exists(), 'bin/llm-maker not found')
        proc = run([str(wrapper), 'agentic', '--stdout'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: maker', proc.stdout)

    def test_wrapper_llm_calendar_domain_map(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / '..' / 'bin' / 'llm-calendar'
        self.assertTrue(wrapper.exists(), 'bin/llm-calendar not found')
        proc = run([str(wrapper), 'domain-map', '--stdout'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Top-Level', proc.stdout)
        self.assertIn('CLI Tree', proc.stdout)

    def test_wrapper_llm_maker_domain_map(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / '..' / 'bin' / 'llm-maker'
        self.assertTrue(wrapper.exists(), 'bin/llm-maker not found')
        proc = run([str(wrapper), 'domain-map', '--stdout'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Top-Level', proc.stdout)
