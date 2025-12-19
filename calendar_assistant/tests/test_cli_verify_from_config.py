import io
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace


class FakeService:
    def __init__(self, ctx):
        self.ctx = ctx
    def list_events_in_range(self, **kwargs):
        # Return one Monday 17:00-17:30 event; nothing else
        return [
            {
                'start': {'dateTime': '2025-01-06T17:00:00+00:00'},  # Monday
                'end': {'dateTime': '2025-01-06T17:30:00+00:00'},
            }
        ]


class TestVerifyFromConfigFlow(unittest.TestCase):
    def test_verify_from_config_duplicates_and_missing(self):
        import sys
        # Stub YAML loader to provide two events, one matching and one missing
        yamlio = types.ModuleType("calendar_assistant.yamlio")
        def fake_load_config(_path):
            return {
                'events': [
                    {
                        'subject': 'Match',
                        'repeat': 'weekly',
                        'byday': ['MO'],
                        'start_time': '17:00',
                        'end_time': '17:30',
                        'range': {'start_date': '2025-01-01', 'until': '2025-02-01'},
                    },
                    {
                        'subject': 'Missing',
                        'repeat': 'weekly',
                        'byday': ['WE'],
                        'start_time': '17:00',
                        'end_time': '17:30',
                        'range': {'start_date': '2025-01-01', 'until': '2025-02-01'},
                    },
                ]
            }
        yamlio.load_config = fake_load_config
        old_yaml = sys.modules.get('calendar_assistant.yamlio')
        sys.modules['calendar_assistant.yamlio'] = yamlio

        # Stub OutlookService used by the command
        old_osvc_mod = sys.modules.get('calendar_assistant.outlook_service')
        stub_osvc = types.ModuleType('calendar_assistant.outlook_service')
        stub_osvc.OutlookService = FakeService  # type: ignore
        sys.modules['calendar_assistant.outlook_service'] = stub_osvc

        from calendar_assistant import __main__ as cli
        try:
            args = SimpleNamespace(
                config='dummy.yaml', calendar=None,
                profile=None, client_id=None, tenant=None, token=None
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = cli._cmd_outlook_verify_from_config(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn('Checked 2 recurring entries', out)
            self.assertIn('Duplicates: 1, Missing: 1', out)
        finally:
            # Restore modules
            if old_osvc_mod is None:
                sys.modules.pop('calendar_assistant.outlook_service', None)
            else:
                sys.modules['calendar_assistant.outlook_service'] = old_osvc_mod
            if old_yaml is None:
                sys.modules.pop('calendar_assistant.yamlio', None)
            else:
                sys.modules['calendar_assistant.yamlio'] = old_yaml


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
