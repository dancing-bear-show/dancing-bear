"""Calendar-specific test fixtures.

Outlook client fakes, calendar service fakes, and event helpers.
"""

from __future__ import annotations

from typing import Dict, Optional

# Re-export shared fixtures for backwards compatibility
from tests.fixtures import temp_csv, write_csv, write_csv_content

# Re-export fakes from centralized fakes module
from tests.fakes.outlook import (
    FakeOutlookClient,
    FakeCalendarService,
    make_outlook_client,
)

__all__ = [
    "temp_csv",
    "write_csv",
    "write_csv_content",
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
    subject: str,
    start_iso: str,
    end_iso: str,
    series_id: Optional[str] = None,
    location: Optional[str] = None,
    created: Optional[str] = None,
    event_type: Optional[str] = None,
) -> Dict:
    """Create a fake Outlook event dict for testing."""
    event = {
        "subject": subject,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if series_id:
        event["seriesMasterId"] = series_id
    if location:
        event["location"] = {"displayName": location}
    if created:
        event["createdDateTime"] = created
    if event_type:
        event["type"] = event_type
    return event


# -----------------------------------------------------------------------------
# Pipeline testing helpers
# -----------------------------------------------------------------------------


class NoOpProducer:
    """A producer that does nothing - for testing pipelines."""

    def produce(self, env):
        pass


def make_mock_processor(envelope):
    """Create a mock processor that returns the given envelope.

    Args:
        envelope: The ResultEnvelope to return from process()

    Returns:
        A class (not instance) that can be passed to run_pipeline
    """
    class MockProcessor:
        def process(self, req):
            return envelope
    return MockProcessor
