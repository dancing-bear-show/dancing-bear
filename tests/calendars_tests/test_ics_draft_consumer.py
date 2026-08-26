"""Tests for the ICS draft consumer pipeline.

Covers:
- One-off event with datetime (DTSTART/DTEND with time)
- All-day event (VALUE=DATE)
- Weekly recurring event with RRULE (BYDAY, INTERVAL)
- Default path creates a DRAFT and never sends
- dry-run does not call create_draft_raw
- ICS content is asserted, not just presence
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.fixtures import write_yaml

from calendars.outlook_pipelines.ics_draft import (
    IcsDraftProcessor,
    IcsDraftProducer,
    IcsDraftRequest,
    IcsDraftResult,
    _build_vcalendar,
    _build_vevent,
    _build_rrule,
)
from core.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_plan_yaml(events: list[dict], tmp_dir: str) -> Path:
    """Write a plan YAML file and return its path."""
    written = write_yaml({"events": events}, dir=tmp_dir, filename="plan.yaml")
    return Path(written)


def _fake_gmail_client(draft_id: str = "draft-abc-123") -> MagicMock:
    """Return a mock GmailClient that records calls to create_draft_raw."""
    client = MagicMock()
    client.create_draft_raw.return_value = {"id": draft_id}
    return client


# ---------------------------------------------------------------------------
# Unit tests for ICS builder helpers
# ---------------------------------------------------------------------------


class TestBuildRrule(unittest.TestCase):
    def test_weekly_byday_interval(self):
        nev = {
            "repeat": "weekly",
            "interval": 2,
            "byday": ["MO", "WE"],
        }
        rrule = _build_rrule(nev)
        self.assertIsNotNone(rrule)
        self.assertIn("FREQ=WEEKLY", rrule)
        self.assertIn("INTERVAL=2", rrule)
        self.assertIn("BYDAY=MO,WE", rrule)

    def test_weekly_with_until(self):
        nev = {
            "repeat": "weekly",
            "byday": ["FR"],
            "range": {"until": "2026-12-31"},
        }
        rrule = _build_rrule(nev)
        self.assertIn("UNTIL=20261231T235959Z", rrule)
        self.assertNotIn("COUNT", rrule)

    def test_daily_count(self):
        nev = {"repeat": "daily", "count": 5}
        rrule = _build_rrule(nev)
        self.assertIn("FREQ=DAILY", rrule)
        self.assertIn("COUNT=5", rrule)

    def test_no_repeat_returns_none(self):
        self.assertIsNone(_build_rrule({}))
        self.assertIsNone(_build_rrule({"subject": "Test"}))

    def test_interval_1_omitted(self):
        nev = {"repeat": "weekly", "interval": 1, "byday": ["TU"]}
        rrule = _build_rrule(nev)
        self.assertNotIn("INTERVAL", rrule)

    def test_monthly(self):
        nev = {"repeat": "monthly"}
        rrule = _build_rrule(nev)
        self.assertIn("FREQ=MONTHLY", rrule)


class TestBuildVevent(unittest.TestCase):
    def test_one_off_event_has_uid_summary_dtstart_dtend(self):
        nev = {
            "subject": "Sync Meeting",
            "start": "2026-09-15T10:00:00",
            "end": "2026-09-15T11:00:00",
        }
        lines = _build_vevent(nev)
        text = "\n".join(lines)
        self.assertIn("BEGIN:VEVENT", text)
        self.assertIn("END:VEVENT", text)
        self.assertIn("SUMMARY:Sync Meeting", text)
        self.assertIn("UID:", text)
        self.assertIn("DTSTART:", text)
        self.assertIn("DTEND:", text)
        # Must not contain RRULE for a one-off
        self.assertNotIn("RRULE:", text)

    def test_all_day_event_uses_value_date(self):
        nev = {
            "subject": "Company Holiday",
            "start": "2026-10-01",
            "end": "2026-10-02",
        }
        lines = _build_vevent(nev)
        text = "\n".join(lines)
        self.assertIn("DTSTART;VALUE=DATE:20261001", text)
        self.assertIn("DTEND;VALUE=DATE:20261002", text)
        self.assertNotIn("RRULE:", text)

    def test_weekly_recurring_has_rrule_byday(self):
        nev = {
            "subject": "Swim Class",
            "repeat": "weekly",
            "interval": 1,
            "byday": ["MO", "WE"],
            "start_time": "17:00",
            "end_time": "17:30",
            "range": {"start_date": "2026-09-08", "until": "2026-12-15"},
        }
        lines = _build_vevent(nev)
        text = "\n".join(lines)
        self.assertIn("RRULE:", text)
        self.assertIn("FREQ=WEEKLY", text)
        self.assertIn("BYDAY=MO,WE", text)
        self.assertIn("UNTIL=20261215T235959Z", text)
        self.assertIn("DTSTART:", text)

    def test_location_included(self):
        nev = {
            "subject": "Gym Session",
            "start": "2026-09-01T09:00:00",
            "end": "2026-09-01T10:00:00",
            "location": "Elgin West",
        }
        lines = _build_vevent(nev)
        text = "\n".join(lines)
        self.assertIn("LOCATION:Elgin West", text)

    def test_exdates_included(self):
        nev = {
            "subject": "Yoga",
            "repeat": "weekly",
            "byday": ["TU"],
            "start_time": "08:00",
            "end_time": "09:00",
            "range": {"start_date": "2026-09-01"},
            "exdates": ["2026-10-06", "2026-10-13"],
        }
        lines = _build_vevent(nev)
        text = "\n".join(lines)
        self.assertIn("EXDATE;VALUE=DATE:20261006,20261013", text)

    def test_tz_applied_to_dtstart(self):
        nev = {
            "subject": "Morning Standup",
            "start": "2026-09-10T09:00:00",
            "end": "2026-09-10T09:15:00",
            "tz": "America/Toronto",
        }
        lines = _build_vevent(nev)
        text = "\n".join(lines)
        self.assertIn("TZID=America/Toronto:", text)


class TestBuildVcalendar(unittest.TestCase):
    def test_wrapper_structure(self):
        vevent_lines = ["BEGIN:VEVENT", "UID:abc", "SUMMARY:Test", "END:VEVENT"]
        ics = _build_vcalendar(vevent_lines)
        self.assertTrue(ics.startswith("BEGIN:VCALENDAR"))
        self.assertIn("VERSION:2.0", ics)
        self.assertIn("PRODID:-//dancing-bear//calendar-plan//EN", ics)
        self.assertIn("BEGIN:VEVENT", ics)
        self.assertIn("END:VEVENT", ics)
        self.assertTrue(ics.rstrip("\r\n").endswith("END:VCALENDAR"))

    def test_uses_crlf_line_endings(self):
        vevent_lines = ["BEGIN:VEVENT", "SUMMARY:Test", "END:VEVENT"]
        ics = _build_vcalendar(vevent_lines)
        self.assertIn("\r\n", ics)


# ---------------------------------------------------------------------------
# Integration tests using IcsDraftProcessor
# ---------------------------------------------------------------------------


class TestIcsDraftProcessorOneOff(unittest.TestCase):
    """A one-off event is processed and ICS content is correct."""

    def _make_request(self, config_path: Path, dry_run: bool = True, gmail_client=None) -> IcsDraftRequest:
        return IcsDraftRequest(
            config_path=config_path,
            recipient="test@example.com",
            subject="My Calendar Draft",
            dry_run=dry_run,
            gmail_client=gmail_client,
        )

    def test_one_off_event_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "Doctor Appointment", "start": "2026-09-20T14:00:00", "end": "2026-09-20T15:00:00"}],
                tmp,
            )
            req = self._make_request(plan, dry_run=True)
            processor = IcsDraftProcessor()
            env = processor.process(req)

        self.assertTrue(env.ok(), env.diagnostics)
        result: IcsDraftResult = env.payload
        self.assertEqual(result.event_count, 1)
        self.assertIsNone(result.draft_id)  # dry-run: no draft created
        self.assertIn("BEGIN:VCALENDAR", result.ics_payload)
        self.assertIn("SUMMARY:Doctor Appointment", result.ics_payload)
        self.assertIn("DTSTART:", result.ics_payload)

    def test_one_off_event_creates_draft(self):
        gmail = _fake_gmail_client("draft-111")
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "Doctor Appointment", "start": "2026-09-20T14:00:00", "end": "2026-09-20T15:00:00"}],
                tmp,
            )
            req = self._make_request(plan, dry_run=False, gmail_client=gmail)
            processor = IcsDraftProcessor()
            env = processor.process(req)

        self.assertTrue(env.ok(), env.diagnostics)
        result: IcsDraftResult = env.payload
        self.assertEqual(result.draft_id, "draft-111")
        self.assertEqual(result.event_count, 1)

        # create_draft_raw was called exactly once, never send_message_raw
        gmail.create_draft_raw.assert_called_once()
        gmail.send_message_raw.assert_not_called()

    def test_default_path_never_sends(self):
        """Default (non-dry-run) path must call create_draft_raw only, never any send path."""
        gmail = _fake_gmail_client()
        # Ensure no "send" attribute is called; MagicMock records all calls
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "Team Sync", "start": "2026-10-01T10:00:00", "end": "2026-10-01T10:30:00"}],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="team@example.com",
                subject="Team Sync ICS",
                dry_run=False,
                gmail_client=gmail,
            )
            processor = IcsDraftProcessor()
            env = processor.process(req)

        self.assertTrue(env.ok(), env.diagnostics)
        gmail.create_draft_raw.assert_called_once()
        # Verify send was never invoked
        self.assertEqual(gmail.send_message_raw.call_count, 0)


class TestIcsDraftProcessorAllDay(unittest.TestCase):
    """All-day events use VALUE=DATE in DTSTART/DTEND."""

    def test_all_day_event_ics(self):
        gmail = _fake_gmail_client()
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "Public Holiday", "start": "2026-12-25", "end": "2026-12-26"}],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="user@example.com",
                subject="Holidays",
                dry_run=False,
                gmail_client=gmail,
            )
            processor = IcsDraftProcessor()
            env = processor.process(req)

        self.assertTrue(env.ok(), env.diagnostics)
        result: IcsDraftResult = env.payload
        self.assertIn("DTSTART;VALUE=DATE:20261225", result.ics_payload)
        self.assertIn("DTEND;VALUE=DATE:20261226", result.ics_payload)
        self.assertNotIn("RRULE:", result.ics_payload)


class TestIcsDraftProcessorRecurring(unittest.TestCase):
    """Weekly recurring events produce a correct RRULE including BYDAY and INTERVAL."""

    def test_weekly_recurring_rrule(self):
        gmail = _fake_gmail_client("draft-weekly-001")
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{
                    "subject": "Swim Kids 3",
                    "repeat": "weekly",
                    "interval": 2,
                    "byday": ["MO", "WE"],
                    "start_time": "17:00",
                    "end_time": "17:30",
                    "tz": "America/Toronto",
                    "range": {"start_date": "2026-09-07", "until": "2026-12-14"},
                    "location": "Elgin West Community Centre",
                }],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="family@example.com",
                subject="Swim Schedule",
                dry_run=False,
                gmail_client=gmail,
            )
            processor = IcsDraftProcessor()
            env = processor.process(req)

        self.assertTrue(env.ok(), env.diagnostics)
        result: IcsDraftResult = env.payload
        ics = result.ics_payload

        # RRULE must contain all three parts
        self.assertIn("RRULE:FREQ=WEEKLY", ics)
        self.assertIn("INTERVAL=2", ics)
        self.assertIn("BYDAY=MO,WE", ics)
        self.assertIn("UNTIL=20261214T235959Z", ics)

        # DTSTART should include timezone
        self.assertIn("TZID=America/Toronto:", ics)

        # Location
        self.assertIn("LOCATION:Elgin West Community Centre", ics)

        # Draft was created, not sent
        gmail.create_draft_raw.assert_called_once()
        gmail.send_message_raw.assert_not_called()
        self.assertEqual(result.draft_id, "draft-weekly-001")

    def test_weekly_byday_maps_directly(self):
        """byday codes (MO, WE) are RRULE's own convention — must not be transformed."""
        nev = {
            "subject": "Test",
            "repeat": "weekly",
            "byday": ["MO", "WE", "FR"],
            "range": {"start_date": "2026-09-01"},
            "start_time": "09:00",
            "end_time": "10:00",
        }
        vevent = _build_vevent(nev)
        text = "\n".join(vevent)
        # Codes must appear exactly as provided — uppercase 2-char RRULE codes
        self.assertIn("BYDAY=MO,WE,FR", text)


class TestIcsDraftDryRun(unittest.TestCase):
    """dry-run must print intent but must NOT call create_draft_raw."""

    def test_dry_run_does_not_create_draft(self):
        gmail = _fake_gmail_client()
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "Dry Run Event", "start": "2026-11-01T09:00:00", "end": "2026-11-01T10:00:00"}],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="nobody@example.com",
                subject="Dry Run",
                dry_run=True,
                gmail_client=gmail,
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                processor = IcsDraftProcessor()
                env = processor.process(req)

        self.assertTrue(env.ok(), env.diagnostics)
        self.assertIsNone(env.payload.draft_id)
        # create_draft_raw must NOT have been called
        gmail.create_draft_raw.assert_not_called()
        output = buf.getvalue()
        self.assertIn("[dry-run]", output)

    def test_dry_run_without_gmail_client_is_ok(self):
        """dry-run with gmail_client=None must succeed (no auth needed)."""
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "No-Auth Dry Run", "start": "2026-11-02T08:00:00", "end": "2026-11-02T09:00:00"}],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="nobody@example.com",
                subject="No-Auth",
                dry_run=True,
                gmail_client=None,
            )
            processor = IcsDraftProcessor()
            env = processor.process(req)

        self.assertTrue(env.ok(), env.diagnostics)
        self.assertIsNone(env.payload.draft_id)


class TestIcsDraftRunPipeline(unittest.TestCase):
    """Smoke test via the run_pipeline entrypoint."""

    def test_run_pipeline_returns_zero_on_success(self):
        gmail = _fake_gmail_client()
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "Pipeline Test", "start": "2026-09-30T10:00:00", "end": "2026-09-30T11:00:00"}],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="ops@example.com",
                subject="Pipeline Test Draft",
                dry_run=False,
                gmail_client=gmail,
            )
            exit_code = run_pipeline(req, IcsDraftProcessor, IcsDraftProducer)

        self.assertEqual(exit_code, 0)

    def test_run_pipeline_dry_run_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [{"subject": "Dry Pipeline", "start": "2026-09-30T10:00:00", "end": "2026-09-30T11:00:00"}],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="ops@example.com",
                subject="Dry Run",
                dry_run=True,
                gmail_client=None,
            )
            exit_code = run_pipeline(req, IcsDraftProcessor, IcsDraftProducer)

        self.assertEqual(exit_code, 0)


class TestIcsDraftMultipleEvents(unittest.TestCase):
    """Multiple events produce multiple VEVENT blocks."""

    def test_multiple_events_count(self):
        gmail = _fake_gmail_client()
        with tempfile.TemporaryDirectory() as tmp:
            plan = _make_plan_yaml(
                [
                    {"subject": "Event A", "start": "2026-09-01T09:00:00", "end": "2026-09-01T10:00:00"},
                    {"subject": "Event B", "start": "2026-09-02T09:00:00", "end": "2026-09-02T10:00:00"},
                    {"subject": "Event C", "start": "2026-09-03T09:00:00", "end": "2026-09-03T10:00:00"},
                ],
                tmp,
            )
            req = IcsDraftRequest(
                config_path=plan,
                recipient="user@example.com",
                subject="Multi Event",
                dry_run=False,
                gmail_client=gmail,
            )
            processor = IcsDraftProcessor()
            env = processor.process(req)

        self.assertTrue(env.ok())
        result: IcsDraftResult = env.payload
        self.assertEqual(result.event_count, 3)
        self.assertEqual(result.ics_payload.count("BEGIN:VEVENT"), 3)
        self.assertIn("SUMMARY:Event A", result.ics_payload)
        self.assertIn("SUMMARY:Event B", result.ics_payload)
        self.assertIn("SUMMARY:Event C", result.ics_payload)


class TestGmailClientWiring(unittest.TestCase):
    """The non-dry-run path must build a client that can actually create a draft.

    Regression test: run_outlook_ics_draft originally used
    build_gmail_service_from_args, which returns calendars.gmail_service.GmailService
    — a read-only scan wrapper with no create_draft_raw. The command therefore
    raised AttributeError on every real run while passing every --dry-run test,
    because dry-run never touches the client.
    """

    def test_gmail_service_lacks_create_draft_raw(self):
        """Pin the reason the old wiring was wrong, so it cannot silently return."""
        from calendars.gmail_service import GmailService

        self.assertFalse(
            hasattr(GmailService, "create_draft_raw"),
            "If GmailService gains create_draft_raw, revisit run_outlook_ics_draft",
        )

    def test_non_dry_run_without_client_fails_loudly(self):
        """dry_run=False with no client raises rather than silently doing nothing.

        This is the other half of the wiring bug: if the client fails to build,
        the run must stop, not produce a success envelope having created no draft.
        """
        request = IcsDraftRequest(
            config_path="plan.yaml",
            recipient="a@b.com",
            subject="S",
            dry_run=False,
            gmail_client=None,
        )
        proc = IcsDraftProcessor()
        with patch.object(proc, "_load_events", return_value=[{"subject": "X", "start": "2026-05-01T09:00:00", "end": "2026-05-01T10:00:00"}]):
            with self.assertRaises(ValueError) as ctx:
                proc._process_safe(request)
        self.assertIn("gmail_client is required", str(ctx.exception))

    def test_non_dry_run_builds_a_draft_capable_client(self):
        """The client handed to the processor must expose create_draft_raw."""
        import argparse

        from calendars.outlook import commands

        captured = {}

        def _capture(request, _proc, _prod):
            captured["client"] = request.gmail_client
            return 0

        args = argparse.Namespace(
            config="plan.yaml", recipient="a@b.com", subject="S",
            dry_run=False, profile=None, credentials=None, token=None, cache=None,
        )
        fake_client = MagicMock()
        with patch("mail.gmail_api.GmailClient", return_value=fake_client), \
                patch("core.auth.resolve_gmail_credentials", return_value=("c.json", "t.json")), \
                patch.object(commands, "run_pipeline", side_effect=_capture):
            rc = commands.run_outlook_ics_draft(args)

        self.assertEqual(rc, 0)
        self.assertIs(captured["client"], fake_client)
        fake_client.authenticate.assert_called_once()

    def test_dry_run_builds_no_client_at_all(self):
        """--dry-run must not construct or authenticate any Gmail client."""
        import argparse

        from calendars.outlook import commands

        captured = {}

        def _capture(request, _proc, _prod):
            captured["client"] = request.gmail_client
            return 0

        args = argparse.Namespace(
            config="plan.yaml", recipient="a@b.com", subject="S",
            dry_run=True, profile=None, credentials=None, token=None, cache=None,
        )
        with patch("mail.gmail_api.GmailClient") as client_cls, \
                patch.object(commands, "run_pipeline", side_effect=_capture):
            commands.run_outlook_ics_draft(args)

        self.assertIsNone(captured["client"])
        client_cls.assert_not_called()


class TestCLIIcsDraftCommand(unittest.TestCase):
    """`outlook ics-draft` is reachable through the real parser with correct dests."""

    def test_ics_draft_command_registered(self):
        from calendars.cli.main import app

        parser = app.build_parser()
        args = parser.parse_args(
            ["outlook", "ics-draft", "--config", "plan.yaml", "--recipient", "a@b.com"]
        )
        self.assertEqual(args.config, "plan.yaml")
        self.assertEqual(args.recipient, "a@b.com")
        self.assertEqual(args.subject, "Calendar Plan")
        self.assertFalse(args.dry_run)

    def test_ics_draft_requires_config_and_recipient(self):
        """Both --config and --recipient are required; omitting them exits non-zero."""
        from calendars.cli.main import app

        parser = app.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["outlook", "ics-draft"])


if __name__ == "__main__":
    unittest.main()
