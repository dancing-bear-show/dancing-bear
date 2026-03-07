import unittest

from tests.fixtures import bin_path, repo_root
from tests.mixins import OutputCaptureMixin


class TestLlmCli(OutputCaptureMixin, unittest.TestCase):
    def test_help(self):
        import subprocess  # nosec B404
        import sys
        root = repo_root()
        proc = subprocess.run([sys.executable, str(bin_path('llm')), '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root))  # nosec B603 - test code with trusted local script
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Unified LLM utilities', proc.stdout)

    def test_inventory_stdout(self):
        from mail import llm_cli
        with self.capture_output() as buf:
            rc = llm_cli.main(['inventory', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('LLM Agent Inventory', out)

    def test_familiar_stdout(self):
        from mail import llm_cli
        with self.capture_output() as buf:
            rc = llm_cli.main(['familiar', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agent_note:', out)

    def test_inventory_json(self):
        from mail import llm_cli
        with self.capture_output() as buf:
            rc = llm_cli.main(['inventory', '--format', 'json', '--stdout'])
        self.assertEqual(rc, 0)
        import json
        data = json.loads(buf.getvalue())
        self.assertIn('wrappers', data)
        self.assertIn('areas', data)
        self.assertIn('mail_groups', data)

    def test_check_respects_sla_env(self):
        import subprocess  # nosec B404
        import sys
        import os
        root = repo_root()
        env = dict(os.environ)
        # Allow .llm to be considered within SLA to avoid failing in CI
        env['LLM_SLA'] = '.llm:365,Root:365'
        proc = subprocess.run([sys.executable, str(bin_path('llm')), 'check'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root), env=env)  # nosec B603 - test code with trusted local script
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)

    def test_repo_llm_app_phone(self):
        from core import llm_cli as repo_llm
        with self.capture_output() as buf:
            rc = repo_llm.main(['--app', 'phone', 'agentic', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agentic: phone', out)


if __name__ == '__main__':
    unittest.main()
