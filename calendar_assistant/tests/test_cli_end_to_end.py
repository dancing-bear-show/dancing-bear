import io
import types
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace


class FakeService:
    def __init__(self, ctx):  # matches OutlookService(OutlookContext(...))
        self.ctx = ctx
        self.created = []

    def create_event(self, **kwargs):
        self.created.append(("single", kwargs))
        return {"id": "evt_single", "subject": kwargs.get("subject")}

    def create_recurring_event(self, **kwargs):
        self.created.append(("recurring", kwargs))
        return {"id": "evt_recurring", "subject": kwargs.get("subject")}


class TestAddFromConfigFlow(unittest.TestCase):
    def test_add_from_config_uses_service(self):
        # Inject a fake YAML I/O wrapper used by the function
        import sys
        yamlio = types.ModuleType("calendar_assistant.yamlio")
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
        yamlio.load_config = fake_load_config
        old_yamlio = sys.modules.get("calendar_assistant.yamlio")
        sys.modules["calendar_assistant.yamlio"] = yamlio

        # Stub module for calendar_assistant.outlook_service to return our FakeService
        old_osvc_mod = sys.modules.get('calendar_assistant.outlook_service')
        stub_osvc = types.ModuleType('calendar_assistant.outlook_service')
        stub_osvc.OutlookService = FakeService  # type: ignore[attr-defined]
        sys.modules['calendar_assistant.outlook_service'] = stub_osvc
        from calendar_assistant import __main__ as cli
        try:
            buf = io.StringIO()
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
            with redirect_stdout(buf):
                rc = cli._cmd_outlook_add_from_config(args)
            out = buf.getvalue()
            self.assertEqual(rc, 0, msg=out)
            self.assertIn("Planned 2 events/series", out)
        finally:
            # Restore stubbed outlook_service module
            if old_osvc_mod is None:
                sys.modules.pop('calendar_assistant.outlook_service', None)
            else:
                sys.modules['calendar_assistant.outlook_service'] = old_osvc_mod
            # Clean up injected modules to avoid cross-test interference
            import sys as _sys
            if old_yamlio is None:
                _sys.modules.pop("calendar_assistant.yamlio", None)
            else:
                _sys.modules["calendar_assistant.yamlio"] = old_yamlio


if __name__ == '__main__':  # pragma: no cover
    unittest.main()
