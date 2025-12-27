import types
import unittest
from types import SimpleNamespace

from tests.fixtures import capture_stdout, make_outlook_event, FakeCalendarService


class TestDedupFlow(unittest.TestCase):
    def setUp(self):
        import sys
        # Stub service
        self.old_osvc = sys.modules.get('calendars.outlook_service')
        # Two masters (A,B) same Subj Monday 17:00
        vals = [
            make_outlook_event('Soccer', '2025-01-06T17:00:00+00:00', '2025-01-06T17:30:00+00:00',
                               series_id='A', created='2024-01-01T00:00:00Z', event_type='occurrence'),
            make_outlook_event('Soccer', '2025-01-13T17:00:00+00:00', '2025-01-13T17:30:00+00:00',
                               series_id='B', created='2024-06-01T00:00:00Z', event_type='occurrence'),
        ]
        mod = types.ModuleType('calendars.outlook_service')

        def factory(ctx):
            return FakeCalendarService(events=vals)
        mod.OutlookService = factory  # type: ignore
        sys.modules['calendars.outlook_service'] = mod

    def tearDown(self):
        import sys
        if self.old_osvc is None:
            sys.modules.pop('calendars.outlook_service', None)
        else:
            sys.modules['calendars.outlook_service'] = self.old_osvc

    def test_dedup_plan(self):
        from calendars.outlook.commands import run_outlook_dedup
        args = SimpleNamespace(calendar='Your Family', from_date='2025-01-01', to_date='2025-02-01', apply=False,
                               prefer_delete_nonstandard=False, keep_newest=False, delete_standardized=False,
                               profile=None, client_id=None, tenant=None, token=None)
        with capture_stdout() as buf:
            rc = run_outlook_dedup(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn('Found 1 duplicate groups', out)
        self.assertIn('Dry plan only', out)

    def test_dedup_apply(self):
        from calendars.outlook.commands import run_outlook_dedup
        args = SimpleNamespace(calendar='Your Family', from_date='2025-01-01', to_date='2025-02-01', apply=True,
                               prefer_delete_nonstandard=False, keep_newest=False, delete_standardized=False,
                               profile=None, client_id=None, tenant=None, token=None)
        with capture_stdout() as buf:
            rc = run_outlook_dedup(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn('Deleted', out)

    def test_dedup_prefer_delete_nonstandard_and_keep_newest(self):
        from calendars.outlook.commands import run_outlook_dedup
        import sys
        # Provide occurrences where one master has standardized location
        evt_a = make_outlook_event('Soccer', '2025-01-06T17:00:00+00:00', '2025-01-06T17:30:00+00:00',
                                   series_id='A', created='2024-01-01T00:00:00Z', event_type='occurrence')
        evt_b = make_outlook_event('Soccer', '2025-01-13T17:00:00+00:00', '2025-01-13T17:30:00+00:00',
                                   series_id='B', created='2024-06-01T00:00:00Z', event_type='occurrence')
        evt_b['location'] = {'address': {'street': 'X', 'city': 'Y'}}
        vals = [evt_a, evt_b]
        mod = types.ModuleType('calendars.outlook_service')

        def factory(ctx):
            return FakeCalendarService(events=vals)
        mod.OutlookService = factory  # type: ignore
        sys.modules['calendars.outlook_service'] = mod
        args = SimpleNamespace(calendar=None, from_date='2025-01-01', to_date='2025-02-01', apply=True,
                               prefer_delete_nonstandard=True, keep_newest=True, delete_standardized=False,
                               profile=None, client_id=None, tenant=None, token=None)
        with capture_stdout() as buf:
            rc = run_outlook_dedup(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        # Should choose to delete the non-standard master (A)
        self.assertIn('Deleted', out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
