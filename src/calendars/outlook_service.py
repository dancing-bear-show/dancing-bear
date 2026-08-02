"""Thin Outlook service wrapper.

Encapsulates an authenticated Outlook client and exposes a stable set of
helpers used by CLI handlers. This keeps __main__ smaller and centralizes
Graph interactions while preserving existing behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .context import OutlookContext
from core.constants import DEFAULT_REQUEST_TIMEOUT, GRAPH_API_URL
from core.http import HttpClient
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
        self._http = HttpClient("", timeout=DEFAULT_REQUEST_TIMEOUT)

    # Creation helpers
    def create_event(self, params: EventCreationParams) -> dict[str, Any]:
        """Create a one-time event using parameter object."""
        return self.client.create_event(params)

    def create_recurring_event(self, params: RecurringEventCreationParams) -> dict[str, Any]:
        """Create a recurring event using parameter object."""
        return self.client.create_recurring_event(params)

    # Query helpers
    def list_events_in_range(self, params: ListEventsRequest) -> list[dict[str, Any]]:
        """List events in a date range using parameter object."""
        return self.client.list_events_in_range(params)

    # Mail/message helpers (inbox search)
    def search_inbox_messages(self, query: str, *, days: int = 60, top: int = 25, pages: int = 2) -> list[str]:
        from core.outlook.models import SearchParams
        return self.client.search_inbox_messages(
            SearchParams(search_query=query, days=days, top=top, pages=pages)
        )

    def get_message(self, message_id: str, *, select_body: bool = True) -> dict[str, Any]:
        return self.client.get_message(message_id, select_body=select_body)

    def get_calendar_id_by_name(self, name: str | None) -> str | None:
        return self.client.get_calendar_id_by_name(name) if name else None

    def ensure_calendar(self, name: str) -> str:
        return self.client.ensure_calendar(name)

    # Aliases + listing helpers
    def find_calendar_id(self, name: str | None) -> str | None:
        return self.get_calendar_id_by_name(name)

    def list_calendars(self) -> list[dict[str, Any]]:
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
        calendar_id: str | None = None,
        calendar_name: str | None = None,
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
        calendar_id: str | None = None,
        calendar_name: str | None = None,
        subject: str,
    ) -> None:
        self.client.update_event_subject(
            event_id=event_id,
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            subject=subject,
        )

    def ensure_calendar_permission(self, calendar_id: str, recipient: str, role: str) -> dict[str, Any]:
        return self.client.ensure_calendar_permission(calendar_id, recipient, role)

    # Low-level access
    def headers(self) -> dict[str, str]:
        return self.client._headers()

    def graph_base(self) -> str:
        return getattr(self.client, "GRAPH", GRAPH_API_URL)

    # Calendar view pagination + deletion helpers
    def list_calendar_view(self, params: ListCalendarViewRequest) -> list[dict[str, Any]]:
        """List calendar view with pagination using parameter object."""
        base = self.graph_base()
        endpoint = f"{base}/me/calendars/{params.calendar_id}/calendarView" if params.calendar_id else f"{base}/me/calendarView"
        url = f"{endpoint}?startDateTime={params.start_iso}&endDateTime={params.end_iso}&$top={int(params.top)}&$select={params.select}"
        hdrs = self.headers()
        out: list[dict[str, Any]] = []
        nxt = url
        while nxt:
            r = self._http.get(nxt, headers=hdrs)
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value") or [])
            nxt = data.get("@odata.nextLink")
        return out

    def delete_event_by_id(self, event_id: str) -> bool:
        base = self.graph_base()
        hdrs = self.headers()
        url = f"{base}/me/events/{event_id}"
        try:
            r = self._http.delete(url, headers=hdrs)
            return r.status_code == 204 or 200 <= r.status_code < 300
        except Exception:  # nosec B110 - HTTP errors return False
            return False

    # Mail listing (read-only)
    def list_messages(
        self,
        *,
        folder: str = "inbox",
        top: int = 5,
        pages: int = 1,
        select: str = "id,subject,receivedDateTime,from",
    ) -> list[dict[str, Any]]:
        base = self.graph_base()
        hdrs = self.headers()
        folder_path = f"/me/mailFolders/{folder}/messages" if folder else "/me/messages"
        url = f"{base}{folder_path}?$top={int(top)}&$select={select}"
        out: list[dict[str, Any]] = []
        nxt = url
        remaining_pages = int(pages)
        while nxt and remaining_pages > 0:
            r = self._http.get(nxt, headers=hdrs)
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value") or [])
            nxt = data.get("@odata.nextLink")
            remaining_pages -= 1
        return out
