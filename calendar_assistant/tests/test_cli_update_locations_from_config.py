import io
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace


ADDR = {
    'street': '11099 Bathurst St',
    'city': 'Richmond Hill',
    'state': 'ON',
    'postalCode': 'L4C 0A2',
    'countryOrRegion': 'CA',
}


class FakeService:
    def __init__(self, ctx):
        self.ctx = ctx
    def list_events_in_range(self, **kwargs):
        # Monday 17:00 event with address
        return [{
            'start': {'dateTime': '2025-01-06T17:00:00+00:00'},
            'end': {'dateTime': '2025-01-06T17:30:00+00:00'},
            'location': {'displayName': 'Elgin West', 'address': ADDR},
            'id': 'occ1',
            'seriesMasterId': 'ser1',
        }]


class TestUpdateLocationsFromConfig(unittest.TestCase):
    def test_updates_yaml_with_address(self):
        import sys
        import calendar_assistant.outlook_pipelines as pipelines

        events = [{
            'subject': 'Class',
            'repeat': 'weekly',
            'byday': ['MO'],
            'start_time': '17:00',
            'end_time': '17:30',
            'range': {'start_date': '2025-01-01', 'until': '2025-02-01'},
            'location': 'Old Name',
        }]
        def fake_load(_):
            return {'events': events}
        # Stub the imported function directly in the pipelines module
        old_load_yaml = pipelines._load_yaml
        pipelines._load_yaml = fake_load

        # Stub yamlio module for dump_config (imported inside the function)
        captured = {}
        def fake_dump(path, obj):
            captured['path'] = path
            captured['obj'] = obj
        yamlio = types.ModuleType('calendar_assistant.yamlio')
        yamlio.load_config = fake_load
        yamlio.dump_config = fake_dump
        old_yamlio = sys.modules.get('calendar_assistant.yamlio')
        sys.modules['calendar_assistant.yamlio'] = yamlio

        # Stub service
        old_osvc = sys.modules.get('calendar_assistant.outlook_service')
        stub_osvc = types.ModuleType('calendar_assistant.outlook_service')
        stub_osvc.OutlookService = FakeService  # type: ignore
        sys.modules['calendar_assistant.outlook_service'] = stub_osvc

        from calendar_assistant.outlook.commands import run_outlook_update_locations
        try:
            args = SimpleNamespace(
                config='dummy.yaml', calendar=None,
                profile=None, client_id=None, tenant=None, token=None,
                dry_run=False,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = run_outlook_update_locations(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('Wrote updated locations', out)
            # Verify dump contains the standardized address
            written = captured.get('obj', {})
            self.assertIn('events', written)
            loc = written['events'][0].get('location')
            self.assertIn('Richmond Hill', loc)
            self.assertIn('11099 Bathurst St', loc)
        finally:
            # Restore original _load_yaml
            pipelines._load_yaml = old_load_yaml
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

