import io
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace


class FakeService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.updated = []

    def list_events_in_range(self, **kwargs):
        # Two matching events in the window: one series occurrence, one single
        return [
            {
                'id': 'occ-1',
                'seriesMasterId': 'ser-123',
                'start': {'dateTime': '2025-01-06T17:00:00+00:00'},  # Monday
                'end': {'dateTime': '2025-01-06T17:30:00+00:00'},
                'location': {'displayName': 'Old'},
            },
            {
                'id': 'single-1',
                'start': {'dateTime': '2025-01-13T17:00:00+00:00'},  # Monday next week
                'end': {'dateTime': '2025-01-13T17:30:00+00:00'},
                'location': {'displayName': 'Old Single'},
            },
        ]

    def update_event_location(self, *, event_id, calendar_name=None, calendar_id=None, location_str):
        self.updated.append((event_id, location_str))


class TestApplyLocationsFromConfig(unittest.TestCase):
    def test_apply_all_occurrences_updates_series_and_occurrence(self):
        import sys
        # Stub YAML wrapper to return a recurring event with a desired location
        yamlio = types.ModuleType('calendar_assistant.yamlio')
        def fake_load(_):
            return {'events': [{
                'subject': 'Class',
                'repeat': 'weekly', 'byday': ['MO'],
                'start_time': '17:00', 'end_time': '17:30',
                'range': {'start_date': '2025-01-01', 'until': '2025-02-01'},
                'location': 'Target Location',
            }]}
        yamlio.load_config = fake_load
        old_yamlio = sys.modules.get('calendar_assistant.yamlio')
        sys.modules['calendar_assistant.yamlio'] = yamlio

        # Stub service
        osvc_mod = types.ModuleType('calendar_assistant.outlook_service')
        osvc_mod.OutlookService = FakeService  # type: ignore
        old_osvc = sys.modules.get('calendar_assistant.outlook_service')
        sys.modules['calendar_assistant.outlook_service'] = osvc_mod

        from calendar_assistant import __main__ as cli
        try:
            args = SimpleNamespace(
                config='dummy.yaml', calendar=None,
                profile=None, client_id=None, tenant=None, token=None,
                dry_run=False, all_occurrences=True,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli._cmd_outlook_apply_locations_from_config(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('Applied', out)
            # Both series master and single occurrence updated
            # FakeService stores updates on instance; we can’t access it directly here
            # but we can assert message contains both update lines
            self.assertIn('Updated series', out)
            self.assertIn('Updated occurrence', out)
        finally:
            if old_yamlio is None:
                sys.modules.pop('calendar_assistant.yamlio', None)
            else:
                sys.modules['calendar_assistant.yamlio'] = old_yamlio
            if old_osvc is None:
                sys.modules.pop('calendar_assistant.outlook_service', None)
            else:
                sys.modules['calendar_assistant.outlook_service'] = old_osvc


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

