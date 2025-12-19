import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path


class TestLlmCli(unittest.TestCase):
    def test_help(self):
        import subprocess, sys
        root = Path(__file__).resolve().parents[1]
        proc = subprocess.run([sys.executable, str(root / 'bin' / 'llm'), '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Unified LLM utilities', proc.stdout)

    def test_inventory_stdout(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('LLM Agent Inventory', out)

    def test_familiar_stdout(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['familiar', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agent_note:', out)

    def test_inventory_json(self):
        from mail_assistant import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--format', 'json', '--stdout'])
        self.assertEqual(rc, 0)
        import json
        data = json.loads(buf.getvalue())
        self.assertIn('wrappers', data)
        self.assertIn('areas', data)
        self.assertIn('mail_assistant_groups', data)

    def test_check_respects_sla_env(self):
        import subprocess, sys, os
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        # Allow .llm to be considered within SLA to avoid failing in CI
        env['LLM_SLA'] = '.llm:365,Root:365'
        proc = subprocess.run([sys.executable, str(root / 'bin' / 'llm'), 'check'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root), env=env)
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)

    def test_repo_llm_app_phone(self):
        from personal_core import llm_cli as repo_llm
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = repo_llm.main(['--app', 'phone', 'agentic', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agentic: phone', out)


if __name__ == '__main__':
    unittest.main()
