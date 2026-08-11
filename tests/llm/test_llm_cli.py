import io
import unittest
from contextlib import redirect_stdout

from tests.fixtures import bin_path, repo_root


class TestLlmCli(unittest.TestCase):
    def test_help(self):
        import subprocess  # nosec B404
        import sys
        root = repo_root()
        proc = subprocess.run([sys.executable, str(bin_path('llm')), '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root))  # nosec B603 - test code with trusted local script
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Unified LLM utilities', proc.stdout)

    def test_inventory_stdout(self):
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('LLM Agent Inventory', out)

    def test_familiar_stdout(self):
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['familiar', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agent_note:', out)

    def test_inventory_json(self):
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--format', 'json', '--stdout'])
        self.assertEqual(rc, 0)
        import json
        data = json.loads(buf.getvalue())
        self.assertIn('wrappers', data)
        self.assertIn('areas', data)
        self.assertIn('mail_groups', data)

    def test_inventory_is_not_self_referential(self):
        """The markdown inventory must carry real content, not a pointer to itself."""
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertNotIn('(see .llm/INVENTORY.md)', out)
        for package in ('mail', 'calendars', 'workflow', 'telemetry'):
            self.assertIn(package, out)

    def test_inventory_json_reflects_real_packages(self):
        """JSON inventory is derived from the repo, not a hardcoded stub."""
        from mail import llm_cli
        import json
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--format', 'json', '--stdout'])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        # The old stub returned exactly ["bin/mail-assistant"] and ["mail", "calendar"].
        self.assertGreater(len(data['packages']), 10)
        self.assertGreater(len(data['wrappers']), 10)
        self.assertIn('workflow', data['packages'])

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
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = repo_llm.main(['--app', 'phone', 'agentic', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agentic: phone', out)


if __name__ == '__main__':
    unittest.main()
