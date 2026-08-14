"""Calendar and event operations for Outlook via Microsoft Graph."""

from __future__ import annotations

from typing import Any, Protocol

from .client import _requests
from .models import (
    EventCreationParams,
    EventSettingsPatch,
    ListCalendarViewRequest,
    ListEventsRequest,
    RecurringEventCreationParams,
    UpdateEventLocationRequest,
    UpdateEventReminderRequest,
    UpdateEventSubjectRequest,
)
from core.constants import DAY_START_TIME, DAY_END_TIME, GRAPH_API_URL
from core.outlook._location import _parse_location
from core.outlook._recurrence import (
    _apply_reminder,
    _build_recurrence_pattern,
    _build_recurrence_range,
)


class _OutlookCalendarHost(Protocol):
    """Structural contract the host class must satisfy for OutlookCalendarMixin.

    Only members the mixin does *not* define itself belong here: everything else
    (_resolve_calendar_id, _paginated_get, _event_endpoint, _patch_event,
    list_calendars, get_calendar_id_by_name, ...) is provided by the mixin.
    """

    def _headers(self) -> dict[str, str]:
        """Return Graph API auth headers."""
        ...

    def get_mailbox_timezone(self) -> str | None:
        """Return the mailbox's default IANA timezone, if known."""
        ...


class OutlookCalendarMixin:
    """Mixin providing calendar and event operations.

    Host class must satisfy _OutlookCalendarHost.
    """

    # -------------------- Internal helpers --------------------
    def _resolve_calendar_id(
        self: _OutlookCalendarHost,
        calendar_id: str | None,
        calendar_name: str | None,
    ) -> str | None:
        """Resolve calendar_id from either explicit ID or name lookup."""
        if calendar_id:
            return calendar_id
        if calendar_name:
            return self.get_calendar_id_by_name(calendar_name)
        return None

    def _paginated_get(self: _OutlookCalendarHost, url: str) -> list[dict[str, Any]]:
        """Fetch all pages from a paginated Graph API endpoint."""
        out: list[dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value", []) or [])
            url = data.get("@odata.nextLink")
        return out

    @staticmethod
    def _event_endpoint(calendar_id: str | None, event_id: str | None = None) -> str:
        """Build Graph API endpoint for events."""
        if calendar_id:
            base = f"{GRAPH_API_URL}/me/calendars/{calendar_id}/events"
        else:
            base = f"{GRAPH_API_URL}/me/events"
        return f"{base}/{event_id}" if event_id else base

    @staticmethod
    def _apply_reminder(payload: dict[str, Any], no_reminder: bool, reminder_minutes: int | None) -> None:
        """Apply reminder settings to an event payload."""
        _apply_reminder(payload, no_reminder, reminder_minutes)

    # -------------------- Calendars --------------------
    def list_calendars(self: _OutlookCalendarHost) -> list[dict[str, Any]]:
        return self._paginated_get(f"{GRAPH_API_URL}/me/calendars")

    def create_calendar(self: _OutlookCalendarHost, name: str) -> dict[str, Any]:
        body = {"name": name}
        r = _requests().post(f"{GRAPH_API_URL}/me/calendars", headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _calendar_name_matches(cal: dict[str, Any], target: str) -> bool:
        """Return True if cal's name/displayName case-insensitively equals target."""
        n = (cal.get("name") or cal.get("displayName") or "").strip().lower()
        return n == target

    def _find_calendar_by_name(self: _OutlookCalendarHost, target: str) -> dict[str, Any] | None:
        """Return the first calendar whose name matches target (already normalized)."""
        for cal in self.list_calendars():
            if self._calendar_name_matches(cal, target):
                return cal
        return None

    def ensure_calendar(self: _OutlookCalendarHost, name: str) -> str:
        target = (name or "").strip().lower()
        if not target:
            raise ValueError("Calendar name is empty")
        found = self._find_calendar_by_name(target)
        if found is not None:
            return found.get("id", "")
        created = self.create_calendar(name)
        return created.get("id", "")

    # Alias for backwards compatibility
    def ensure_calendar_exists(self: _OutlookCalendarHost, name: str) -> str:
        return self.ensure_calendar(name)

    def find_calendar_id(self: _OutlookCalendarHost, name: str) -> str | None:
        return self.get_calendar_id_by_name(name)

    def get_calendar_id_by_name(self: _OutlookCalendarHost, name: str) -> str | None:
        target = (name or "").strip().lower()
        if not target:
            return None
        found = self._find_calendar_by_name(target)
        cid = found.get("id") if found else None
        return str(cid) if cid else None

    # -------------------- Calendar Sharing --------------------
    def list_calendar_permissions(self: _OutlookCalendarHost, calendar_id: str) -> list[dict[str, Any]]:
        url = f"{GRAPH_API_URL}/me/calendars/{calendar_id}/calendarPermissions"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("value", [])

    def _update_calendar_permission(
        self: _OutlookCalendarHost, calendar_id: str, perm_id: str, role: str
    ) -> dict[str, Any]:
        """Patch an existing calendar permission to a new role."""
        rr = _requests().patch(
            f"{GRAPH_API_URL}/me/calendars/{calendar_id}/calendarPermissions/{perm_id}",
            headers=self._headers(),
            json={"role": role},
        )
        rr.raise_for_status()
        return rr.json() if rr.text else {}

    @staticmethod
    def _permission_email_matches(perm: dict[str, Any], email: str) -> bool:
        """Return True if perm's emailAddress case-insensitively equals email."""
        em = ((perm.get("emailAddress") or {}).get("address") or "").strip().lower()
        return em == (email or "").strip().lower()

    def _reconcile_permission_role(
        self: _OutlookCalendarHost, calendar_id: str, perm: dict[str, Any], role: str
    ) -> dict[str, Any]:
        """Update perm's role if it differs from the target role; else return it unchanged."""
        cur = (perm.get("role") or "").strip()
        if cur.lower() == role.strip().lower():
            return perm
        pid = perm.get("id")
        if not pid:
            return perm
        return self._update_calendar_permission(calendar_id, pid, role)

    def ensure_calendar_permission(
        self: _OutlookCalendarHost,
        calendar_id: str,
        email: str,
        role: str = "write"
    ) -> dict[str, Any]:
        """Ensure a calendar permission exists for an external email with the given role.

        role: one of read | write | limitedRead | freeBusyRead | delegateWithoutPrivateEventAccess | delegateWithPrivateEventAccess
        """
        for p in self.list_calendar_permissions(calendar_id):
            if self._permission_email_matches(p, email):
                return self._reconcile_permission_role(calendar_id, p, role)
        r = _requests().post(
            f"{GRAPH_API_URL}/me/calendars/{calendar_id}/calendarPermissions",
            headers=self._headers(),
            json={"emailAddress": {"address": email}, "role": role},
        )
        r.raise_for_status()
        return r.json()

    # -------------------- Events --------------------
    def list_events_in_range(
        self: _OutlookCalendarHost,
        params: ListEventsRequest,
    ) -> list[dict[str, Any]]:
        """List events for a calendar within [start_iso, end_iso].

        Uses calendarView which expands recurring series. Optional subject_filter
        performs a client-side case-insensitive match.
        """
        cal_id = self._resolve_calendar_id(params.calendar_id, params.calendar_name)
        base = f"{GRAPH_API_URL}/me/calendars/{cal_id}/calendarView" if cal_id else f"{GRAPH_API_URL}/me/calendarView"
        events = self._paginated_get(f"{base}?startDateTime={params.start_iso}&endDateTime={params.end_iso}&$top={int(params.top)}")
        if not params.subject_filter:
            return events
        needle = params.subject_filter.lower()
        return [ev for ev in events if needle in (ev.get("subject") or "").lower()]

    def list_calendar_view(
        self: _OutlookCalendarHost,
        params: ListCalendarViewRequest,
    ) -> list[dict[str, Any]]:
        """List calendar view (expanded occurrences) for a date range."""
        base = f"{GRAPH_API_URL}/me/calendars/{params.calendar_id}/calendarView" if params.calendar_id else f"{GRAPH_API_URL}/me/calendarView"
        return self._paginated_get(f"{base}?startDateTime={params.start_iso}&endDateTime={params.end_iso}&$top={int(params.top)}")

    def _resolve_tz(self: _OutlookCalendarHost, tz: str | None) -> str:
        if tz and tz.strip():
            return tz.strip()
        mbx = self.get_mailbox_timezone()
        if mbx:
            return mbx
        return "America/Toronto"

    @staticmethod
    def _apply_body_and_location(
        payload: dict[str, Any], body_html: str | None, location: str | None
    ) -> None:
        """Add optional body/location fields to an event payload, in place."""
        if body_html:
            payload["body"] = {"contentType": "HTML", "content": body_html}
        if location:
            payload["location"] = _parse_location(location)

    def create_event(self: _OutlookCalendarHost, params: EventCreationParams) -> dict[str, Any]:
        """Create a one-time event."""
        tz_final = self._resolve_tz(params.tz)
        cal_id = self._resolve_calendar_id(params.calendar_id, params.calendar_name)
        payload: dict[str, Any] = {
            "subject": params.subject,
            "start": {"dateTime": params.start_iso, "timeZone": tz_final},
            "end": {"dateTime": params.end_iso, "timeZone": tz_final},
        }
        self._apply_body_and_location(payload, params.body_html, params.location)
        if params.all_day:
            payload["isAllDay"] = True
        _apply_reminder(payload, params.no_reminder, params.reminder_minutes)
        r = _requests().post(self._event_endpoint(cal_id), headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def create_recurring_event(
        self: _OutlookCalendarHost, params: RecurringEventCreationParams
    ) -> dict[str, Any]:
        """Create a recurring event series."""
        tz_final = self._resolve_tz(params.tz)
        cal_id = self._resolve_calendar_id(params.calendar_id, params.calendar_name)

        pattern = _build_recurrence_pattern(params.repeat, params.interval, params.byday)
        rng = _build_recurrence_range(params.range_start_date, params.range_until, params.count)

        start_iso = f"{params.range_start_date}T{params.start_time}"
        end_iso = f"{params.range_start_date}T{params.end_time}"

        payload: dict[str, Any] = {
            "subject": params.subject,
            "start": {"dateTime": start_iso, "timeZone": tz_final},
            "end": {"dateTime": end_iso, "timeZone": tz_final},
            "recurrence": {"pattern": pattern, "range": rng},
        }
        self._apply_body_and_location(payload, params.body_html, params.location)
        _apply_reminder(payload, params.no_reminder, params.reminder_minutes)

        r = _requests().post(self._event_endpoint(cal_id), headers=self._headers(), json=payload)
        r.raise_for_status()
        series = r.json()

        if params.exdates:
            self._apply_exdate_deletions_best_effort(cal_id, series.get("id"), params.exdates, rng)
        return series

    def _apply_exdate_deletions_best_effort(
        self: _OutlookCalendarHost,
        calendar_id: str | None,
        series_id: str | None,
        exdates: list[str],
        rng: dict[str, Any],
    ) -> None:
        """Apply exdate deletions, swallowing failures — non-fatal to series creation."""
        if not series_id:
            return
        try:
            self._apply_exdate_deletions(calendar_id, series_id, exdates, rng)
        except Exception:  # nosec B110 - non-fatal exdate deletion
            pass

    @staticmethod
    def _build_recurrence_pattern(repeat: str, interval: int, byday: list[str] | None) -> dict[str, Any]:
        """Build recurrence pattern for Graph API."""
        return _build_recurrence_pattern(repeat, interval, byday)

    @staticmethod
    def _build_recurrence_range(start_date: str, until: str | None, count: int | None) -> dict[str, Any]:
        """Build recurrence range for Graph API."""
        return _build_recurrence_range(start_date, until, count)

    def _apply_exdate_deletions(
        self: _OutlookCalendarHost,
        calendar_id: str | None,
        series_id: str,
        exdates: list[str],
        rng: dict[str, Any],
    ) -> None:
        start_date = rng.get("startDate")
        end_date = rng.get("endDate") or start_date
        url = f"{self._event_endpoint(calendar_id, series_id)}/instances?startDateTime={start_date}{DAY_START_TIME}&endDateTime={end_date}{DAY_END_TIME}"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        ex_set = {d.strip() for d in exdates if d and d.strip()}
        for inst in r.json().get("value", []):
            iid = inst.get("id")
            st = (inst.get("start") or {}).get("dateTime") or ""
            date_only = st.split("T", 1)[0] if "T" in st else st
            if iid and date_only in ex_set:
                _requests().delete(self._event_endpoint(calendar_id, iid), headers=self._headers())

    # -------------------- Event Updates --------------------
    def _patch_event(
        self: _OutlookCalendarHost,
        event_id: str,
        calendar_id: str | None,
        calendar_name: str | None,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Patch an event and return the result."""
        cal_id = self._resolve_calendar_id(calendar_id, calendar_name)
        r = _requests().patch(self._event_endpoint(cal_id, event_id), headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def update_event_location(
        self: _OutlookCalendarHost,
        params: UpdateEventLocationRequest,
    ) -> dict[str, Any]:
        """Patch the location of an event or series master."""
        if not (params.location_str and params.location_str.strip()):
            raise ValueError("Must provide location_str")
        loc = _parse_location(params.location_str)
        return self._patch_event(params.event_id, params.calendar_id, params.calendar_name, {"location": loc})

    def update_event_reminder(
        self: _OutlookCalendarHost,
        params: UpdateEventReminderRequest,
    ) -> dict[str, Any]:
        """Patch event reminder fields."""
        body: dict[str, Any] = {"isReminderOn": bool(params.is_on)}
        if params.minutes_before_start is not None:
            body["reminderMinutesBeforeStart"] = int(params.minutes_before_start)
        return self._patch_event(params.event_id, params.calendar_id, params.calendar_name, body)

    def update_event_settings(
        self: _OutlookCalendarHost,
        params: EventSettingsPatch,
    ) -> dict[str, Any]:
        """Patch selected event fields in one request."""
        body: dict[str, Any] = {}
        if params.categories is not None:
            body["categories"] = list(params.categories)
        if params.show_as:
            body["showAs"] = str(params.show_as)
        if params.sensitivity:
            body["sensitivity"] = str(params.sensitivity)
        if params.is_reminder_on is not None:
            body["isReminderOn"] = bool(params.is_reminder_on)
        if params.reminder_minutes is not None:
            body["reminderMinutesBeforeStart"] = int(params.reminder_minutes)
        if not body:
            return {}
        return self._patch_event(params.event_id, params.calendar_id, params.calendar_name, body)

    def update_event_subject(
        self: _OutlookCalendarHost,
        params: UpdateEventSubjectRequest,
    ) -> dict[str, Any]:
        """Patch the subject/title of an event or series master."""
        return self._patch_event(
            params.event_id, params.calendar_id, params.calendar_name, {"subject": params.subject}
        )

    def delete_event(
        self: _OutlookCalendarHost,
        event_id: str,
        calendar_id: str | None = None
    ) -> None:
        r = _requests().delete(self._event_endpoint(calendar_id, event_id), headers=self._headers())
        if r.status_code not in (200, 202, 204):
            r.raise_for_status()

    def delete_event_by_id(
        self: _OutlookCalendarHost,
        event_id: str,
        calendar_id: str | None = None
    ) -> bool:
        """Delete an event by ID, return True if successful."""
        try:
            self.delete_event(event_id, calendar_id)
            return True
        except Exception:
            return False
