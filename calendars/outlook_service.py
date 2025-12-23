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


@dataclass
class OutlookService:
    ctx: OutlookContext

    def __post_init__(self) -> None:
        self.client = self.ctx.ensure_client()

    # Creation helpers
    def create_event(
        self,
        *,
        calendar_id: Optional[str],
        calendar_name: Optional[str],
        subject: str,
        start_iso: str,
        end_iso: str,
        tz: Optional[str] = None,
        body_html: Optional[str] = None,
        all_day: bool = False,
        location: Optional[str] = None,
        no_reminder: bool = False,
        reminder_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.client.create_event(
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            subject=subject,
            start_iso=start_iso,
            end_iso=end_iso,
            tz=tz,
            body_html=body_html,
            all_day=all_day,
            location=location,
            no_reminder=no_reminder,
            reminder_minutes=reminder_minutes,
        )

    def create_recurring_event(
        self,
        *,
        calendar_id: Optional[str],
        calendar_name: Optional[str],
        subject: str,
        start_time: str,
        end_time: str,
        tz: Optional[str],
        repeat: str,
        interval: int = 1,
        byday: Optional[List[str]] = None,
        range_start_date: Optional[str] = None,
        range_until: Optional[str] = None,
        count: Optional[int] = None,
        body_html: Optional[str] = None,
        location: Optional[str] = None,
        exdates: Optional[List[str]] = None,
        no_reminder: bool = False,
        reminder_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        return self.client.create_recurring_event(
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            subject=subject,
            start_time=start_time,
            end_time=end_time,
            tz=tz,
            repeat=repeat,
            interval=interval,
            byday=byday,
            range_start_date=range_start_date,
            range_until=range_until,
            count=count,
            body_html=body_html,
            location=location,
            exdates=exdates,
            no_reminder=no_reminder,
            reminder_minutes=reminder_minutes,
        )

    # Query helpers
    def list_events_in_range(
        self,
        *,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        start_iso: str,
        end_iso: str,
        subject_filter: Optional[str] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        return self.client.list_events_in_range(
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            start_iso=start_iso,
            end_iso=end_iso,
            subject_filter=subject_filter,
            **kwargs,
        )

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

    def update_event_reminder(
        self,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        is_on: bool,
        minutes_before_start: Optional[int] = None,
    ) -> None:
        return self.client.update_event_reminder(
            event_id=event_id,
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            is_on=is_on,
            minutes_before_start=minutes_before_start,
        )

    def update_event_settings(
        self,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        categories: Optional[list[str]] = None,
        show_as: Optional[str] = None,
        sensitivity: Optional[str] = None,
        is_reminder_on: Optional[bool] = None,
        reminder_minutes: Optional[int] = None,
    ) -> None:
        """Patch a subset of event settings (categories/showAs/sensitivity/reminder fields)."""
        self.client.update_event_fields(
            event_id=event_id,
            calendar_id=calendar_id,
            calendar_name=calendar_name,
            categories=categories,
            show_as=show_as,
            sensitivity=sensitivity,
            is_reminder_on=is_reminder_on,
            reminder_minutes=reminder_minutes,
        )

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
        return getattr(self.client, "GRAPH", "https://graph.microsoft.com/v1.0")

    # Calendar view pagination + deletion helpers
    def list_calendar_view(
        self,
        *,
        calendar_id: Optional[str],
        start_iso: str,
        end_iso: str,
        select: str = "subject,start,end,seriesMasterId,type,createdDateTime,location",
        top: int = 200,
    ) -> List[Dict[str, Any]]:
        base = self.graph_base()
        endpoint = f"{base}/me/calendars/{calendar_id}/calendarView" if calendar_id else f"{base}/me/calendarView"
        url = f"{endpoint}?startDateTime={start_iso}&endDateTime={end_iso}&$top={int(top)}&$select={select}"
        hdrs = self.headers()
        out: List[Dict[str, Any]] = []
        nxt = url
        while nxt:
            r = requests.get(nxt, headers=hdrs)
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value") or [])
            nxt = data.get("@odata.nextLink")
        return out

    def delete_event_by_id(self, event_id: str) -> bool:
        base = self.graph_base()
        hdrs = self.headers()
        url = f"{base}/me/events/{event_id}"
        r = requests.delete(url, headers=hdrs)
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
            r = requests.get(nxt, headers=hdrs)
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value") or [])
            nxt = data.get("@odata.nextLink")
            remaining_pages -= 1
        return out
