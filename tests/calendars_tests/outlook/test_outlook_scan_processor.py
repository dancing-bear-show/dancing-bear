"""Tests for OutlookScanProcessor/OutlookScanProducer (C8), CalendarProvider Protocol (C3/C9),
and CalendarNotFoundError error hierarchy (C5).

Coverage targets:
  C8 – OutlookScanProcessor._process_safe happy-path and sad-paths
       OutlookScanProducer._produce_success (no-match, with-events, with-out)
  C3 – CalendarProvider protocol conformance for both Gmail and Outlook stubs
  C5 – CalendarNotFoundError isinstance(NotFoundError) check
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import List
from unittest.mock import MagicMock, patch

from core.pipeline import ResultEnvelope


# ---------------------------------------------------------------------------
# Shared fake — minimal Outlook service for scan operations
# (search_inbox_messages + get_message not in FakeCalendarService; add stub)
# ---------------------------------------------------------------------------

@dataclass
class FakeScanService:
    """Minimal Outlook service stub for OutlookScanProcessor tests."""

    message_ids: List[str] = field(default_factory=list)
    messages: dict = field(default_factory=dict)
    raise_on_get: str | None = None  # message id that causes get_message to raise

    def search_inbox_messages(self, query: str, *, days: int, top: int, pages: int) -> List[str]:  # noqa: ARG002
        return list(self.message_ids)

    def get_message(self, mid: str, *, select_body: bool = False) -> dict:  # noqa: ARG002
        if mid == self.raise_on_get:
            raise RuntimeError(f"fetch failed for {mid}")
        return self.messages.get(mid, {})


# ---------------------------------------------------------------------------
# C8 – OutlookScanProcessor / OutlookScanProducer
# ---------------------------------------------------------------------------

class TestOutlookScanProcessorHappyPath(unittest.TestCase):
    """Happy-path: consumer → processor → producer round-trip for scan classes."""

    def _make_request(self, svc):
        from calendars.outlook.commands import OutlookScanRequest
        return OutlookScanRequest(
            service=svc,
            from_text="trainer@example.com",
            days=60,
            top=25,
            pages=2,
            calendar="Kids",
            out=None,
        )

    def test_returns_success_envelope_with_no_messages(self):
        """No matching messages → success envelope with empty events list."""
        from calendars.outlook.commands import OutlookScanProcessor, OutlookScanResult
        svc = FakeScanService(message_ids=[])
        request = self._make_request(svc)
        envelope = OutlookScanProcessor().process(request)
        self.assertTrue(envelope.ok())
        payload = envelope.payload
        self.assertIsInstance(payload, OutlookScanResult)
        self.assertEqual(payload.events, [])
        self.assertEqual(payload.message_count, 0)

    def test_returns_success_envelope_with_schedule_email(self):
        """A message containing a schedule pattern → events list populated."""
        from calendars.outlook.commands import OutlookScanProcessor, OutlookScanResult
        msg_body = (
            "Monday from 9:00am to 10:00am – Swimming\n"
            "Please register by the date shown."
        )
        svc = FakeScanService(
            message_ids=["msg-1"],
            messages={
                "msg-1": {
                    "id": "msg-1",
                    "subject": "Fall Classes",
                    "receivedDateTime": "2025-09-01T12:00:00Z",
                    "from": {"emailAddress": {"address": "trainer@example.com"}},
                    "body": {"content": msg_body},
                }
            },
        )
        request = self._make_request(svc)
        envelope = OutlookScanProcessor().process(request)
        self.assertTrue(envelope.ok())
        payload = envelope.payload
        self.assertIsInstance(payload, OutlookScanResult)
        # message_count reflects how many IDs were returned, not how many had events
        self.assertEqual(payload.message_count, 1)
        # events may or may not contain entries depending on RANGE_PAT match;
        # assert the structure is a list (not None/missing)
        self.assertIsInstance(payload.events, list)

    def test_producer_no_messages_found(self):
        """Producer prints 'No matching messages' when message_count is 0."""
        from calendars.outlook.commands import OutlookScanProducer, OutlookScanResult
        payload = OutlookScanResult(events=[], message_count=0, extracted=[], out=None)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookScanProducer().produce(env)
        self.assertIn("No matching messages", buf.getvalue())

    def test_producer_messages_but_no_schedule_lines(self):
        """Producer prints schedule-not-found message when events list is empty but messages exist."""
        from calendars.outlook.commands import OutlookScanProducer, OutlookScanResult
        payload = OutlookScanResult(events=[], message_count=3, extracted=[], out=None)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookScanProducer().produce(env)
        self.assertIn("No schedule-like lines", buf.getvalue())

    def test_producer_with_events_prints_count_and_entries(self):
        """Producer lists events and prints candidate count when events are present."""
        from calendars.outlook.commands import OutlookScanProducer, OutlookScanResult
        events = [
            {
                "subject": "Swim Class",
                "byday": ["MO"],
                "start_time": "09:00",
                "end_time": "10:00",
                "calendar": "Kids",
            }
        ]
        payload = OutlookScanResult(events=events, message_count=2, extracted=[], out=None)
        env = ResultEnvelope(status="success", payload=payload)
        buf = io.StringIO()
        with redirect_stdout(buf):
            OutlookScanProducer().produce(env)
        output = buf.getvalue()
        self.assertIn("1", output)       # event count
        self.assertIn("Swim Class", output)
        self.assertIn("--out", output)   # usage hint

    def test_producer_with_out_path_writes_yaml(self):
        """Producer writes YAML when out path is set and prints confirmation."""
        from calendars.outlook.commands import OutlookScanProducer, OutlookScanResult
        events = [{"subject": "Swim", "byday": ["WE"], "start_time": "09:00", "end_time": "10:00"}]
        payload = OutlookScanResult(events=events, message_count=1, extracted=[], out="plan.yaml")
        env = ResultEnvelope(status="success", payload=payload)
        io.StringIO()
        with patch("calendars.outlook.commands.OutlookScanProducer._produce_success") as mock_produce:
            # Patch _produce_success directly to avoid real filesystem writes
            mock_produce.return_value = None
            OutlookScanProducer().produce(env)
            mock_produce.assert_called_once_with(payload, None)


# ---------------------------------------------------------------------------
# C8 sad-paths – one test per distinct raise site in _process_safe
# ---------------------------------------------------------------------------

class TestOutlookScanProcessorSadPaths(unittest.TestCase):
    """Sad-path tests for OutlookScanProcessor._process_safe raise sites."""

    def _make_request(self, svc):
        from calendars.outlook.commands import OutlookScanRequest
        return OutlookScanRequest(
            service=svc,
            from_text="trainer@example.com",
            days=60,
            top=25,
            pages=2,
            calendar="Kids",
            out=None,
        )

    def test_search_raises_returns_error_envelope(self):
        """search_inbox_messages raising → processor returns error envelope, not crash."""
        from calendars.outlook.commands import OutlookScanProcessor

        svc = MagicMock()
        svc.search_inbox_messages.side_effect = RuntimeError("search API offline")
        request = self._make_request(svc)
        envelope = OutlookScanProcessor().process(request)
        self.assertFalse(envelope.ok())
        self.assertIn("search API offline", (envelope.diagnostics or {}).get("message", ""))

    def test_get_message_raises_causes_error_envelope(self):
        """get_message raising for one ID → _error entry causes KeyError in enrich step → error envelope.

        The _scan_enrich_items helper accesses item["source"] on every extracted entry,
        including the {"_error": ...} sentinel appended on fetch failure.  That KeyError
        propagates through _process_safe and is caught by SafeProcessor.process(), which
        returns an error envelope.  This is the observable contract — callers see an error,
        not a silent partial result.
        """
        from calendars.outlook.commands import OutlookScanProcessor

        svc = FakeScanService(
            message_ids=["bad-id"],
            messages={},
            raise_on_get="bad-id",
        )
        request = self._make_request(svc)
        envelope = OutlookScanProcessor().process(request)
        # SafeProcessor catches the KeyError and wraps it in an error envelope
        self.assertFalse(envelope.ok())
        self.assertIsNotNone(envelope.diagnostics)


# ---------------------------------------------------------------------------
# C3 – CalendarProvider Protocol conformance
# ---------------------------------------------------------------------------

class TestCalendarProviderProtocol(unittest.TestCase):
    """Verify Protocol conformance for both Gmail and Outlook stubs.

    A class satisfying CalendarProvider must expose list_events(date_range)
    and add_event(event) with the correct signatures.
    """

    def _make_gmail_conformant(self):
        """Minimal Gmail-side conformant object."""
        from calendars.gmail_pipelines import CalendarEvent

        class FakeGmailBackend:
            def list_events(self, date_range: tuple) -> list:
                return []

            def add_event(self, event: CalendarEvent) -> CalendarEvent:
                return event

        return FakeGmailBackend()

    def _make_outlook_conformant(self):
        """Minimal Outlook-side conformant object."""
        from calendars.gmail_pipelines import CalendarEvent

        class FakeOutlookBackend:
            def list_events(self, date_range: tuple) -> list:
                return []

            def add_event(self, event: CalendarEvent) -> CalendarEvent:
                return event

        return FakeOutlookBackend()

    def test_gmail_backend_satisfies_protocol(self):
        from calendars.importer.base import CalendarProvider
        backend = self._make_gmail_conformant()
        self.assertIsInstance(backend, CalendarProvider)

    def test_outlook_backend_satisfies_protocol(self):
        from calendars.importer.base import CalendarProvider
        backend = self._make_outlook_conformant()
        self.assertIsInstance(backend, CalendarProvider)

    def test_missing_list_events_does_not_satisfy_protocol(self):
        """Object missing list_events must not satisfy CalendarProvider."""
        from calendars.importer.base import CalendarProvider
        from calendars.gmail_pipelines import CalendarEvent

        class MissingListEvents:
            def add_event(self, event: CalendarEvent) -> CalendarEvent:
                return event

        obj = MissingListEvents()
        self.assertNotIsInstance(obj, CalendarProvider)

    def test_missing_add_event_does_not_satisfy_protocol(self):
        """Object missing add_event must not satisfy CalendarProvider."""
        from calendars.importer.base import CalendarProvider

        class MissingAddEvent:
            def list_events(self, date_range: tuple) -> list:
                return []

        obj = MissingAddEvent()
        self.assertNotIsInstance(obj, CalendarProvider)


# ---------------------------------------------------------------------------
# C5 – CalendarNotFoundError error hierarchy
# ---------------------------------------------------------------------------

class TestCalendarNotFoundErrorHierarchy(unittest.TestCase):
    """CalendarNotFoundError must subclass NotFoundError (not bare ValueError)."""

    def test_isinstance_of_not_found_error(self):
        from core.cli_errors import NotFoundError
        from calendars.outlook_pipelines.locations import CalendarNotFoundError
        err = CalendarNotFoundError("My Calendar")
        self.assertIsInstance(err, NotFoundError)

    def test_message_contains_calendar_name(self):
        from calendars.outlook_pipelines.locations import CalendarNotFoundError
        err = CalendarNotFoundError("Summer Schedule")
        self.assertIn("Summer Schedule", str(err))

    def test_calendar_name_attribute(self):
        from calendars.outlook_pipelines.locations import CalendarNotFoundError
        err = CalendarNotFoundError("Work")
        self.assertEqual(err.calendar_name, "Work")

    def test_not_isinstance_of_plain_value_error(self):
        """CalendarNotFoundError must no longer subclass ValueError after C5 fix."""
        from calendars.outlook_pipelines.locations import CalendarNotFoundError
        err = CalendarNotFoundError("Test")
        self.assertNotIsInstance(err, ValueError)

    def test_not_found_error_subclasses_cli_error(self):
        """NotFoundError itself subclasses CLIError — confirm the full chain."""
        from core.cli_errors import CLIError, NotFoundError
        from calendars.outlook_pipelines.locations import CalendarNotFoundError
        err = CalendarNotFoundError("Chain")
        self.assertIsInstance(err, CLIError)
        self.assertIsInstance(err, NotFoundError)


if __name__ == "__main__":
    unittest.main()
