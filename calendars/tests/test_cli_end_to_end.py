import types
import unittest
from types import SimpleNamespace

from tests.fixtures import capture_stdout, FakeCalendarService


class TestAddFromConfigFlow(unittest.TestCase):
    def test_add_from_config_uses_service(self):
        import sys
        import calendars.outlook_pipelines as pipelines

        def fake_load_config(_path):
            # one recurring and one single event
            return {
                "events": [
                    {
                        "subject": "Class",
                        "calendar": "Your Family",
                        "repeat": "weekly",
                        "byday": ["MO"],
                        "start_time": "17:00",
                        "end_time": "17:30",
                        "range": {"start_date": "2025-01-01", "until": "2025-02-01"},
                    },
                    {
                        "subject": "One-Off",
                        "calendar": "Your Family",
                        "start": "2025-01-10T17:00:00",
                        "end": "2025-01-10T17:30:00",
                    },
                ]
            }
        # Stub the imported function directly in the pipelines module
        old_load_yaml = pipelines._load_yaml
        pipelines._load_yaml = fake_load_config

        # Stub module for calendar.outlook_service to return our FakeCalendarService
        old_osvc_mod = sys.modules.get('calendars.outlook_service')
        stub_osvc = types.ModuleType('calendars.outlook_service')
        stub_osvc.OutlookService = lambda ctx: FakeCalendarService()  # type: ignore[attr-defined]
        sys.modules['calendars.outlook_service'] = stub_osvc
        from calendars.outlook.commands import run_outlook_add_from_config
        try:
            args = SimpleNamespace(
                config="dummy.yaml",
                calendar=None,
                no_reminder=False,
                dry_run=False,
                profile=None,
                client_id=None,
                tenant=None,
                token=None,
            )
            with capture_stdout() as buf:
                rc = run_outlook_add_from_config(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("Planned 2 events/series", out)
        finally:
            # Restore stubbed outlook_service module
            if old_osvc_mod is None:
                sys.modules.pop('calendars.outlook_service', None)
            else:
                sys.modules['calendars.outlook_service'] = old_osvc_mod
            # Restore original _load_yaml
            pipelines._load_yaml = old_load_yaml


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
