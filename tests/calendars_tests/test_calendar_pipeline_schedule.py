import io
import tempfile
import datetime as _dt
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from calendars.outlook_service import EventCreationParams, RecurringEventCreationParams
from calendars.pipeline import (
    OutlookScheduleImportProcessor,
    OutlookScheduleImportProducer,
    OutlookScheduleImportRequest,
    OutlookScheduleImportRequestConsumer,
    OutlookListOneOffsProcessor,
    OutlookListOneOffsProducer,
    OutlookListOneOffsRequest,
    OutlookListOneOffsRequestConsumer,
    OutlookCalendarShareProcessor,
    OutlookCalendarShareProducer,
    OutlookCalendarShareRequest,
    OutlookCalendarShareRequestConsumer,
    OutlookMailListProcessor,
    OutlookMailListProducer,
    OutlookMailListRequest,
    OutlookMailListRequestConsumer,
    OutlookAddEventProcessor,
    OutlookAddEventProducer,
    OutlookAddEventRequest,
    OutlookAddEventRequestConsumer,
)


class CalendarExtraPipelineTests(TestCase):
    def _make_schedule_items(self):
        from calendars.importer import ScheduleItem

        return [
            ScheduleItem(subject="OneOff", start_iso="2025-01-01T10:00:00", end_iso="2025-01-01T11:00:00"),
            ScheduleItem(
                subject="Weekly Swim",
                recurrence="weekly",
                byday=["MO"],
                start_time="10:00",
                end_time="11:00",
                range_start="2025-01-01",
                range_until="2025-02-01",
            ),
            ScheduleItem(subject="Invalid"),
        ]

    def test_schedule_import_processor_apply(self):
        svc = MagicMock()
        svc.ensure_calendar_exists.return_value = "cal-1"
        items = self._make_schedule_items()
        processor = OutlookScheduleImportProcessor(schedule_loader=lambda *_, **__: items)
        request = OutlookScheduleImportRequest(
            source="in.csv",
            kind=None,
            calendar="Family",
            tz="Eastern Standard Time",
            until=None,
            dry_run=False,
            no_reminder=False,
            service=svc,
        )
        env = processor.process(OutlookScheduleImportRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.created, 2)  # type: ignore[union-attr]
        svc.create_event.assert_called_once()
        svc.create_recurring_event.assert_called_once()
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookScheduleImportProducer().produce(env)
        self.assertIn("Created 2 event series", buf.getvalue())

    def test_schedule_import_processor_dry_run(self):
        svc = MagicMock()
        svc.ensure_calendar_exists.return_value = "cal-1"
        items = self._make_schedule_items()
        processor = OutlookScheduleImportProcessor(schedule_loader=lambda *_, **__: items)
        request = OutlookScheduleImportRequest(
            source="in.csv",
            kind=None,
            calendar=None,
            tz=None,
            until=None,
            dry_run=True,
            no_reminder=True,
            service=svc,
        )
        env = processor.process(OutlookScheduleImportRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.created, 2)  # type: ignore[union-attr]
        svc.create_event.assert_not_called()
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookScheduleImportProducer().produce(env)
        self.assertIn("Preview complete", buf.getvalue())

    def test_schedule_import_handles_loader_error(self):
        svc = MagicMock()
        svc.ensure_calendar_exists.return_value = "cal-1"
        processor = OutlookScheduleImportProcessor(schedule_loader=lambda *_, **__: (_ for _ in ()).throw(ValueError("boom")))
        request = OutlookScheduleImportRequest(
            source="bad",
            kind=None,
            calendar=None,
            tz=None,
            until=None,
            dry_run=False,
            no_reminder=False,
            service=svc,
        )
        env = processor.process(OutlookScheduleImportRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_list_one_offs_pipeline(self):
        svc = MagicMock()
        svc.list_events_in_range.return_value = [
            {"type": "singleInstance", "subject": "Solo", "start": {"dateTime": "2025-01-02T10:00:00"}, "end": {"dateTime": "2025-01-02T11:00:00"}, "location": {"displayName": "Gym"}},
            {"type": "occurrence", "seriesMasterId": "S1"},
            {"subject": "NoType"},
        ]
        request = OutlookListOneOffsRequest(
            service=svc,
            calendar="Family",
            from_date="2025-01-01",
            to_date="2025-01-10",
            limit=5,
            out_path=None,
        )
        env = OutlookListOneOffsProcessor(today_factory=lambda: _dt.date(2025, 1, 3)).process(
            OutlookListOneOffsRequestConsumer(request).consume()
        )
        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.rows), 2)  # type: ignore[union-attr]
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookListOneOffsProducer().produce(env)
        self.assertIn("Found 2 single events", buf.getvalue())

    def test_list_one_offs_writes_yaml(self):
        svc = MagicMock()
        svc.list_events_in_range.return_value = [
            {"type": "singleInstance", "subject": "Solo", "start": {"dateTime": "2025-01-02T10:00:00"}, "end": {"dateTime": "2025-01-02T11:00:00"}, "location": {"displayName": "Gym"}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "one-offs.yaml"
            request = OutlookListOneOffsRequest(
                service=svc,
                calendar=None,
                from_date=None,
                to_date=None,
                limit=10,
                out_path=out,
            )
            env = OutlookListOneOffsProcessor().process(OutlookListOneOffsRequestConsumer(request).consume())
            self.assertTrue(env.ok())
            buf = io.StringIO()
            with redirect_stdout(buf):
                OutlookListOneOffsProducer().produce(env)
            self.assertIn("Wrote one-offs", buf.getvalue())
            import yaml

            data = yaml.safe_load(out.read_text())
            self.assertEqual(len(data.get("events", [])), 1)

    def test_list_one_offs_handles_error(self):
        svc = MagicMock()
        svc.list_events_in_range.side_effect = RuntimeError("boom")
        request = OutlookListOneOffsRequest(
            service=svc,
            calendar=None,
            from_date=None,
            to_date=None,
            limit=5,
            out_path=None,
        )
        env = OutlookListOneOffsProcessor().process(OutlookListOneOffsRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_calendar_share_processor(self):
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-123"
        request = OutlookCalendarShareRequest(
            service=svc,
            calendar="Family",
            recipient="user@example.com",
            role="Owner",
        )
        env = OutlookCalendarShareProcessor().process(OutlookCalendarShareRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookCalendarShareProducer().produce(env)
        self.assertIn("Shared 'Family'", buf.getvalue())

    def test_calendar_share_creates_calendar(self):
        svc = MagicMock()
        svc.find_calendar_id.return_value = None
        svc.ensure_calendar_exists.return_value = "cal-1"
        request = OutlookCalendarShareRequest(
            service=svc,
            calendar="Family",
            recipient="user@example.com",
            role="read",
        )
        env = OutlookCalendarShareProcessor().process(OutlookCalendarShareRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        svc.ensure_calendar_permission.assert_called_once()

    def test_calendar_share_handles_failure(self):
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-1"
        svc.ensure_calendar_permission.side_effect = RuntimeError("boom")
        request = OutlookCalendarShareRequest(
            service=svc,
            calendar="Family",
            recipient="user@example.com",
            role="read",
        )
        env = OutlookCalendarShareProcessor().process(OutlookCalendarShareRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_mail_list_processor_and_producer(self):
        svc = MagicMock()
        svc.list_messages.return_value = [
            {"subject": "Hello", "receivedDateTime": "2025-01-01T10:00:00Z", "from": {"emailAddress": {"address": "a@example.com"}}}
        ]
        request = OutlookMailListRequest(service=svc, folder="inbox", top=5, pages=1)
        env = OutlookMailListProcessor().process(OutlookMailListRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookMailListProducer().produce(env)
        self.assertIn("Listed 1 message", buf.getvalue())

    def test_mail_list_handles_error(self):
        svc = MagicMock()
        svc.list_messages.side_effect = RuntimeError("boom")
        request = OutlookMailListRequest(service=svc, folder="inbox", top=5, pages=1)
        env = OutlookMailListProcessor().process(OutlookMailListRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_add_event_processor_and_producer(self):
        svc = MagicMock()
        svc.create_event.return_value = {"id": "E1", "subject": "Test"}
        params = EventCreationParams(
            subject="Test",
            start_iso="2025-01-01T10:00:00",
            end_iso="2025-01-01T11:00:00",
            calendar_id=None,
            calendar_name="Family",
            tz=None,
            body_html=None,
            all_day=False,
            location=None,
            no_reminder=False,
            reminder_minutes=None,
        )
        request = OutlookAddEventRequest(service=svc, params=params)
        env = OutlookAddEventProcessor().process(OutlookAddEventRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookAddEventProducer().produce(env)
        self.assertIn("Created event", buf.getvalue())

    def test_add_event_processor_handles_error(self):
        svc = MagicMock()
        svc.create_event.side_effect = RuntimeError("boom")
        params = EventCreationParams(
            subject="Test",
            start_iso="2025-01-01T10:00:00",
            end_iso="2025-01-01T11:00:00",
            calendar_id=None,
            calendar_name="Family",
            tz=None,
            body_html=None,
            all_day=False,
            location=None,
            no_reminder=False,
            reminder_minutes=None,
        )
        request = OutlookAddEventRequest(service=svc, params=params)
        env = OutlookAddEventProcessor().process(OutlookAddEventRequestConsumer(request).consume())
        self.assertFalse(env.ok())

if __name__ == "__main__":  # pragma: no cover
    import unittest

    unittest.main()
