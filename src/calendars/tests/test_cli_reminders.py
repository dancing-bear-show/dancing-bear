import types
import unittest
from types import SimpleNamespace

from tests.fixtures import capture_stdout, FakeCalendarService


class TestRemindersFlows(unittest.TestCase):
    def setUp(self):
        import sys
        self.old_osvc = sys.modules.get('calendars.outlook_service')
        # Provide a series master, an occurrence, and a single event
        events = [
            {'id': 'ser-1', 'type': 'seriesMaster'},
            {'id': 'occ-1', 'type': 'occurrence', 'seriesMasterId': 'ser-1'},
            {'id': 'single-1', 'type': 'singleInstance'},
        ]
        mod = types.ModuleType('calendars.outlook_service')
        mod.OutlookService = lambda ctx: FakeCalendarService(events=events)  # type: ignore
        sys.modules['calendars.outlook_service'] = mod

    def tearDown(self):
        import sys
        if self.old_osvc is None:
            sys.modules.pop('calendars.outlook_service', None)
        else:
            sys.modules['calendars.outlook_service'] = self.old_osvc

    def test_reminders_off(self):
        from calendars.outlook.commands import run_outlook_reminders_off
        args = SimpleNamespace(calendar=None, from_date='2025-01-01', to_date='2025-01-31', all_occurrences=True, dry_run=False,
                               profile=None, client_id=None, tenant=None, token=None)
        with capture_stdout() as buf:
            rc = run_outlook_reminders_off(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn('Disabled reminders on', out)

    def test_reminders_set_minutes(self):
        from calendars.outlook.commands import run_outlook_reminders_set
        args = SimpleNamespace(calendar=None, from_date='2025-01-01', to_date='2025-01-31', off=False, minutes=10, dry_run=False,
                               profile=None, client_id=None, tenant=None, token=None)
        with capture_stdout() as buf:
            rc = run_outlook_reminders_set(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn('Updated reminders on', out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
