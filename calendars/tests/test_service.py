import unittest

from calendars.outlook_service import OutlookService


class FakeClient:
    def __init__(self):
        self.calls = []
        self.GRAPH = "https://graph.microsoft.com/v1.0"

    def list_events_in_range(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [{"id": "e1"}]

    def create_event(self, **kwargs):
        self.calls.append(("create", kwargs))
        return {"id": "new"}

    def _headers(self):
        return {"Authorization": "Bearer X"}


class FakeCtx:
    def ensure_client(self):
        return FakeClient()


class TestOutlookService(unittest.TestCase):
    def test_passthrough_calls(self):
        svc = OutlookService(FakeCtx())  # type: ignore[arg-type]
        from calendars.outlook_service import ListEventsRequest
        evs = svc.list_events_in_range(ListEventsRequest(start_iso="2025-01-01T00:00:00", end_iso="2025-01-31T23:59:59"))
        self.assertEqual(len(evs), 1)
        evt = svc.create_event(calendar_id=None, calendar_name=None, subject="X", start_iso="S", end_iso="E")
        self.assertEqual(evt.get("id"), "new")
        self.assertTrue(svc.headers().get("Authorization"))
        self.assertTrue(svc.graph_base().startswith("https://"))


if __name__ == '__main__':  # pragma: no cover
    unittest.main()

