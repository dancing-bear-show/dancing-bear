import io
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace


class FakeService:
    def __init__(self, ctx, values=None):
        self.ctx = ctx
        self.values = values or []
        self.deleted = []
    def get_calendar_id_by_name(self, name):
        return 'cal-1' if name else None
    def find_calendar_id(self, name):
        return self.get_calendar_id_by_name(name)
    def list_calendar_view(self, *, calendar_id, start_iso, end_iso, select="", top=200):
        return list(self.values)
    def delete_event_by_id(self, event_id: str) -> bool:
        self.deleted.append(event_id)
        return True


def _make_occurrence(sub, series_id, start_iso, end_iso, created):
    return {
        'subject': sub,
        'seriesMasterId': series_id,
        'type': 'occurrence',
        'start': {'dateTime': start_iso},
        'end': {'dateTime': end_iso},
        'createdDateTime': created,
    }


class TestDedupFlow(unittest.TestCase):
    def setUp(self):
        import sys
        # Stub service
        self.old_osvc = sys.modules.get('calendar_assistant.outlook_service')
        mod = types.ModuleType('calendar_assistant.outlook_service')
        mod.OutlookService = FakeService  # type: ignore
        sys.modules['calendar_assistant.outlook_service'] = mod
        # Two masters (A,B) same Subj Monday 17:00
        vals = [
            _make_occurrence('Soccer', 'A', '2025-01-06T17:00:00+00:00', '2025-01-06T17:30:00+00:00', '2024-01-01T00:00:00Z'),
            _make_occurrence('Soccer', 'B', '2025-01-13T17:00:00+00:00', '2025-01-13T17:30:00+00:00', '2024-06-01T00:00:00Z'),
        ]
        mod = types.ModuleType('calendar_assistant.outlook_service')
        def factory(ctx):
            return FakeService(ctx, vals)
        mod.OutlookService = factory  # type: ignore
        sys.modules['calendar_assistant.outlook_service'] = mod

    def tearDown(self):
        import sys
        if self.old_osvc is None:
            sys.modules.pop('calendar_assistant.outlook_service', None)
        else:
            sys.modules['calendar_assistant.outlook_service'] = self.old_osvc
        # nothing else to restore here

    def test_dedup_plan(self):
        from calendar_assistant.outlook.commands import run_outlook_dedup
        args = SimpleNamespace(calendar='Your Family', from_date='2025-01-01', to_date='2025-02-01', apply=False,
                               prefer_delete_nonstandard=False, keep_newest=False, delete_standardized=False,
                               profile=None, client_id=None, tenant=None, token=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_outlook_dedup(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn('Found 1 duplicate groups', out)
        self.assertIn('Dry plan only', out)

    def test_dedup_apply(self):
        from calendar_assistant.outlook.commands import run_outlook_dedup
        args = SimpleNamespace(calendar='Your Family', from_date='2025-01-01', to_date='2025-02-01', apply=True,
                               prefer_delete_nonstandard=False, keep_newest=False, delete_standardized=False,
                               profile=None, client_id=None, tenant=None, token=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_outlook_dedup(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        self.assertIn('Deleted', out)

    def test_dedup_prefer_delete_nonstandard_and_keep_newest(self):
        from calendar_assistant.outlook.commands import run_outlook_dedup
        import sys
        # Provide occurrences where one master has standardized location
        vals = [
            _make_occurrence('Soccer', 'A', '2025-01-06T17:00:00+00:00', '2025-01-06T17:30:00+00:00', '2024-01-01T00:00:00Z'),
            {**_make_occurrence('Soccer', 'B', '2025-01-13T17:00:00+00:00', '2025-01-13T17:30:00+00:00', '2024-06-01T00:00:00Z'), 'location': {'address': {'street': 'X', 'city': 'Y'}}},
        ]
        mod = types.ModuleType('calendar_assistant.outlook_service')
        def factory(ctx):
            return FakeService(ctx, vals)
        mod.OutlookService = factory  # type: ignore
        sys.modules['calendar_assistant.outlook_service'] = mod
        args = SimpleNamespace(calendar=None, from_date='2025-01-01', to_date='2025-02-01', apply=True,
                               prefer_delete_nonstandard=True, keep_newest=True, delete_standardized=False,
                               profile=None, client_id=None, tenant=None, token=None)
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_outlook_dedup(args)
        out = buf.getvalue()
        self.assertEqual(rc, 0, msg=out)
        # Should choose to delete the non-standard master (A)
        self.assertIn('Deleted', out)


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
