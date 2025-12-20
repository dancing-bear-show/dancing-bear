import sys
import unittest

from tests.fixtures import bin_path, has_pyyaml, repo_root, run


class CalendarCLITests(unittest.TestCase):
    def test_help_via_module_invocation(self):
        proc = run([sys.executable, '-m', 'calendar_assistant', '--help'])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Calendar Assistant CLI', proc.stdout)

    test_help_via_module_invocation = unittest.skipUnless(has_pyyaml(), 'requires PyYAML to import CLI')(test_help_via_module_invocation)

    def test_help_via_assistant_wrapper(self):
        root = repo_root()
        wrapper = bin_path('assistant')
        self.assertTrue(wrapper.exists(), 'bin/assistant not found')
        proc = run([sys.executable, str(wrapper), 'calendar', '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Calendar Assistant CLI', proc.stdout)

    test_help_via_assistant_wrapper = unittest.skipUnless(has_pyyaml(), 'requires PyYAML to import CLI')(test_help_via_assistant_wrapper)

    def test_help_via_calendar_wrapper(self):
        root = repo_root()
        wrapper = bin_path('calendar')
        self.assertTrue(wrapper.exists(), 'bin/calendar not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Calendar Assistant CLI', proc.stdout)

    test_help_via_calendar_wrapper = unittest.skipUnless(has_pyyaml(), 'requires PyYAML to import CLI')(test_help_via_calendar_wrapper)

    def test_help_via_legacy_wrapper(self):
        root = repo_root()
        wrapper = bin_path('calendar-assistant')
        self.assertTrue(wrapper.exists(), 'bin/calendar-assistant not found')
        proc = run([sys.executable, str(wrapper), '--help'], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Calendar Assistant CLI', proc.stdout)

    test_help_via_legacy_wrapper = unittest.skipUnless(has_pyyaml(), 'requires PyYAML to import CLI')(test_help_via_legacy_wrapper)
