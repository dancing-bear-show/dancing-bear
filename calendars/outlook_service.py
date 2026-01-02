"""Thin Outlook service wrapper.

Encapsulates an authenticated Outlook client and exposes a stable set of
helpers used by CLI handlers. This keeps __main__ smaller and centralizes
Graph interactions while preserving existing behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import requests

from .context import OutlookContext
from core.constants import DEFAULT_REQUEST_TIMEOUT, GRAPH_API_URL
from core.outlook.models import (
    EventCreationParams,
    EventSettingsPatch,
    ListCalendarViewRequest,
    ListEventsRequest,
    RecurringEventCreationParams,
    UpdateEventReminderRequest,
)

__all__ = [
    "EventCreationParams",
    "EventSettingsPatch",
    "ListCalendarViewRequest",
    "ListEventsRequest",
    "RecurringEventCreationParams",
    "UpdateEventReminderRequest",
    "OutlookService",
]


@dataclass
class OutlookService:
    ctx: OutlookContext

    def __post_init__(self) -> None:
        self.client = self.ctx.ensure_client()

    # Creation helpers
    def create_event(self, params: EventCreationParams) -> Dict[str, Any]:
        """Create a one-time event using parameter object."""
        return self.client.create_event(
            calendar_id=params.calendar_id,
            calendar_name=params.calendar_name,
            subject=params.subject,
            start_iso=params.start_iso,
            end_iso=params.end_iso,
            tz=params.tz,
            body_html=params.body_html,
            all_day=params.all_day,
            location=params.location,
            no_reminder=params.no_reminder,
            reminder_minutes=params.reminder_minutes,
        )

    def create_recurring_event(self, params: RecurringEventCreationParams) -> Dict[str, Any]:
        """Create a recurring event using parameter object."""
        return self.client.create_recurring_event(
            calendar_id=params.calendar_id,
            calendar_name=params.calendar_name,
            subject=params.subject,
            start_time=params.start_time,
            end_time=params.end_time,
            tz=params.tz,
            repeat=params.repeat,
            interval=params.interval,
            byday=params.byday,
            range_start_date=params.range_start_date,
            range_until=params.range_until,
            count=params.count,
            body_html=params.body_html,
            location=params.location,
            exdates=params.exdates,
            no_reminder=params.no_reminder,
            reminder_minutes=params.reminder_minutes,
        )

    # Query helpers
    def list_events_in_range(self, params: ListEventsRequest) -> List[Dict[str, Any]]:
        """List events in a date range using parameter object."""
        return self.client.list_events_in_range(params)

    # Mail/message helpers (inbox search)
    def search_inbox_messages(self, query: str, *, days: int = 60, top: int = 25, pages: int = 2) -> List[str]:
        return self.client.search_inbox_messages(query, days=days, top=top, pages=pages)

    def get_message(self, message_id: str, *, select_body: bool = True) -> Dict[str, Any]:
        return self.client.get_message(message_id, select_body=select_body)

    def get_calendar_id_by_name(self, name: Optional[str]) -> Optional[str]:
        return self.client.get_calendar_id_by_name(name) if name else None

    def ensure_calendar(self, name: str) -> str:
        return self.client.ensure_calendar(name)

    # Aliases + listing helpers
    def find_calendar_id(self, name: Optional[str]) -> Optional[str]:
        return self.get_calendar_id_by_name(name)

    def list_calendars(self):  # type: ignore[no-untyped-def]
        try:
            return self.client.list_calendars()
        except Exception:
            # Underlying client may not support listing; return empty list
            return []

    def ensure_calendar_exists(self, name: str) -> str:
        return self.ensure_calendar(name)

    # Update helpers
    def update_event_location(
        self,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        location_str: str,
    ) -> None:
        return self.client.update_event_location(
            event_id=event_id,
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            location_str=location_str,
        )

    def update_event_reminder(self, params: UpdateEventReminderRequest) -> None:
        """Update event reminder using parameter object."""
        self.client.update_event_reminder(params)

    def update_event_settings(self, params: EventSettingsPatch) -> None:
        """Patch a subset of event settings using parameter object."""
        self.client.update_event_settings(params)

    def update_event_subject(
        self,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        subject: str,
    ) -> None:
        self.client.update_event_subject(
            event_id=event_id,
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            subject=subject,
        )

    def ensure_calendar_permission(self, calendar_id: str, recipient: str, role: str) -> Dict[str, Any]:
        return self.client.ensure_calendar_permission(calendar_id, recipient, role)

    # Low-level access
    def headers(self) -> Dict[str, str]:
        return self.client._headers()

    def graph_base(self) -> str:
        return getattr(self.client, "GRAPH", GRAPH_API_URL)

    # Calendar view pagination + deletion helpers
    def list_calendar_view(self, params: ListCalendarViewRequest) -> List[Dict[str, Any]]:
        """List calendar view with pagination using parameter object."""
        base = self.graph_base()
        endpoint = f"{base}/me/calendars/{params.calendar_id}/calendarView" if params.calendar_id else f"{base}/me/calendarView"
        url = f"{endpoint}?startDateTime={params.start_iso}&endDateTime={params.end_iso}&$top={int(params.top)}&$select={params.select}"
        hdrs = self.headers()
        out: List[Dict[str, Any]] = []
        nxt = url
        while nxt:
            r = requests.get(nxt, headers=hdrs, timeout=DEFAULT_REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value") or [])
            nxt = data.get("@odata.nextLink")
        return out

    def delete_event_by_id(self, event_id: str) -> bool:
        base = self.graph_base()
        hdrs = self.headers()
        url = f"{base}/me/events/{event_id}"
        r = requests.delete(url, headers=hdrs, timeout=DEFAULT_REQUEST_TIMEOUT)
        return r.status_code == 204 or 200 <= r.status_code < 300

    # Mail listing (read-only)
    def list_messages(
        self,
        *,
        folder: str = "inbox",
        top: int = 5,
        pages: int = 1,
        select: str = "id,subject,receivedDateTime,from",
    ) -> List[Dict[str, Any]]:
        base = self.graph_base()
        hdrs = self.headers()
        folder_path = f"/me/mailFolders/{folder}/messages" if folder else "/me/messages"
        url = f"{base}{folder_path}?$top={int(top)}&$select={select}"
        out: List[Dict[str, Any]] = []
        nxt = url
        remaining_pages = int(pages)
        while nxt and remaining_pages > 0:
            r = requests.get(nxt, headers=hdrs, timeout=DEFAULT_REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value") or [])
            nxt = data.get("@odata.nextLink")
            remaining_pages -= 1
        return out
