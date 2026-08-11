"""Schedule test fixtures and fakes.

Provides shared fake/stub classes used across schedule_tests/.
Consolidates the FakeOutlook inline definitions from test_schedule_verify_sync.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class FakeOutlook:
    """Configurable fake Outlook calendar service for schedule pipeline tests.

    Matches the interface expected by VerifyProcessor, SyncProcessor, and
    ExportScheduleProcessor: authenticate(), ensure_calendar(), and
    list_events_in_range().

    Example usage:
        svc = FakeOutlook(events=[
            {"subject": "Swim", "start": {"dateTime": "2025-10-05T10:00:00"}, ...}
        ])
        # Pass via patch("mail.outlook_api.OutlookClient", new=type(svc))
    """

    events: List[Dict[str, Any]] = field(default_factory=list)
    calendar_id: str = "CAL_FAKE"

    # Track mutations for assertions
    ensure_calendar_calls: List[str] = field(default_factory=list)

    def authenticate(self) -> None:
        """No-op – authentication not needed in tests."""

    def ensure_calendar(self, name: str) -> str:
        self.ensure_calendar_calls.append(name)
        return self.calendar_id

    def list_events_in_range(self, _params: Any) -> List[Dict[str, Any]]:
        return list(self.events)
