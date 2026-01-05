"""Fake Outlook client and calendar service for testing.

Provides configurable fake clients for Outlook API and calendar operations
without requiring network access or credentials.
"""
# ruff: noqa: ARG002
# Unused parameters are intentional - these fakes must match the real interface signatures.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.outlook.models import EventCreationParams, RecurringEventCreationParams


@dataclass
class FakeOutlookClient:
    """Configurable fake Outlook client for testing.

    Example usage:
        client = FakeOutlookClient(
            events=[{"subject": "Meeting", "start": {...}, "end": {...}}],
            calendars=[{"id": "cal1", "name": "Work"}],
        )
    """

    events: List[Dict] = field(default_factory=list)
    calendars: List[Dict] = field(default_factory=list)
    rules: List[Dict] = field(default_factory=list)
    categories: List[Dict] = field(default_factory=list)

    # Track mutations
    created_events: List[Dict] = field(default_factory=list)
    deleted_event_ids: List[str] = field(default_factory=list)
    updated_events: List[Dict] = field(default_factory=list)

    def authenticate(self) -> None:
        """No-op for fake client - authentication not needed in tests."""

    def list_calendars(self) -> List[Dict]:
        return list(self.calendars)

    def get_calendar_by_name(self, name: str) -> Optional[Dict]:
        for cal in self.calendars:
            if cal.get("name") == name:
                return cal
        return None

    def list_events_in_range(
        self, calendar_id: Optional[str] = None, start: Optional[str] = None,
        end: Optional[str] = None, **kwargs
    ) -> List[Dict]:
        return list(self.events)

    def create_event(self, calendar_id: str, event: Dict) -> Dict:
        event_copy = dict(event)
        event_copy["id"] = f"EVT_{len(self.created_events)}"
        self.created_events.append(event_copy)
        return event_copy

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self.deleted_event_ids.append(event_id)

    def update_event(self, calendar_id: str, event_id: str, updates: Dict) -> Dict:
        self.updated_events.append({"id": event_id, **updates})
        return {"id": event_id, **updates}

    def list_rules(self) -> List[Dict]:
        return list(self.rules)

    def list_categories(self) -> List[Dict]:
        return list(self.categories)


def make_outlook_client(
    events: Optional[List[Dict]] = None,
    calendars: Optional[List[Dict]] = None,
) -> FakeOutlookClient:
    """Factory for creating a pre-configured FakeOutlookClient."""
    return FakeOutlookClient(
        events=events or [],
        calendars=calendars or [{"id": "default", "name": "Calendar"}],
    )


@dataclass
class FakeCalendarService:
    """Configurable fake calendar service for CLI testing.

    Consolidates the FakeService pattern used across calendar CLI tests.

    Example usage:
        svc = FakeCalendarService(events=[...])
        svc.list_calendar_view(ListCalendarViewRequest(calendar_id="cal-1", start_iso="...", end_iso="..."))
    """

    events: List[Dict] = field(default_factory=list)
    deleted_ids: List[str] = field(default_factory=list)
    updated_reminders: List[tuple] = field(default_factory=list)
    created_events: List[tuple] = field(default_factory=list)
    updated_locations: List[tuple] = field(default_factory=list)
    calendar_id: str = "cal-1"

    def get_calendar_id_by_name(self, name: str) -> Optional[str]:
        return self.calendar_id if name else None

    def find_calendar_id(self, name: str) -> Optional[str]:
        return self.get_calendar_id_by_name(name)

    def list_calendar_view(
        self, *, calendar_id: str, start_iso: str, end_iso: str,
        select: str = "", top: int = 200
    ) -> List[Dict]:
        return list(self.events)

    def delete_event_by_id(self, event_id: str) -> bool:
        self.deleted_ids.append(event_id)
        return True

    def list_events_in_range(
        self, *, start_iso: str, end_iso: str, calendar_id: Optional[str] = None,
        **kwargs
    ) -> List[Dict]:
        return list(self.events)

    def update_event_reminder(
        self, *, event_id: str, calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None, is_on: bool,
        minutes_before_start: Optional[int] = None
    ) -> None:
        self.updated_reminders.append((event_id, is_on, minutes_before_start))

    def create_event(self, params: EventCreationParams) -> Dict[str, Any]:
        evt: Dict[str, Any] = {"id": f"evt_{len(self.created_events)}", "subject": params.subject}
        self.created_events.append(("single", params))
        return evt

    def create_recurring_event(self, params: RecurringEventCreationParams) -> Dict[str, Any]:
        evt: Dict[str, Any] = {"id": f"evt_rec_{len(self.created_events)}", "subject": params.subject}
        self.created_events.append(("recurring", params))
        return evt

    def update_event_location(
        self, *, event_id: str, calendar_name: Optional[str] = None,
        calendar_id: Optional[str] = None, location_str: str
    ) -> None:
        self.updated_locations.append((event_id, location_str))
