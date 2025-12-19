# Lightweight smoke tests for schedule_assistant CLI

import os
import sys
import subprocess
import unittest
from pathlib import Path


def run(cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


class ScheduleCLITests(unittest.TestCase):

    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'schedule_assistant', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Schedule Assistant CLI', proc.stdout)

    def test_help_via_executable_script(self):
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'schedule_assistant'
        self.assertTrue(wrapper.exists(), 'bin/schedule_assistant not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(repo_root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Schedule Assistant CLI', proc.stdout)
        # Ensure new subcommands appear
        self.assertIn('verify', proc.stdout)
        self.assertIn('sync', proc.stdout)
        self.assertIn('export', proc.stdout)

    def test_apply_dry_run_counts(self):
        # Requires PyYAML for reading the plan
        import importlib.util as _util
        if _util.find_spec('yaml') is None:  # pragma: no cover
            self.skipTest('requires PyYAML to parse plan')
        import tempfile, textwrap
        repo_root = Path(__file__).resolve().parents[1]
        wrapper = repo_root / 'bin' / 'schedule_assistant'
        with tempfile.TemporaryDirectory() as td:
            plan_path = Path(td) / 'plan.yaml'
            plan_yaml = textwrap.dedent(
                """
                events:
                  - subject: One-off
                    start: 2025-10-01T10:00:00
                    end: 2025-10-01T11:00:00
                  - subject: Weekly Class
                    repeat: weekly
                    byday: [MO,WE]
                    start_time: "18:00"
                    end_time: "19:00"
                    range:
                      start_date: 2025-10-01
                      until: 2025-12-31
                """
            ).strip()
            plan_path.write_text(plan_yaml, encoding='utf-8')
            proc = run([sys.executable, str(wrapper), 'apply', '--plan', str(plan_path)], cwd=str(repo_root))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn('[DRY-RUN] Would apply 2 events', proc.stdout)

    def test_agentic_flag(self):
        proc = run([sys.executable, str(Path(__file__).resolve().parents[1] / 'bin' / 'schedule_assistant'), '--agentic'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: schedule_assistant', proc.stdout)


if __name__ == "__main__":
    unittest.main()
