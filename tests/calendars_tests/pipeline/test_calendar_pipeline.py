import io
import tempfile
import datetime as _dt
from contextlib import redirect_stdout
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock

from tests.fixtures import test_path, write_yaml
from tests.calendars_tests.fixtures import NoOpProducer, make_mock_processor

from core.pipeline import ResultEnvelope
from calendars.pipeline import (
    BaseProducer,
    RequestConsumer,
    GmailAuth,
    GmailPlanProducer,
    GmailPlanResult,
    GmailReceiptsProcessor,
    GmailReceiptsRequest,
    GmailReceiptsRequestConsumer,
    GmailScanClassesProcessor,
    GmailScanClassesProducer,
    GmailScanClassesRequest,
    GmailScanClassesRequestConsumer,
    GmailMailListProcessor,
    GmailMailListProducer,
    GmailMailListRequest,
    GmailMailListRequestConsumer,
    GmailSweepTopProcessor,
    GmailSweepTopProducer,
    GmailSweepTopRequest,
    GmailSweepTopRequestConsumer,
    OutlookVerifyProcessor,
    OutlookVerifyProducer,
    OutlookVerifyRequest,
    OutlookVerifyResult,
    OutlookVerifyRequestConsumer,
    OutlookAddProcessor,
    OutlookAddProducer,
    OutlookAddRequest,
    OutlookAddRequestConsumer,
    OutlookDedupProcessor,
    OutlookDedupProducer,
    OutlookDedupRequest,
    OutlookDedupRequestConsumer,
    OutlookRemoveProcessor,
    OutlookRemoveProducer,
    OutlookRemoveRequest,
    OutlookRemoveRequestConsumer,
    OutlookRemindersProcessor,
    OutlookRemindersProducer,
    OutlookRemindersRequest,
    OutlookRemindersRequestConsumer,
    OutlookSettingsProcessor,
    OutlookSettingsProducer,
    OutlookSettingsRequest,
    OutlookSettingsRequestConsumer,
)


def _make_occurrence(subject, series_id, start_iso, end_iso, created, location=None):
    event = {
        "subject": subject,
        "seriesMasterId": series_id,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
        "createdDateTime": created,
    }
    if location:
        event["location"] = location
    return event


class CalendarPipelineTests(TestCase):
    def _make_service(self, texts):
        svc = MagicMock()
        svc.list_message_ids.return_value = list(texts.keys())
        svc.get_message_text.side_effect = lambda mid: texts[mid]
        return svc

    def test_receipts_processor_success(self):
        sample = {
            "m1": """Enrollment in Swim Kids 3
Meeting Dates: From January 1, 2025 to March 1, 2025
Each Monday from 5:00 pm to 5:30 pm
Location: Elgin West""",
        }
        svc = self._make_service(sample)
        request = GmailReceiptsRequest(
            auth=GmailAuth(None, None, None, None),
            query=None,
            from_text="richmondhill.ca",
            days=365,
            pages=1,
            page_size=10,
            calendar="Activities",
            out_path=Path("plan.yaml"),
        )
        processor = GmailReceiptsProcessor(service_builder=lambda _auth: svc)
        env = processor.process(GmailReceiptsRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.document["events"]), 1)  # type: ignore[union-attr]

    def test_scan_classes_processor_and_producer(self):
        text = """Location: Elgin West
Monday from 5:00 pm to 5:30 pm"""
        svc = self._make_service({"m1": text})
        auth = GmailAuth(None, None, None, None)
        request = GmailScanClassesRequest(
            auth=auth,
            query=None,
            from_text="active rh",
            days=60,
            pages=1,
            page_size=10,
            inbox_only=False,
            calendar="Activities",
            out_path=None,
        )
        processor = GmailScanClassesProcessor(service_builder=lambda _auth: svc)
        env = processor.process(GmailScanClassesRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.events), 1)  # type: ignore[union-attr]
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailScanClassesProducer().produce(env)
        self.assertIn("Found 1", buf.getvalue())

    def test_scan_classes_producer_writes_yaml(self):
        text = """Location: Elgin West
Tuesday from 6:00 pm to 6:30 pm"""
        svc = self._make_service({"m1": text})
        auth = GmailAuth(None, None, None, None)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "plan.yaml"
            request = GmailScanClassesRequest(
                auth=auth,
                query=None,
                from_text=None,
                days=30,
                pages=1,
                page_size=10,
                inbox_only=True,
                calendar=None,
                out_path=out,
            )
            processor = GmailScanClassesProcessor(service_builder=lambda _auth: svc)
            env = processor.process(GmailScanClassesRequestConsumer(request).consume())
            self.assertTrue(env.ok())
            buf = io.StringIO()
            with redirect_stdout(buf):
                GmailScanClassesProducer().produce(env)
            self.assertTrue(out.exists())

    def test_scan_classes_handles_auth_error(self):
        request = GmailScanClassesRequest(
            auth=GmailAuth(None, None, None, None),
            query=None,
            from_text=None,
            days=30,
            pages=1,
            page_size=10,
            inbox_only=False,
            calendar=None,
            out_path=None,
        )
        processor = GmailScanClassesProcessor(service_builder=lambda _auth: (_ for _ in ()).throw(RuntimeError("boom")))
        env = processor.process(GmailScanClassesRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_mail_list_processor_and_producer(self):
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1"]
        svc.get_message_text.return_value = "Hello\nSecond line"
        request = GmailMailListRequest(
            auth=GmailAuth(None, None, None, None),
            query=None,
            from_text="alerts",
            days=7,
            pages=1,
            page_size=5,
            inbox_only=True,
        )
        processor = GmailMailListProcessor(service_builder=lambda _auth: svc)
        env = processor.process(GmailMailListRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailMailListProducer().produce(env)
        self.assertIn("Listed 1 Gmail message", buf.getvalue())

    def test_mail_list_handles_list_error(self):
        request = GmailMailListRequest(
            auth=GmailAuth(None, None, None, None),
            query=None,
            from_text=None,
            days=7,
            pages=1,
            page_size=5,
            inbox_only=False,
        )
        svc = MagicMock()
        svc.list_message_ids.side_effect = RuntimeError("boom")
        processor = GmailMailListProcessor(service_builder=lambda _auth: svc)
        env = processor.process(GmailMailListRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_sweep_top_processor_and_producer(self):
        svc = MagicMock()
        svc.list_message_ids.return_value = ["m1", "m2"]
        svc.get_message.side_effect = [
            {"payload": {"headers": [{"name": "From", "value": "User <u@example.com>"}]}},
            {"from": "foo@example.com"},
        ]
        request = GmailSweepTopRequest(
            auth=GmailAuth(None, None, None, None),
            query=None,
            from_text="",
            days=10,
            pages=1,
            page_size=10,
            inbox_only=True,
            top=5,
            out_path=None,
        )
        processor = GmailSweepTopProcessor(service_builder=lambda _auth: svc)
        env = processor.process(GmailSweepTopRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        buf = io.StringIO()
        with redirect_stdout(buf):
            GmailSweepTopProducer().produce(env)
        self.assertIn("Top 2 sender", buf.getvalue())

    def test_sweep_top_handles_list_error(self):
        request = GmailSweepTopRequest(
            auth=GmailAuth(None, None, None, None),
            query=None,
            from_text=None,
            days=10,
            pages=1,
            page_size=10,
            inbox_only=False,
            top=5,
            out_path=None,
        )
        svc = MagicMock()
        svc.list_message_ids.side_effect = RuntimeError("boom")
        processor = GmailSweepTopProcessor(service_builder=lambda _auth: svc)
        env = processor.process(GmailSweepTopRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_receipts_processor_handles_auth_error(self):
        request = GmailReceiptsRequest(
            auth=GmailAuth(None, None, None, None),
            query=None,
            from_text=None,
            days=30,
            pages=1,
            page_size=10,
            calendar=None,
            out_path=Path("plan.yaml"),
        )
        processor = GmailReceiptsProcessor(service_builder=lambda _auth: (_ for _ in ()).throw(RuntimeError("boom")))
        env = processor.process(GmailReceiptsRequestConsumer(request).consume())
        self.assertFalse(env.ok())
        self.assertIn("boom", env.diagnostics["message"])

    def test_plan_producer_writes_yaml(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "plan.yaml"
            payload = GmailPlanResult(document={"events": []}, out_path=out_path)
            env = ResultEnvelope(status="success", payload=payload)
            buf = io.StringIO()
            with redirect_stdout(buf):
                GmailPlanProducer().produce(env)
            self.assertTrue(out_path.exists())
            self.assertIn("Wrote 0 events", buf.getvalue())

    def test_outlook_verify_processor(self):
        cfg = {
            "events": [
                {
                    "subject": "Swim",
                    "repeat": "weekly",
                    "byday": ["MO"],
                    "start_time": "17:00",
                    "end_time": "17:30",
                    "range": {"start_date": "2025-01-01", "until": "2025-03-01"},
                }
            ]
        }
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml") as tf:
            import yaml
            yaml.safe_dump(cfg, tf)
            tf_path = Path(tf.name)
        svc = MagicMock()
        svc.list_events_in_range.return_value = [
            {
                "subject": "Swim",
                "start": {"dateTime": "2025-01-06T17:00:00"},
                "end": {"dateTime": "2025-01-06T17:30:00"},
                "type": "singleInstance",
            }
        ]
        request = OutlookVerifyRequest(config_path=tf_path, calendar=None, service=svc)
        env = OutlookVerifyProcessor().process(OutlookVerifyRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.duplicates, 1)  # type: ignore[union-attr]

    def test_outlook_verify_producer_prints_logs(self):
        buf = io.StringIO()
        payload = OutlookVerifyResult(logs=["log1"], total=1, duplicates=1, missing=0)
        env = ResultEnvelope(status="success", payload=payload)
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        self.assertIn("log1", buf.getvalue())

    def test_outlook_add_processor_and_producer(self):
        cfg = {
            "events": [
                {"subject": "Meet", "start": "2025-01-01T10:00:00", "end": "2025-01-01T11:00:00"},
                {"subject": "Series", "repeat": "weekly", "byday": ["MO"], "start_time": "10:00", "end_time": "11:00", "range": {"start_date": "2025-01-01", "until": "2025-02-01"}},
            ]
        }
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".yaml") as tf:
            import yaml
            yaml.safe_dump(cfg, tf)
            tf_path = Path(tf.name)
        svc = MagicMock()
        svc.create_event.return_value = {"id": "1"}
        svc.create_recurring_event.return_value = {"id": "2"}
        request = OutlookAddRequest(
            config_path=tf_path,
            dry_run=False,
            force_no_reminder=False,
            service=svc,
        )
        env = OutlookAddProcessor().process(OutlookAddRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.created, 2)  # type: ignore[union-attr]
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookAddProducer().produce(env)
        self.assertIn("Planned 2 events", buf.getvalue())

    def test_outlook_dedup_processor_plan_and_producer(self):
        svc = MagicMock()
        svc.find_calendar_id.return_value = "cal-1"
        svc.list_calendar_view.return_value = [
            _make_occurrence("Soccer", "A", "2025-01-06T17:00:00+00:00", "2025-01-06T17:30:00+00:00", "2024-01-01T00:00:00Z"),
            _make_occurrence("Soccer", "B", "2025-01-13T17:00:00+00:00", "2025-01-13T17:30:00+00:00", "2024-06-01T00:00:00Z"),
        ]
        request = OutlookDedupRequest(
            service=svc,
            calendar="Family",
            from_date="2025-01-01",
            to_date="2025-02-01",
        )
        env = OutlookDedupProcessor().process(OutlookDedupRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.duplicates), 1)  # type: ignore[union-attr]
        dup = env.payload.duplicates[0]  # type: ignore[union-attr]
        self.assertEqual(dup.keep, "A")
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookDedupProducer().produce(env)
        text = buf.getvalue()
        self.assertIn("Found 1 duplicate groups", text)
        self.assertIn("Dry plan only", text)

    def test_outlook_dedup_processor_apply(self):
        svc = MagicMock()
        svc.list_calendar_view.return_value = [
            _make_occurrence("Swim", "S1", "2025-02-03T18:00:00+00:00", "2025-02-03T18:30:00+00:00", "2024-01-01T00:00:00Z"),
            _make_occurrence("Swim", "S2", "2025-02-10T18:00:00+00:00", "2025-02-10T18:30:00+00:00", "2024-03-01T00:00:00Z"),
        ]
        svc.delete_event_by_id.return_value = True
        request = OutlookDedupRequest(
            service=svc,
            apply=True,
            from_date="2025-02-01",
            to_date="2025-02-28",
        )
        env = OutlookDedupProcessor().process(OutlookDedupRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertTrue(env.payload.apply)  # type: ignore[union-attr]
        self.assertEqual(env.payload.deleted, 1)  # type: ignore[union-attr]
        svc.delete_event_by_id.assert_called_once_with("S2")
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookDedupProducer().produce(env)
        text = buf.getvalue()
        self.assertIn("Deleted series master S2", text)
        self.assertIn("Deleted 1 duplicate series", text)

    def test_outlook_dedup_processor_handles_graph_error(self):
        svc = MagicMock()
        svc.list_calendar_view.side_effect = RuntimeError("boom")
        request = OutlookDedupRequest(service=svc)
        env = OutlookDedupProcessor().process(OutlookDedupRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_outlook_remove_processor_plan_and_producer(self):
        cfg = {
            "events": [
                {"subject": "Series", "repeat": "weekly", "byday": ["MO"], "start_time": "10:00", "end_time": "11:00", "range": {"start_date": "2025-01-01", "until": "2025-01-31"}},
                {"subject": "OneOff", "start": "2025-02-01T12:00:00", "end": "2025-02-01T13:00:00"},
            ]
        }
        cfg_path = write_yaml(cfg)
        svc = MagicMock()
        svc.list_events_in_range.side_effect = [
            [
                {"seriesMasterId": "S1", "start": {"dateTime": "2025-01-06T10:00:00"}, "end": {"dateTime": "2025-01-06T11:00:00"}},
            ],
            [
                {"id": "E1", "start": {"dateTime": "2025-02-01T12:00:00"}, "end": {"dateTime": "2025-02-01T13:00:00"}},
            ],
        ]
        request = OutlookRemoveRequest(
            config_path=cfg_path,
            calendar=None,
            subject_only=False,
            apply=False,
            service=svc,
        )
        env = OutlookRemoveProcessor().process(OutlookRemoveRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(len(env.payload.plan), 2)  # type: ignore[union-attr]
        first = env.payload.plan[0]  # type: ignore[union-attr]
        self.assertEqual(first.series_ids, ["S1"])
        second = env.payload.plan[1]  # type: ignore[union-attr]
        self.assertEqual(second.event_ids, ["E1"])
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemoveProducer().produce(env)
        text = buf.getvalue()
        self.assertIn("Planned deletions:", text)
        self.assertIn("Re-run with --apply", text)

    def test_outlook_remove_processor_apply(self):
        cfg = {
            "events": [
                {"subject": "Series", "repeat": "weekly", "byday": ["MO"], "start_time": "10:00", "end_time": "11:00", "range": {"start_date": "2025-01-01", "until": "2025-01-31"}},
            ]
        }
        cfg_path = write_yaml(cfg)
        svc = MagicMock()
        svc.list_events_in_range.return_value = [
            {"seriesMasterId": "S1", "start": {"dateTime": "2025-01-06T10:00:00"}, "end": {"dateTime": "2025-01-06T11:00:00"}},
        ]
        svc.delete_event_by_id.return_value = True
        request = OutlookRemoveRequest(
            config_path=cfg_path,
            calendar=None,
            subject_only=False,
            apply=True,
            service=svc,
        )
        env = OutlookRemoveProcessor().process(OutlookRemoveRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        self.assertEqual(env.payload.deleted, 1)  # type: ignore[union-attr]
        svc.delete_event_by_id.assert_called_once_with("S1")
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemoveProducer().produce(env)
        text = buf.getvalue()
        self.assertIn("Deleted series master: S1", text)
        self.assertIn("Deleted 1 items", text)

    def test_outlook_remove_processor_handles_bad_config(self):
        cfg_path = write_yaml({"foo": "bar"})
        svc = MagicMock()
        request = OutlookRemoveRequest(
            config_path=cfg_path,
            calendar=None,
            subject_only=False,
            apply=False,
            service=svc,
        )
        env = OutlookRemoveProcessor().process(OutlookRemoveRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_outlook_reminders_processor_dry_run(self):
        svc = MagicMock()
        svc.get_calendar_id_by_name.return_value = "cal-123"
        svc.list_events_in_range.return_value = [
            {"type": "seriesMaster", "id": "S1"},
            {"type": "occurrence", "id": "O1", "seriesMasterId": "S1"},
            {"type": "singleInstance", "id": "E1"},
        ]
        request = OutlookRemindersRequest(
            service=svc,
            calendar="Family",
            from_date="2025-01-01",
            to_date="2025-02-01",
            dry_run=True,
            all_occurrences=True,
             set_off=True,
             minutes=None,
        )
        env = OutlookRemindersProcessor(today_factory=lambda: _dt.date(2025, 1, 5)).process(
            OutlookRemindersRequestConsumer(request).consume()
        )
        self.assertTrue(env.ok())
        self.assertTrue(env.payload.dry_run)  # type: ignore[union-attr]
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemindersProducer().produce(env)
        out = buf.getvalue()
        self.assertIn("dry-run", out)
        self.assertIn("Preview complete.", out)
        svc.update_event_reminder.assert_not_called()

    def test_outlook_reminders_processor_apply(self):
        svc = MagicMock()
        svc.get_calendar_id_by_name.return_value = None
        svc.list_events_in_range.return_value = [
            {"type": "seriesMaster", "id": "S1"},
            {"type": "singleInstance", "id": "E1"},
        ]
        request = OutlookRemindersRequest(
            service=svc,
            calendar=None,
            from_date=None,
            to_date=None,
            dry_run=False,
            all_occurrences=False,
            set_off=True,
            minutes=None,
        )
        env = OutlookRemindersProcessor(today_factory=lambda: _dt.date(2025, 1, 5)).process(
            OutlookRemindersRequestConsumer(request).consume()
        )
        self.assertTrue(env.ok())
        self.assertFalse(env.payload.dry_run)  # type: ignore[union-attr]
        self.assertEqual(env.payload.updated, 2)  # type: ignore[union-attr]
        from calendars.outlook_service import UpdateEventReminderRequest
        svc.update_event_reminder.assert_any_call(
            UpdateEventReminderRequest(event_id="S1", calendar_id=None, calendar_name=None, is_on=False)
        )
        svc.update_event_reminder.assert_any_call(
            UpdateEventReminderRequest(event_id="E1", calendar_id=None, calendar_name=None, is_on=False)
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookRemindersProducer().produce(env)
        self.assertIn("Disabled reminders on 2 item(s).", buf.getvalue())

    def test_outlook_reminders_processor_calendar_not_found(self):
        svc = MagicMock()
        svc.get_calendar_id_by_name.return_value = None
        request = OutlookRemindersRequest(
            service=svc,
            calendar="Unknown",
            from_date=None,
            to_date=None,
            dry_run=False,
            all_occurrences=False,
            set_off=True,
            minutes=None,
        )
        env = OutlookRemindersProcessor().process(OutlookRemindersRequestConsumer(request).consume())
        self.assertFalse(env.ok())
    def test_outlook_reminders_processor_set_minutes(self):
        svc = MagicMock()
        svc.get_calendar_id_by_name.return_value = "cal-1"
        svc.list_events_in_range.return_value = [
            {"type": "seriesMaster", "id": "S1"},
        ]
        request = OutlookRemindersRequest(
            service=svc,
            calendar="Family",
            from_date="2025-01-01",
            to_date="2025-01-31",
            dry_run=False,
            all_occurrences=False,
            set_off=False,
            minutes=15,
        )
        env = OutlookRemindersProcessor().process(OutlookRemindersRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        from calendars.outlook_service import UpdateEventReminderRequest
        svc.update_event_reminder.assert_called_once_with(
            UpdateEventReminderRequest(
                event_id="S1",
                calendar_id="cal-1",
                calendar_name="Family",
                is_on=True,
                minutes_before_start=15,
            )
        )

    def test_outlook_settings_processor_dry_run(self):
        cfg = {
            "settings": {
                "defaults": {"show_as": "busy"},
                "rules": [
                    {"match": {"subject_contains": ["Swim"]}, "set": {"categories": ["Kids"], "reminder_minutes": 10}}
                ],
            }
        }
        cfg_path = write_yaml(cfg)
        svc = MagicMock()
        svc.list_events_in_range.return_value = [
            {"id": "E1", "subject": "Swim Practice", "location": {"displayName": "Pool"}},
        ]
        request = OutlookSettingsRequest(
            config_path=cfg_path,
            calendar="Family",
            from_date="2025-01-01",
            to_date="2025-01-31",
            dry_run=True,
            service=svc,
        )
        env = OutlookSettingsProcessor().process(OutlookSettingsRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookSettingsProducer().produce(env)
        out = buf.getvalue()
        self.assertIn("[dry-run] would update", out)
        self.assertIn("Preview complete. 1 item(s) matched.", out)
        svc.update_event_settings.assert_not_called()

    def test_outlook_settings_processor_apply(self):
        cfg = {
            "defaults": {"categories": ["Default"]},
            "rules": [
                {
                    "match": {"location_contains": ["Arena"]},
                    "set": {"sensitivity": "private", "is_reminder_on": "true"},
                }
            ],
        }
        cfg_path = write_yaml(cfg)
        svc = MagicMock()
        svc.list_events_in_range.return_value = [
            {"id": "E2", "subject": "Hockey", "location": {"displayName": "Community Arena"}},
        ]
        request = OutlookSettingsRequest(
            config_path=cfg_path,
            calendar=None,
            from_date=None,
            to_date=None,
            dry_run=False,
            service=svc,
        )
        env = OutlookSettingsProcessor().process(OutlookSettingsRequestConsumer(request).consume())
        self.assertTrue(env.ok())
        from calendars.outlook_service import EventSettingsPatch
        svc.update_event_settings.assert_called_once_with(
            EventSettingsPatch(
                event_id="E2",
                calendar_name=None,
                categories=["Default"],
                show_as=None,
                sensitivity="private",
                is_reminder_on=True,
                reminder_minutes=None,
            )
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookSettingsProducer().produce(env)
        self.assertIn("Applied settings to 1 item(s).", buf.getvalue())

    def test_outlook_settings_processor_bad_config(self):
        cfg_path = write_yaml({"settings": {"rules": "nope"}})
        svc = MagicMock()
        request = OutlookSettingsRequest(
            config_path=cfg_path,
            calendar=None,
            from_date=None,
            to_date=None,
            dry_run=False,
            service=svc,
        )
        env = OutlookSettingsProcessor().process(OutlookSettingsRequestConsumer(request).consume())
        self.assertFalse(env.ok())

class RequestConsumerTests(TestCase):
    """Tests for the generic RequestConsumer class."""

    def test_request_consumer_returns_request(self):
        """RequestConsumer.consume() returns the original request object."""
        request = GmailMailListRequest(
            auth=GmailAuth(None, None, None, None),
            query="test",
            from_text=None,
            days=7,
            pages=1,
            page_size=10,
            inbox_only=True,
        )
        consumer = RequestConsumer(request)
        result = consumer.consume()
        self.assertIs(result, request)

    def test_request_consumer_works_with_type_alias(self):
        """Type alias consumers work correctly with RequestConsumer."""
        request = OutlookVerifyRequest(
            config_path=Path(test_path("test.yaml")),  # noqa: S108 - test fixture path
            calendar="Family",
            service=MagicMock(),
        )
        # Using the type alias
        consumer = OutlookVerifyRequestConsumer(request)
        result = consumer.consume()
        self.assertIs(result, request)
        self.assertEqual(result.calendar, "Family")

    def test_request_consumer_preserves_all_fields(self):
        """RequestConsumer preserves all request fields."""
        auth = GmailAuth("profile", "creds", "token", "cache")
        request = GmailSweepTopRequest(
            auth=auth,
            query="from:test",
            from_text="alerts",
            days=30,
            pages=5,
            page_size=50,
            inbox_only=False,
            top=10,
            out_path=Path(test_path("out.yaml")),  # noqa: S108 - test fixture path
        )
        consumer = GmailSweepTopRequestConsumer(request)
        result = consumer.consume()
        self.assertEqual(result.auth.profile, "profile")
        self.assertEqual(result.query, "from:test")
        self.assertEqual(result.days, 30)
        self.assertEqual(result.top, 10)


class BaseProducerTests(TestCase):
    """Tests for the BaseProducer template method pattern."""

    def test_base_producer_handles_error_result(self):
        """BaseProducer.produce() prints error message for failed results."""
        env = ResultEnvelope(status="error", diagnostics={"message": "Something went wrong", "code": 1})
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        self.assertIn("Something went wrong", buf.getvalue())

    def test_base_producer_handles_error_without_message(self):
        """BaseProducer.produce() handles errors without message gracefully."""
        env = ResultEnvelope(status="error", diagnostics={"code": 1})
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        # Should not raise, just return without printing
        self.assertEqual("", buf.getvalue())

    def test_base_producer_calls_produce_success(self):
        """BaseProducer.produce() delegates to _produce_success for successful results."""
        payload = OutlookVerifyResult(logs=["test log"], total=5, duplicates=2, missing=1)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookVerifyProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("test log", output)
        self.assertIn("Checked 5 recurring entries", output)
        self.assertIn("Duplicates: 2", output)
        self.assertIn("Missing: 1", output)

    def test_base_producer_print_logs_helper(self):
        """BaseProducer.print_logs() prints each log line."""
        producer = OutlookVerifyProducer()
        buf = io.StringIO()
        with redirect_stdout(buf):
            producer.print_logs(["line1", "line2", "line3"])
        output = buf.getvalue()
        self.assertIn("line1", output)
        self.assertIn("line2", output)
        self.assertIn("line3", output)

    def test_base_producer_print_error_returns_true_on_error(self):
        """BaseProducer.print_error() returns True when result has error."""
        env = ResultEnvelope(status="error", diagnostics={"message": "fail"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = BaseProducer.print_error(env)
        self.assertTrue(result)
        self.assertIn("fail", buf.getvalue())

    def test_base_producer_print_error_returns_false_on_success(self):
        """BaseProducer.print_error() returns False when result is successful."""
        env = ResultEnvelope(status="success", payload=None)
        result = BaseProducer.print_error(env)
        self.assertFalse(result)


class RunPipelineTests(TestCase):
    """Tests for the run_pipeline helper function."""

    def test_run_pipeline_returns_zero_on_success(self):
        """run_pipeline() returns 0 when processor returns success."""
        from core.pipeline import run_pipeline

        Processor = make_mock_processor(ResultEnvelope(status="success", payload={"data": "test"}))
        result = run_pipeline({"test": 123}, Processor, NoOpProducer)
        self.assertEqual(0, result)

    def test_run_pipeline_returns_error_code_on_failure(self):
        """run_pipeline() returns error code from diagnostics on failure."""
        from core.pipeline import run_pipeline

        Processor = make_mock_processor(ResultEnvelope(status="error", diagnostics={"code": 42, "message": "fail"}))
        result = run_pipeline({}, Processor, NoOpProducer)
        self.assertEqual(42, result)

    def test_run_pipeline_returns_default_code_on_failure_without_code(self):
        """run_pipeline() returns 2 when error has no code in diagnostics."""
        from core.pipeline import run_pipeline

        Processor = make_mock_processor(ResultEnvelope(status="error", diagnostics={"message": "fail"}))
        result = run_pipeline({}, Processor, NoOpProducer)
        self.assertEqual(2, result)

    def test_run_pipeline_calls_producer_with_envelope(self):
        """run_pipeline() passes the envelope from processor to producer."""
        from core.pipeline import run_pipeline

        captured_envelope = []

        class MockProcessor:
            def process(self, req):
                return ResultEnvelope(status="success", payload={"from_request": req})

        class CapturingProducer:
            def produce(self, env):
                captured_envelope.append(env)

        run_pipeline({"key": "value"}, MockProcessor, CapturingProducer)
        self.assertEqual(1, len(captured_envelope))
        self.assertEqual({"from_request": {"key": "value"}}, captured_envelope[0].payload)

    def test_run_pipeline_passes_request_to_processor(self):
        """run_pipeline() passes the request directly to processor.process()."""
        from core.pipeline import run_pipeline

        captured_request = []

        class CapturingProcessor:
            def process(self, req):
                captured_request.append(req)
                return ResultEnvelope(status="success", payload=None)

        test_request = {"field1": "a", "field2": 42}
        run_pipeline(test_request, CapturingProcessor, NoOpProducer)
        self.assertEqual(1, len(captured_request))
        self.assertEqual(test_request, captured_request[0])


class CheckServiceRequiredTests(TestCase):
    """Tests for the check_service_required helper function."""

    def test_check_service_required_returns_none_when_service_exists(self):
        """check_service_required() returns None when service is not None."""
        from calendars.pipeline_base import check_service_required

        # Should not raise for valid service
        check_service_required(MagicMock())

    def test_check_service_required_raises_when_none(self):
        """check_service_required() raises ValueError when service is None."""
        from calendars.pipeline_base import check_service_required

        with self.assertRaises(ValueError) as ctx:
            check_service_required(None)
        self.assertIn("service is required", str(ctx.exception))

    def test_check_service_required_uses_custom_error_message(self):
        """check_service_required() uses custom error message when provided."""
        from calendars.pipeline_base import check_service_required

        with self.assertRaises(ValueError) as ctx:
            check_service_required(None, error_msg="Custom error message")
        self.assertEqual("Custom error message", str(ctx.exception))

    def test_check_service_required_in_processor_pattern(self):
        """check_service_required() works within SafeProcessor pattern."""
        from calendars.pipeline_base import check_service_required

        # Valid service - no exception
        service = MagicMock()
        try:
            check_service_required(service)
        except ValueError:
            self.fail("Should not raise for valid service")

        # None service - raises, which SafeProcessor catches
        with self.assertRaises(ValueError):
            check_service_required(None)
