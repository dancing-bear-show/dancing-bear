"""Calendar-specific test fixtures.

Outlook client fakes, calendar service fakes, and event helpers.
"""

from __future__ import annotations

from typing import Dict

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
