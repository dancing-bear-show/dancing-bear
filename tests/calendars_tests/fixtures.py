"""Calendar-specific test fixtures.

Outlook client fakes, calendar service fakes, and event helpers.
"""

from __future__ import annotations

from typing import Any, Dict

# Re-export fakes from centralized fakes module
from tests.fakes.outlook import (
    FakeOutlookClient,
    FakeCalendarService,
    make_outlook_client,
)

__all__ = [
    "make_outlook_event",
    "FakeOutlookClient",
    "make_outlook_client",
    "FakeCalendarService",
    "FakeGoogleCalendarService",
    "NoOpProducer",
    "make_mock_processor",
]


# -----------------------------------------------------------------------------
# Calendar event helpers
# -----------------------------------------------------------------------------


def make_outlook_event(
    subject: str = "Test Event",
    start_iso: str = "2025-01-01T10:00:00",
    end_iso: str = "2025-01-01T11:00:00",
    **kwargs,
) -> Dict:
    """Create a fake Outlook event dict for testing.

    Optional kwargs: series_id, location, created, event_type.
    """
    event: Dict = {
        "subject": subject,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if kwargs.get("series_id"):
        event["seriesMasterId"] = kwargs["series_id"]
    if kwargs.get("location"):
        event["location"] = {"displayName": kwargs["location"]}
    if kwargs.get("created"):
        event["createdDateTime"] = kwargs["created"]
    if kwargs.get("event_type"):
        event["type"] = kwargs["event_type"]
    return event


# -----------------------------------------------------------------------------
# Pipeline testing helpers
# -----------------------------------------------------------------------------


class NoOpProducer:
    """A producer that does nothing - for testing pipelines."""

    def produce(self, env):
        pass  # intentionally empty stub - no-op for pipeline testing


def make_mock_processor(envelope):
    """Create a mock processor that returns the given envelope.

    Args:
        envelope: The ResultEnvelope to return from process()

    Returns:
        A class (not instance) that can be passed to run_pipeline
    """
    class MockProcessor:
        def process(self, _req):  # NOSONAR - fake interface must match real signature
            return envelope
    return MockProcessor


# -----------------------------------------------------------------------------
# Google Calendar Service fake
# -----------------------------------------------------------------------------


class FakeGoogleCalendarService:
    """Fail-fast fake for GoogleCalendarService.

    Pass ``events`` as a list of dicts to return from ``list_events``.
    Pass ``tz`` to control ``get_calendar_timezone``; None simulates lookup failure.
    Pass ``insert_result`` to control what ``insert_event`` returns.

    The fake raises ``KeyError`` for any calendar_id not explicitly registered,
    so a test passing the wrong id fails instead of silently returning placeholder
    data (see fake-silent-miss concern in concerns/tests.md).
    """

    def __init__(
        self,
        events: list[dict[str, Any]] | None = None,
        tz: str | None = "America/Toronto",
        insert_result: dict[str, Any] | None = None,
        registered_calendar_ids: set[str] | None = None,
    ) -> None:
        self._events: list[dict[str, Any]] = events or []
        self._tz = tz
        self._insert_result = insert_result or {"id": "fake-ev-id", "summary": "Inserted"}
        self.inserted: list[tuple[str, dict[str, Any]]] = []
        self._registered_ids = registered_calendar_ids or {"primary"}

    def list_events(
        self, calendar_id: str, time_min: str, time_max: str
    ) -> list[dict[str, Any]]:
        if calendar_id not in self._registered_ids:
            raise KeyError(f"FakeGoogleCalendarService: unregistered calendar_id {calendar_id!r}")
        return list(self._events)

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if calendar_id not in self._registered_ids:
            raise KeyError(f"FakeGoogleCalendarService: unregistered calendar_id {calendar_id!r}")
        self.inserted.append((calendar_id, body))
        result = dict(self._insert_result)
        result.setdefault("summary", body.get("summary", ""))
        return result

    def get_calendar_timezone(self, calendar_id: str) -> str | None:
        if calendar_id not in self._registered_ids:
            raise KeyError(f"FakeGoogleCalendarService: unregistered calendar_id {calendar_id!r}")
        return self._tz


def make_occurrence(subject, series_id, start_iso, end_iso, created, location=None):
    """Build a Graph calendar-event dict shaped for pipeline tests."""
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
