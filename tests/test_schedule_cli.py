# Lightweight smoke tests for schedule CLI

import sys
import unittest
from pathlib import Path

from tests.fixtures import bin_path, has_pyyaml, repo_root, run


class ScheduleCLITests(unittest.TestCase):

    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'schedule', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Schedule Assistant CLI', proc.stdout)

    def test_help_via_executable_script(self):
        root = repo_root()
        wrapper = bin_path('schedule')
        self.assertTrue(wrapper.exists(), 'bin/schedule not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Schedule Assistant CLI', proc.stdout)
        # Ensure new subcommands appear
        self.assertIn('verify', proc.stdout)
        self.assertIn('sync', proc.stdout)
        self.assertIn('export', proc.stdout)

    def test_apply_dry_run_counts(self):
        # Requires PyYAML for reading the plan
        if not has_pyyaml():  # pragma: no cover
            self.skipTest('requires PyYAML to parse plan')
        import tempfile
        import textwrap
        root = repo_root()
        wrapper = bin_path('schedule')
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
            proc = run([sys.executable, str(wrapper), 'apply', '--plan', str(plan_path)], cwd=str(root))
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn('[DRY-RUN] Would apply 2 events', proc.stdout)

    def test_agentic_flag(self):
        proc = run([sys.executable, str(bin_path('schedule')), '--agentic'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('agentic: schedule', proc.stdout)


if __name__ == "__main__":
    unittest.main()
