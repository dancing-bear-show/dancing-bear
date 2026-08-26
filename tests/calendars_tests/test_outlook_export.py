"""Unit tests for the Outlook export-plan pipeline (export.py)."""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fake service helpers
# ---------------------------------------------------------------------------

def _make_singleinstance(subject: str, start_dt: str, end_dt: str, tz: str) -> dict[str, Any]:
    return {
        "type": "singleInstance",
        "subject": subject,
        "start": {"dateTime": start_dt, "timeZone": tz},
        "end": {"dateTime": end_dt, "timeZone": tz},
        "location": {},
    }


def _make_allday(subject: str, date: str) -> dict[str, Any]:
    return {
        "type": "singleInstance",
        "subject": subject,
        "start": {"date": date},
        "end": {"date": date},
        "location": {},
    }


def _make_occurrence(subject: str, master_id: str) -> dict[str, Any]:
    return {
        "type": "occurrence",
        "subject": subject,
        "seriesMasterId": master_id,
        "start": {"dateTime": "2026-01-06T18:00:00", "timeZone": "America/Toronto"},
        "end": {"dateTime": "2026-01-06T19:00:00", "timeZone": "America/Toronto"},
        "location": {},
    }


def _make_weekly_master(
    subject: str,
    days_of_week: list[str],
    interval: int,
    start_date: str,
    end_date: str,
    tz: str,
) -> dict[str, Any]:
    return {
        "type": "seriesMaster",
        "subject": subject,
        "start": {"dateTime": f"{start_date}T18:00:00", "timeZone": tz},
        "end": {"dateTime": f"{start_date}T19:00:00", "timeZone": tz},
        "location": {},
        "recurrence": {
            "pattern": {
                "type": "weekly",
                "daysOfWeek": days_of_week,
                "interval": interval,
            },
            "range": {
                "type": "endDate",
                "startDate": start_date,
                "endDate": end_date,
            },
        },
    }


def _make_unsupported_master(subject: str, pattern_type: str) -> dict[str, Any]:
    return {
        "type": "seriesMaster",
        "subject": subject,
        "start": {"dateTime": "2026-01-06T10:00:00", "timeZone": "America/Toronto"},
        "end": {"dateTime": "2026-01-06T11:00:00", "timeZone": "America/Toronto"},
        "location": {},
        "recurrence": {
            "pattern": {
                "type": pattern_type,
                "interval": 1,
            },
            "range": {
                "type": "noEnd",
                "startDate": "2026-01-06",
            },
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DOCTOR_ONEOFF = _make_singleinstance(
    subject="Doctor",
    start_dt="2026-03-10T09:00:00",
    end_dt="2026-03-10T10:00:00",
    tz="America/Toronto",
)

SWIM_OCCURRENCE = _make_occurrence("Swim", "master-weekly-1")

HOLIDAY_ALLDAY = _make_allday("Holiday", "2026-05-18")

UNSUPPORTED_OCCURRENCE = {
    "type": "occurrence",
    "subject": "Monthly standup",
    "seriesMasterId": "master-monthly-1",
    "start": {"dateTime": "2026-01-06T10:00:00", "timeZone": "America/Toronto"},
    "end": {"dateTime": "2026-01-06T11:00:00", "timeZone": "America/Toronto"},
    "location": {},
}

SWIM_MASTER = _make_weekly_master(
    subject="Swim",
    days_of_week=["monday", "wednesday"],
    interval=1,
    start_date="2026-01-06",
    end_date="2026-06-30",
    tz="America/Toronto",
)

MONTHLY_MASTER = _make_unsupported_master("Monthly standup", "relativeMonthly")

# Map master IDs to master objects
_MASTERS = {
    "master-weekly-1": SWIM_MASTER,
    "master-monthly-1": MONTHLY_MASTER,
}


def _make_fake_service(events: list[dict[str, Any]]) -> MagicMock:
    """Build a fake Outlook service that returns the given events and mocked masters."""
    svc = MagicMock()
    svc.list_events_in_range.return_value = events
    svc.get_mailbox_timezone.return_value = "America/Toronto"

    def _get_event(event_id: str):
        return _MASTERS.get(event_id)

    svc.get_event.side_effect = _get_event
    return svc


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestOutlookExportProcessor(unittest.TestCase):
    """Tests for OutlookExportProcessor."""

    def _make_request(self, svc, **kwargs):
        from calendars.outlook_pipelines.export import OutlookExportRequest
        return OutlookExportRequest(
            service=svc,
            calendar=None,
            from_date="2026-01-01",
            to_date="2026-06-30",
            out_path=None,
            dry_run=False,
            verbose=False,
            **kwargs,
        )

    def _run(self, events: list[dict[str, Any]], **kwargs):
        from calendars.outlook_pipelines.export import OutlookExportProcessor
        svc = _make_fake_service(events)
        request = self._make_request(svc, **kwargs)
        proc = OutlookExportProcessor()
        envelope = proc.process(request)
        self.assertTrue(envelope.ok(), msg=f"Processor failed: {envelope.diagnostics}")
        return envelope.payload

    def test_one_off_event(self):
        """One-off event is exported with correct field values; no recurrence keys."""
        result = self._run([DOCTOR_ONEOFF])
        self.assertEqual(result.event_count, 1)
        ev = result.events[0]

        # Required key-by-key assertions per spec
        self.assertEqual(ev["subject"], "Doctor")
        self.assertEqual(ev["start"], "2026-03-10T09:00:00")
        self.assertEqual(ev["end"], "2026-03-10T10:00:00")
        self.assertEqual(ev["tz"], "America/Toronto")

        # Absent keys must not be present
        self.assertNotIn("repeat", ev)
        self.assertNotIn("interval", ev)
        self.assertNotIn("byday", ev)
        self.assertNotIn("start_time", ev)
        self.assertNotIn("end_time", ev)
        self.assertNotIn("range", ev)

        # Exact key set
        expected_keys = {"subject", "start", "end", "tz"}
        self.assertEqual(set(ev.keys()), expected_keys)

    def test_weekly_recurring_series(self):
        """Weekly recurring series is reversed correctly from master payload."""
        result = self._run([SWIM_OCCURRENCE])
        self.assertEqual(result.event_count, 1)
        ev = result.events[0]

        # Key-by-key per spec
        self.assertEqual(ev["subject"], "Swim")
        self.assertEqual(ev["repeat"], "weekly")
        self.assertEqual(ev["byday"], ["MO", "WE"])
        self.assertEqual(ev["start_time"], "18:00")
        self.assertEqual(ev["end_time"], "19:00")
        self.assertEqual(ev["range"], {"start_date": "2026-01-06", "until": "2026-06-30"})
        self.assertEqual(ev["tz"], "America/Toronto")

        # interval==1 must be absent
        self.assertNotIn("interval", ev)

        # Absent one-off keys
        self.assertNotIn("start", ev)
        self.assertNotIn("end", ev)

        # Exact key set
        expected_keys = {"subject", "repeat", "byday", "start_time", "end_time", "range", "tz"}
        self.assertEqual(set(ev.keys()), expected_keys)

    def test_all_day_event(self):
        """All-day event uses date strings; no start_time, end_time, or tz."""
        result = self._run([HOLIDAY_ALLDAY])
        self.assertEqual(result.event_count, 1)
        ev = result.events[0]

        self.assertEqual(ev["subject"], "Holiday")
        self.assertEqual(ev["start"], "2026-05-18")
        self.assertEqual(ev["end"], "2026-05-18")

        # Absent keys per spec
        self.assertNotIn("start_time", ev)
        self.assertNotIn("end_time", ev)
        self.assertNotIn("tz", ev)
        self.assertNotIn("repeat", ev)
        self.assertNotIn("interval", ev)
        self.assertNotIn("byday", ev)
        self.assertNotIn("range", ev)

        # Exact key set
        expected_keys = {"subject", "start", "end"}
        self.assertEqual(set(ev.keys()), expected_keys)

    def test_unsupported_pattern_relative_monthly(self):
        """relativeMonthly pattern is skipped with reason='unsupported_pattern'."""
        result = self._run([UNSUPPORTED_OCCURRENCE])
        # Monthly standup skipped
        self.assertEqual(result.event_count, 0)
        self.assertEqual(len(result.skipped), 1)
        skip = result.skipped[0]
        self.assertEqual(skip["reason"], "unsupported_pattern")
        self.assertEqual(skip["pattern_type"], "relativeMonthly")

    def test_unsupported_pattern_absolute_yearly(self):
        """absoluteYearly pattern is skipped with loud failure."""
        occ = {
            "type": "occurrence",
            "subject": "Annual review",
            "seriesMasterId": "master-yearly-1",
            "start": {"dateTime": "2026-01-01T10:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-01-01T11:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        master = _make_unsupported_master("Annual review", "absoluteYearly")
        svc = _make_fake_service([occ])
        svc.get_event.side_effect = lambda eid: master if eid == "master-yearly-1" else None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(service=svc, calendar=None, from_date="2026-01-01", to_date="2026-12-31", out_path=None)
        envelope = OutlookExportProcessor().process(request)
        result = envelope.payload
        self.assertEqual(result.event_count, 0)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0]["reason"], "unsupported_pattern")
        self.assertEqual(result.skipped[0]["pattern_type"], "absoluteYearly")

    def test_unsupported_pattern_relative_yearly(self):
        """relativeYearly pattern is skipped with loud failure."""
        occ = {
            "type": "occurrence",
            "subject": "Yearly check",
            "seriesMasterId": "master-ryearly-1",
            "start": {"dateTime": "2026-03-01T10:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-03-01T11:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        master = _make_unsupported_master("Yearly check", "relativeYearly")
        svc = _make_fake_service([occ])
        svc.get_event.side_effect = lambda eid: master if eid == "master-ryearly-1" else None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(service=svc, calendar=None, from_date="2026-01-01", to_date="2026-12-31", out_path=None)
        envelope = OutlookExportProcessor().process(request)
        result = envelope.payload
        self.assertEqual(result.event_count, 0)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0]["reason"], "unsupported_pattern")
        self.assertEqual(result.skipped[0]["pattern_type"], "relativeYearly")

    def test_full_fixture_round_trip(self):
        """Combined fixture: one-off + weekly + all-day + unsupported = 3 events, 1 skipped."""
        all_events = [DOCTOR_ONEOFF, SWIM_OCCURRENCE, HOLIDAY_ALLDAY, UNSUPPORTED_OCCURRENCE]
        result = self._run(all_events)

        self.assertEqual(result.event_count, 3)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0]["reason"], "unsupported_pattern")
        self.assertEqual(result.skipped[0]["pattern_type"], "relativeMonthly")

    def test_orphaned_master_skipped(self):
        """When get_event() returns None the occurrence is skipped as orphaned_master."""
        occ = {
            "type": "occurrence",
            "subject": "Ghost event",
            "seriesMasterId": "nonexistent-master",
            "start": {"dateTime": "2026-02-01T10:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-02-01T11:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        svc = _make_fake_service([occ])
        svc.get_event.return_value = None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(service=svc, calendar=None, from_date="2026-01-01", to_date="2026-12-31", out_path=None)
        envelope = OutlookExportProcessor().process(request)
        result = envelope.payload
        self.assertEqual(result.event_count, 0)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0]["reason"], "orphaned_master")

    def test_interval_greater_than_one_emitted(self):
        """interval > 1 is emitted explicitly in the plan event."""
        master = _make_weekly_master(
            subject="Triweekly swim",
            days_of_week=["tuesday"],
            interval=3,
            start_date="2026-01-06",
            end_date="2026-06-30",
            tz="America/Toronto",
        )
        occ = {
            "type": "occurrence",
            "subject": "Triweekly swim",
            "seriesMasterId": "master-tri-1",
            "start": {"dateTime": "2026-01-06T18:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-01-06T19:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        svc = _make_fake_service([occ])
        svc.get_event.side_effect = lambda eid: master if eid == "master-tri-1" else None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(service=svc, calendar=None, from_date="2026-01-01", to_date="2026-06-30", out_path=None)
        envelope = OutlookExportProcessor().process(request)
        result = envelope.payload
        self.assertEqual(result.event_count, 1)
        ev = result.events[0]
        self.assertEqual(ev["interval"], 3)

    def test_missing_interval_skipped(self):
        """Master with no interval key is skipped with reason='missing_interval'."""
        master = {
            "type": "seriesMaster",
            "subject": "Interval-less",
            "start": {"dateTime": "2026-01-06T10:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-01-06T11:00:00", "timeZone": "America/Toronto"},
            "location": {},
            "recurrence": {
                "pattern": {"type": "weekly", "daysOfWeek": ["monday"]},  # no interval key
                "range": {"type": "noEnd", "startDate": "2026-01-06"},
            },
        }
        occ = {
            "type": "occurrence",
            "subject": "Interval-less",
            "seriesMasterId": "master-nointerval",
            "start": {"dateTime": "2026-01-06T10:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-01-06T11:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        svc = _make_fake_service([occ])
        svc.get_event.side_effect = lambda eid: master if eid == "master-nointerval" else None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(service=svc, calendar=None, from_date="2026-01-01", to_date="2026-06-30", out_path=None)
        envelope = OutlookExportProcessor().process(request)
        result = envelope.payload
        self.assertEqual(result.event_count, 0)
        self.assertEqual(len(result.skipped), 1)
        self.assertEqual(result.skipped[0]["reason"], "missing_interval")

    def test_numbered_range_emits_count(self):
        """range.type=='numbered' emits count and no until in range."""
        master = {
            "type": "seriesMaster",
            "subject": "Counted event",
            "start": {"dateTime": "2026-01-06T09:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-01-06T10:00:00", "timeZone": "America/Toronto"},
            "location": {},
            "recurrence": {
                "pattern": {"type": "daily", "interval": 1},
                "range": {"type": "numbered", "startDate": "2026-01-06", "numberOfOccurrences": 10},
            },
        }
        occ = {
            "type": "occurrence",
            "subject": "Counted event",
            "seriesMasterId": "master-counted",
            "start": {"dateTime": "2026-01-06T09:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-01-06T10:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        svc = _make_fake_service([occ])
        svc.get_event.side_effect = lambda eid: master if eid == "master-counted" else None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(service=svc, calendar=None, from_date="2026-01-01", to_date="2026-06-30", out_path=None)
        envelope = OutlookExportProcessor().process(request)
        result = envelope.payload
        self.assertEqual(result.event_count, 1)
        ev = result.events[0]
        self.assertEqual(ev["count"], 10)
        self.assertEqual(ev["range"], {"start_date": "2026-01-06"})
        self.assertNotIn("until", ev.get("range", {}))

    def test_no_service_returns_error(self):
        """Processor fails loudly when service is None."""
        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(service=None, calendar=None, from_date=None, to_date=None, out_path=None)
        envelope = OutlookExportProcessor().process(request)
        self.assertFalse(envelope.ok())


class TestOutlookExportProducer(unittest.TestCase):
    """Tests for OutlookExportProducer output behaviour."""

    def _make_result(self, events=None, skipped=None, dry_run=False, verbose=False, out_path=None):
        from calendars.outlook_pipelines.export import OutlookExportResult
        return OutlookExportResult(
            events=events or [],
            skipped=skipped or [],
            out_path=out_path,
            dry_run=dry_run,
            verbose=verbose,
        )

    def test_verbose_reports_reasons_without_leaking_subject_or_ids(self):
        """--verbose explains skips but must not print subjects or Graph object ids."""
        from calendars.outlook_pipelines.export import OutlookExportProducer
        from core.pipeline import ResultEnvelope
        import io

        result = self._make_result(
            events=[],
            skipped=[{
                "seriesMasterId": "AAMkAG-secret-master-id",
                "subject": "Oncologist follow-up",
                "pattern_type": "relativeMonthly",
                "reason": "unsupported_pattern",
            }],
            verbose=True,
        )
        envelope = ResultEnvelope(status="success", payload=result)

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            OutlookExportProducer().produce(envelope)
        output = captured.getvalue()

        # The reason is actionable and must be shown.
        self.assertIn("unsupported_pattern", output)
        self.assertIn("relativeMonthly", output)
        # The subject and the Graph id must never reach the console.
        self.assertNotIn("Oncologist follow-up", output)
        self.assertNotIn("AAMkAG-secret-master-id", output)

    def test_prints_count_summary(self):
        from calendars.outlook_pipelines.export import OutlookExportProducer
        from core.pipeline import ResultEnvelope
        import io

        result = self._make_result(events=[{"subject": "X"}], skipped=[])
        envelope = ResultEnvelope(status="success", payload=result)
        producer = OutlookExportProducer()

        captured = io.StringIO()
        with patch("sys.stdout", captured):
            producer.produce(envelope)

        output = captured.getvalue()
        self.assertIn("Exported 1 events", output)
        self.assertIn("skipped 0", output)

    def test_dry_run_does_not_write_file(self):
        from calendars.outlook_pipelines.export import OutlookExportProducer
        from core.pipeline import ResultEnvelope
        import tempfile
        import io

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "plan.yaml"
            result = self._make_result(events=[{"subject": "X"}], dry_run=True, out_path=out)
            envelope = ResultEnvelope(status="success", payload=result)

            captured = io.StringIO()
            with patch("sys.stdout", captured):
                OutlookExportProducer().produce(envelope)

            self.assertFalse(out.exists(), "dry_run must not create the file")
            self.assertIn("dry-run", captured.getvalue())


class TestGetEventMethod(unittest.TestCase):
    """Tests for the new get_event method on OutlookCalendarMixin."""

    def test_get_event_returns_json_on_200(self):
        from core.outlook.calendar import OutlookCalendarMixin
        from unittest.mock import MagicMock, patch

        mixin = OutlookCalendarMixin.__new__(OutlookCalendarMixin)
        mixin._headers = MagicMock(return_value={"Authorization": "Bearer tok"})
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {"id": "evt1", "subject": "Test"}

        with patch("core.outlook.calendar._requests") as mock_req:
            mock_req.return_value.get.return_value = fake_response
            result = mixin.get_event("evt1")

        self.assertEqual(result, {"id": "evt1", "subject": "Test"})

    def test_get_event_returns_none_on_404(self):
        from core.outlook.calendar import OutlookCalendarMixin
        from unittest.mock import MagicMock, patch

        mixin = OutlookCalendarMixin.__new__(OutlookCalendarMixin)
        fake_response = MagicMock()
        fake_response.status_code = 404

        mixin._headers = MagicMock(return_value={"Authorization": "Bearer tok"})

        with patch("core.outlook.calendar._requests") as mock_req:
            mock_req.return_value.get.return_value = fake_response
            result = mixin.get_event("nonexistent")

        self.assertIsNone(result)

    def test_get_event_raises_on_500(self):
        from core.outlook.calendar import OutlookCalendarMixin
        from unittest.mock import MagicMock, patch

        mixin = OutlookCalendarMixin.__new__(OutlookCalendarMixin)
        fake_response = MagicMock()
        fake_response.status_code = 500
        fake_response.raise_for_status.side_effect = RuntimeError("500 error")

        mixin._headers = MagicMock(return_value={"Authorization": "Bearer tok"})

        with patch("core.outlook.calendar._requests") as mock_req:
            mock_req.return_value.get.return_value = fake_response
            with self.assertRaises(RuntimeError):
                mixin.get_event("bad-id")


class TestCLIExportPlanCommand(unittest.TestCase):
    """Integration-lite test: CLI wiring resolves without import errors."""

    def test_export_plan_command_registered(self):
        """`outlook export-plan` is reachable through the real parser."""
        from calendars.cli.main import app

        parser = app.build_parser()
        args = parser.parse_args(
            ["outlook", "export-plan", "--from", "2026-01-01", "--to", "2026-06-30"]
        )
        self.assertEqual(args.from_date, "2026-01-01")
        self.assertEqual(args.to_date, "2026-06-30")
        self.assertFalse(args.dry_run)

    def test_run_returns_failure_when_service_unavailable(self):
        """A service that cannot be built exits 1 rather than raising."""
        import argparse

        from calendars.outlook import commands

        args = argparse.Namespace(out=None, calendar=None, from_date=None, to_date=None)
        with patch.object(commands, "_build_outlook_service", return_value=None):
            self.assertEqual(commands.run_outlook_export_plan(args), 1)

    def test_default_out_path_resolves_outside_the_checkout(self):
        """The default plan path must not land inside the repo — it holds real calendar data."""
        import argparse

        from calendars.outlook import commands

        captured: dict[str, Any] = {}

        def _capture(request, _proc, _prod):
            captured["out_path"] = request.out_path
            return 0

        args = argparse.Namespace(
            out=None, calendar=None, from_date=None, to_date=None,
            dry_run=True, verbose=False,
        )
        with patch.object(commands, "_build_outlook_service", return_value=MagicMock()), \
                patch.object(commands, "run_pipeline", side_effect=_capture):
            commands.run_outlook_export_plan(args)

        out_path = captured["out_path"]
        self.assertEqual(out_path.name, "plan.yaml")
        repo_root = Path(__file__).resolve().parents[2]
        self.assertNotIn(repo_root, out_path.resolve().parents)


class TestExdatesProducer(unittest.TestCase):
    """GAP 1 — cancelled/exception occurrences are extracted as exdates by the processor."""

    def _make_cancelled_occurrence(
        self, master_id: str, original_start: str, *, is_cancelled: bool = False, occ_type: str = "occurrence"
    ) -> dict[str, Any]:
        occ: dict[str, Any] = {
            "type": occ_type,
            "subject": "Series",
            "seriesMasterId": master_id,
            "start": {"dateTime": original_start, "timeZone": "America/Toronto"},
            "end": {"dateTime": original_start, "timeZone": "America/Toronto"},
            "originalStart": original_start,
            "location": {},
        }
        if is_cancelled:
            occ["isCancelled"] = True
        return occ

    def _run_with_master(self, occurrences: list[dict[str, Any]], master: dict[str, Any]) -> Any:
        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        svc = MagicMock()
        svc.list_events_in_range.return_value = occurrences
        svc.get_mailbox_timezone.return_value = "America/Toronto"
        svc.get_event.side_effect = lambda eid: master if eid == "master-exdates-1" else None

        request = OutlookExportRequest(
            service=svc,
            calendar=None,
            from_date="2026-01-01",
            to_date="2026-12-31",
            out_path=None,
            dry_run=False,
            verbose=False,
        )
        envelope = OutlookExportProcessor().process(request)
        self.assertTrue(envelope.ok(), msg=f"Processor failed: {envelope.diagnostics}")
        return envelope.payload

    def test_exdates_extracted_from_cancelled_and_exception_occurrences(self):
        """isCancelled=True and type='exceptionOccurrence' both produce exdates entries."""
        master = _make_weekly_master(
            subject="Series",
            days_of_week=["tuesday"],
            interval=1,
            start_date="2026-03-03",
            end_date="2026-06-30",
            tz="America/Toronto",
        )
        # Normal occurrence — must NOT appear in exdates
        normal = self._make_cancelled_occurrence("master-exdates-1", "2026-03-03T10:00:00")
        # Cancelled occurrence
        cancelled = self._make_cancelled_occurrence(
            "master-exdates-1", "2026-03-10T10:00:00", is_cancelled=True
        )
        # Exception occurrence (type signals exception, not is_cancelled)
        exception_occ = self._make_cancelled_occurrence(
            "master-exdates-1", "2026-03-17T10:00:00", occ_type="exceptionOccurrence"
        )

        result = self._run_with_master([normal, cancelled, exception_occ], master)

        self.assertEqual(result.event_count, 1)
        ev = result.events[0]
        self.assertIn("exdates", ev)
        self.assertEqual(ev["exdates"], ["2026-03-10", "2026-03-17"])

    def test_exdates_absent_when_no_cancelled_occurrences(self):
        """exdates key is not emitted (not even an empty list) when nothing is cancelled."""
        master = _make_weekly_master(
            subject="Series",
            days_of_week=["tuesday"],
            interval=1,
            start_date="2026-03-03",
            end_date="2026-06-30",
            tz="America/Toronto",
        )
        # Only normal occurrences
        normal_a = self._make_cancelled_occurrence("master-exdates-1", "2026-03-03T10:00:00")
        normal_b = self._make_cancelled_occurrence("master-exdates-1", "2026-03-10T10:00:00")

        result = self._run_with_master([normal_a, normal_b], master)

        self.assertEqual(result.event_count, 1)
        ev = result.events[0]
        self.assertNotIn("exdates", ev)

    def test_exdates_deduped_and_sorted(self):
        """Duplicate cancelled dates are deduplicated; exdates is sorted ascending."""
        master = _make_weekly_master(
            subject="Series",
            days_of_week=["monday"],
            interval=1,
            start_date="2026-01-05",
            end_date="2026-06-30",
            tz="America/Toronto",
        )
        # Two cancelled occurrences on different dates, listed out of order
        late = self._make_cancelled_occurrence(
            "master-exdates-1", "2026-02-09T10:00:00", is_cancelled=True
        )
        early = self._make_cancelled_occurrence(
            "master-exdates-1", "2026-01-12T10:00:00", is_cancelled=True
        )
        # Duplicate of early — must be deduped
        dup = self._make_cancelled_occurrence(
            "master-exdates-1", "2026-01-12T10:00:00", is_cancelled=True
        )

        result = self._run_with_master([late, early, dup], master)

        self.assertEqual(result.event_count, 1)
        ev = result.events[0]
        self.assertIn("exdates", ev)
        self.assertEqual(ev["exdates"], ["2026-01-12", "2026-02-09"])


class TestDSTBoundaryExport(unittest.TestCase):
    """GAP 2 — recurring series spanning a DST transition exports wall-clock times verbatim.

    The export design's position: tz is exported verbatim (as a tz name, not an
    offset) and Graph resolves DST on re-import.  The export must NOT silently
    shift or normalize times across the DST boundary.

    The producer derives start_time / end_time from the **series master** event,
    not from any individual occurrence.  _make_weekly_master sets the master's
    dateTime to "{start_date}T18:00:00" / "{start_date}T19:00:00", so the
    expected wall-clock times from the master are always 18:00 / 19:00.
    The invariant under test is that these master times pass through unaltered
    regardless of which side of the DST boundary the occurrences fall on.
    """

    def test_dst_spring_forward_tz_and_times_unaltered(self):
        """A series spanning the 2026-03-08 spring-forward: tz is 'America/Toronto',
        start_time/end_time are the master's wall-clock times without any DST shift."""
        # Master starts before DST transition (2026-03-08 clocks spring forward).
        # _make_weekly_master sets master dateTime = "2026-03-02T18:00:00" (start_date).
        master = _make_weekly_master(
            subject="DST Series",
            days_of_week=["monday"],
            interval=1,
            start_date="2026-03-02",
            end_date="2026-04-06",
            tz="America/Toronto",
        )
        # Occurrences span the DST boundary.
        pre_dst = {
            "type": "occurrence",
            "subject": "DST Series",
            "seriesMasterId": "master-dst-1",
            "start": {"dateTime": "2026-03-02T18:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-03-02T19:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        post_dst = {
            "type": "occurrence",
            "subject": "DST Series",
            "seriesMasterId": "master-dst-1",
            "start": {"dateTime": "2026-03-16T18:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-03-16T19:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }

        svc = MagicMock()
        svc.list_events_in_range.return_value = [pre_dst, post_dst]
        svc.get_mailbox_timezone.return_value = "America/Toronto"
        svc.get_event.side_effect = lambda eid: master if eid == "master-dst-1" else None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(
            service=svc,
            calendar=None,
            from_date="2026-03-01",
            to_date="2026-04-30",
            out_path=None,
        )
        envelope = OutlookExportProcessor().process(request)
        self.assertTrue(envelope.ok(), msg=f"Processor failed: {envelope.diagnostics}")
        result = envelope.payload

        self.assertEqual(result.event_count, 1)
        ev = result.events[0]

        # tz exported verbatim as a named tz, not a UTC offset — no DST normalization
        self.assertEqual(ev["tz"], "America/Toronto")

        # start_time / end_time come from master dateTime "2026-03-02T18:00:00" / "19:00:00"
        # and must not be shifted relative to the master's wall-clock value
        self.assertEqual(ev["start_time"], "18:00")
        self.assertEqual(ev["end_time"], "19:00")

    def test_dst_fall_back_tz_and_times_unaltered(self):
        """A series spanning the 2026-11-01 fall-back: tz and master wall-clock
        times pass through unchanged; the export does not silently shift or normalize."""
        # _make_weekly_master sets master dateTime = "2026-10-21T18:00:00".
        master = _make_weekly_master(
            subject="Fall Series",
            days_of_week=["wednesday"],
            interval=1,
            start_date="2026-10-21",
            end_date="2026-11-18",
            tz="America/Toronto",
        )
        pre_fallback = {
            "type": "occurrence",
            "subject": "Fall Series",
            "seriesMasterId": "master-fallback-1",
            "start": {"dateTime": "2026-10-21T18:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-10-21T19:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }
        post_fallback = {
            "type": "occurrence",
            "subject": "Fall Series",
            "seriesMasterId": "master-fallback-1",
            "start": {"dateTime": "2026-11-04T18:00:00", "timeZone": "America/Toronto"},
            "end": {"dateTime": "2026-11-04T19:00:00", "timeZone": "America/Toronto"},
            "location": {},
        }

        svc = MagicMock()
        svc.list_events_in_range.return_value = [pre_fallback, post_fallback]
        svc.get_mailbox_timezone.return_value = "America/Toronto"
        svc.get_event.side_effect = lambda eid: master if eid == "master-fallback-1" else None

        from calendars.outlook_pipelines.export import OutlookExportProcessor, OutlookExportRequest
        request = OutlookExportRequest(
            service=svc,
            calendar=None,
            from_date="2026-10-01",
            to_date="2026-12-01",
            out_path=None,
        )
        envelope = OutlookExportProcessor().process(request)
        self.assertTrue(envelope.ok(), msg=f"Processor failed: {envelope.diagnostics}")
        result = envelope.payload

        self.assertEqual(result.event_count, 1)
        ev = result.events[0]

        # tz exported verbatim — no UTC/offset normalization across fall-back
        self.assertEqual(ev["tz"], "America/Toronto")

        # Master dateTime is "2026-10-21T18:00:00" — wall-clock 18:00 must be preserved
        self.assertEqual(ev["start_time"], "18:00")
        self.assertEqual(ev["end_time"], "19:00")


class TestResolveTzFallbackChain(unittest.TestCase):
    """GAP 3 — _resolve_tz fallback chain: event tz → mailbox tz → hardcoded fallback."""

    def _make_start_block(self, tz: str | None) -> dict[str, Any]:
        block: dict[str, Any] = {"dateTime": "2026-05-01T10:00:00"}
        if tz is not None:
            block["timeZone"] = tz
        return block

    def test_resolve_tz_uses_event_tz_when_present(self):
        """(a) timeZone in start block → returned as-is; get_mailbox_timezone never called."""
        from calendars.outlook_pipelines.export import _resolve_tz

        svc = MagicMock()
        start = self._make_start_block("Pacific/Auckland")

        result = _resolve_tz(start, svc)

        self.assertEqual(result, "Pacific/Auckland")
        svc.get_mailbox_timezone.assert_not_called()

    def test_resolve_tz_falls_back_to_mailbox_tz_when_event_tz_absent(self):
        """(b) timeZone absent → svc.get_mailbox_timezone() value is returned."""
        from calendars.outlook_pipelines.export import _resolve_tz

        svc = MagicMock()
        svc.get_mailbox_timezone.return_value = "Europe/London"
        start = self._make_start_block(None)  # no timeZone key

        result = _resolve_tz(start, svc)

        self.assertEqual(result, "Europe/London")
        svc.get_mailbox_timezone.assert_called_once()

    def test_resolve_tz_falls_back_to_mailbox_tz_when_event_tz_empty(self):
        """(b) timeZone present but empty string → treated same as absent."""
        from calendars.outlook_pipelines.export import _resolve_tz

        svc = MagicMock()
        svc.get_mailbox_timezone.return_value = "Europe/London"
        start = {"dateTime": "2026-05-01T10:00:00", "timeZone": ""}

        result = _resolve_tz(start, svc)

        self.assertEqual(result, "Europe/London")
        svc.get_mailbox_timezone.assert_called_once()

    def test_resolve_tz_final_fallback_when_mailbox_raises(self):
        """(c) timeZone absent AND get_mailbox_timezone raises → returns 'America/Toronto' with warning."""
        import warnings
        from calendars.outlook_pipelines.export import _resolve_tz

        svc = MagicMock()
        svc.get_mailbox_timezone.side_effect = RuntimeError("no mailbox")
        start = self._make_start_block(None)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _resolve_tz(start, svc)

        self.assertEqual(result, "America/Toronto")
        self.assertEqual(len(caught), 1)
        self.assertIn("America/Toronto", str(caught[0].message))

    def test_resolve_tz_final_fallback_when_mailbox_returns_none(self):
        """(c-variant) timeZone absent AND get_mailbox_timezone returns None → 'America/Toronto' with warning."""
        import warnings
        from calendars.outlook_pipelines.export import _resolve_tz

        svc = MagicMock()
        svc.get_mailbox_timezone.return_value = None
        start = self._make_start_block(None)

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = _resolve_tz(start, svc)

        self.assertEqual(result, "America/Toronto")
        self.assertEqual(len(caught), 1)
        self.assertIn("America/Toronto", str(caught[0].message))


if __name__ == "__main__":
    unittest.main()
