"""Calendar and event operations for Outlook via Microsoft Graph."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple, Union

from .client import OutlookClientBase, _requests
from .models import (
    EventCreationParams,
    EventSettingsPatch,
    ListCalendarViewRequest,
    ListEventsRequest,
    RecurringEventCreationParams,
    UpdateEventReminderRequest,
)
from core.constants import DAY_START_TIME, DAY_END_TIME, GRAPH_API_URL


class OutlookCalendarMixin:
    """Mixin providing calendar and event operations.

    Requires OutlookClientBase methods: _headers, get_mailbox_timezone
    """

    # -------------------- Internal helpers --------------------
    def _resolve_calendar_id(
        self: OutlookClientBase,
        calendar_id: Optional[str],
        calendar_name: Optional[str],
    ) -> Optional[str]:
        """Resolve calendar_id from either explicit ID or name lookup."""
        if calendar_id:
            return calendar_id
        if calendar_name:
            return self.get_calendar_id_by_name(calendar_name)
        return None

    def _paginated_get(self: OutlookClientBase, url: str) -> List[Dict[str, Any]]:
        """Fetch all pages from a paginated Graph API endpoint."""
        out: List[Dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value", []) or [])
            url = data.get("@odata.nextLink")
        return out

    @staticmethod
    def _event_endpoint(calendar_id: Optional[str], event_id: Optional[str] = None) -> str:
        """Build Graph API endpoint for events."""
        if calendar_id:
            base = f"{GRAPH_API_URL}/me/calendars/{calendar_id}/events"
        else:
            base = f"{GRAPH_API_URL}/me/events"
        return f"{base}/{event_id}" if event_id else base

    @staticmethod
    def _apply_reminder(payload: Dict[str, Any], no_reminder: bool, reminder_minutes: Optional[int]) -> None:
        """Apply reminder settings to an event payload."""
        if no_reminder:
            payload["isReminderOn"] = False
        elif reminder_minutes is not None:
            payload["isReminderOn"] = True
            payload["reminderMinutesBeforeStart"] = int(reminder_minutes)

    # -------------------- Calendars --------------------
    def list_calendars(self: OutlookClientBase) -> List[Dict[str, Any]]:
        return self._paginated_get(f"{GRAPH_API_URL}/me/calendars")

    def create_calendar(self: OutlookClientBase, name: str) -> Dict[str, Any]:
        body = {"name": name}
        r = _requests().post(f"{GRAPH_API_URL}/me/calendars", headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json()

    def ensure_calendar(self: OutlookClientBase, name: str) -> str:
        target = (name or "").strip().lower()
        if not target:
            raise ValueError("Calendar name is empty")
        for cal in self.list_calendars():
            n = (cal.get("name") or cal.get("displayName") or "").strip().lower()
            if n == target:
                return cal.get("id", "")
        created = self.create_calendar(name)
        return created.get("id", "")

    # Alias for backwards compatibility
    def ensure_calendar_exists(self: OutlookClientBase, name: str) -> str:
        return self.ensure_calendar(name)

    def find_calendar_id(self: OutlookClientBase, name: str) -> Optional[str]:
        return self.get_calendar_id_by_name(name)

    def get_calendar_id_by_name(self: OutlookClientBase, name: str) -> Optional[str]:
        target = (name or "").strip().lower()
        if not target:
            return None
        for cal in self.list_calendars():
            n = (cal.get("name") or cal.get("displayName") or "").strip().lower()
            if n == target:
                cid = cal.get("id")
                if cid:
                    return str(cid)
        return None

    # -------------------- Calendar Sharing --------------------
    def list_calendar_permissions(self: OutlookClientBase, calendar_id: str) -> List[Dict[str, Any]]:
        url = f"{GRAPH_API_URL}/me/calendars/{calendar_id}/calendarPermissions"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("value", [])

    def ensure_calendar_permission(
        self: OutlookClientBase,
        calendar_id: str,
        email: str,
        role: str = "write"
    ) -> Dict[str, Any]:
        """Ensure a calendar permission exists for an external email with the given role.

        role: one of read | write | limitedRead | freeBusyRead | delegateWithoutPrivateEventAccess | delegateWithPrivateEventAccess
        """
        perms = self.list_calendar_permissions(calendar_id)
        for p in perms:
            em = ((p.get("emailAddress") or {}).get("address") or "").strip().lower()
            if em == (email or "").strip().lower():
                cur = (p.get("role") or "").strip()
                if cur.lower() != role.strip().lower():
                    pid = p.get("id")
                    if pid:
                        body = {"role": role}
                        rr = _requests().patch(
                            f"{GRAPH_API_URL}/me/calendars/{calendar_id}/calendarPermissions/{pid}",
                            headers=self._headers(),
                            json=body
                        )
                        rr.raise_for_status()
                        return rr.json() if rr.text else {}
                return p
        body = {"emailAddress": {"address": email}, "role": role}
        r = _requests().post(
            f"{GRAPH_API_URL}/me/calendars/{calendar_id}/calendarPermissions",
            headers=self._headers(),
            json=body
        )
        r.raise_for_status()
        return r.json()

    # -------------------- Events --------------------
    def list_events_in_range(
        self: OutlookClientBase,
        params: "ListEventsRequest",
    ) -> List[Dict[str, Any]]:
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
        self: OutlookClientBase,
        params: "ListCalendarViewRequest",
    ) -> List[Dict[str, Any]]:
        """List calendar view (expanded occurrences) for a date range."""
        base = f"{GRAPH_API_URL}/me/calendars/{params.calendar_id}/calendarView" if params.calendar_id else f"{GRAPH_API_URL}/me/calendarView"
        return self._paginated_get(f"{base}?startDateTime={params.start_iso}&endDateTime={params.end_iso}&$top={int(params.top)}")

    def _resolve_tz(self: OutlookClientBase, tz: Optional[str]) -> str:
        if tz and tz.strip():
            return tz.strip()
        mbx = self.get_mailbox_timezone()
        if mbx:
            return mbx
        return "America/Toronto"

    def create_event(
        self: OutlookClientBase,
        params: Union[EventCreationParams, None] = None,
        *,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        subject: Optional[str] = None,
        start_iso: Optional[str] = None,
        end_iso: Optional[str] = None,
        tz: Optional[str] = None,
        body_html: Optional[str] = None,
        all_day: bool = False,
        location: Optional[str] = None,
        no_reminder: bool = False,
        reminder_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create a one-time event.

        Args:
            params: EventCreationParams object (preferred). If provided, other args are ignored.
            calendar_id: Calendar ID (legacy, use params instead).
            calendar_name: Calendar name (legacy, use params instead).
            subject: Event subject (legacy, use params instead).
            start_iso: Start datetime ISO string (legacy, use params instead).
            end_iso: End datetime ISO string (legacy, use params instead).
            tz: Timezone (legacy, use params instead).
            body_html: HTML body content (legacy, use params instead).
            all_day: Whether this is an all-day event (legacy, use params instead).
            location: Location string (legacy, use params instead).
            no_reminder: Disable reminder (legacy, use params instead).
            reminder_minutes: Reminder minutes before start (legacy, use params instead).

        Returns:
            Created event response from Graph API.
        """
        # Support both params object and legacy kwargs
        if params is not None:
            p = params
        else:
            if subject is None or start_iso is None or end_iso is None:
                raise ValueError("subject, start_iso, and end_iso are required")
            p = EventCreationParams(
                subject=subject,
                start_iso=start_iso,
                end_iso=end_iso,
                calendar_id=calendar_id,
                calendar_name=calendar_name,
                tz=tz,
                body_html=body_html,
                all_day=all_day,
                location=location,
                no_reminder=no_reminder,
                reminder_minutes=reminder_minutes,
            )

        tz_final = self._resolve_tz(p.tz)
        cal_id = self._resolve_calendar_id(p.calendar_id, p.calendar_name)
        payload: Dict[str, Any] = {
            "subject": p.subject,
            "start": {"dateTime": p.start_iso, "timeZone": tz_final},
            "end": {"dateTime": p.end_iso, "timeZone": tz_final},
        }
        if p.body_html:
            payload["body"] = {"contentType": "HTML", "content": p.body_html}
        if p.location:
            payload["location"] = _parse_location(p.location)
        if p.all_day:
            payload["isAllDay"] = True
        self._apply_reminder(payload, p.no_reminder, p.reminder_minutes)
        r = _requests().post(self._event_endpoint(cal_id), headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def create_recurring_event(
        self: OutlookClientBase,
        params: Union[RecurringEventCreationParams, None] = None,
        *,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        subject: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        tz: Optional[str] = None,
        repeat: Optional[str] = None,
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
        """Create a recurring event series.

        Args:
            params: RecurringEventCreationParams object (preferred). If provided, other args are ignored.
            calendar_id: Calendar ID (legacy, use params instead).
            calendar_name: Calendar name (legacy, use params instead).
            subject: Event subject (legacy, use params instead).
            start_time: Start time HH:MM:SS (legacy, use params instead).
            end_time: End time HH:MM:SS (legacy, use params instead).
            tz: Timezone (legacy, use params instead).
            repeat: Recurrence type: daily|weekly|monthly (legacy, use params instead).
            interval: Recurrence interval (legacy, use params instead).
            byday: Days for weekly recurrence ["MO","WE","FR"] (legacy, use params instead).
            range_start_date: Start date YYYY-MM-DD (legacy, use params instead).
            range_until: End date YYYY-MM-DD (legacy, use params instead).
            count: Number of occurrences (legacy, use params instead).
            body_html: HTML body content (legacy, use params instead).
            location: Location string (legacy, use params instead).
            exdates: Dates to exclude (legacy, use params instead).
            no_reminder: Disable reminder (legacy, use params instead).
            reminder_minutes: Reminder minutes before start (legacy, use params instead).

        Returns:
            Created series master event from Graph API.
        """
        # Support both params object and legacy kwargs
        if params is not None:
            p = params
        else:
            if subject is None or start_time is None or end_time is None or repeat is None or range_start_date is None:
                raise ValueError("subject, start_time, end_time, repeat, and range_start_date are required")
            p = RecurringEventCreationParams(
                subject=subject,
                start_time=start_time,
                end_time=end_time,
                repeat=repeat,
                calendar_id=calendar_id,
                calendar_name=calendar_name,
                tz=tz,
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

        tz_final = self._resolve_tz(p.tz)
        cal_id = self._resolve_calendar_id(p.calendar_id, p.calendar_name)

        pattern = self._build_recurrence_pattern(p.repeat, p.interval, p.byday)
        rng = self._build_recurrence_range(p.range_start_date, p.range_until, p.count)

        start_iso = f"{p.range_start_date}T{p.start_time}"
        end_iso = f"{p.range_start_date}T{p.end_time}"

        payload: Dict[str, Any] = {
            "subject": p.subject,
            "start": {"dateTime": start_iso, "timeZone": tz_final},
            "end": {"dateTime": end_iso, "timeZone": tz_final},
            "recurrence": {"pattern": pattern, "range": rng},
        }
        if p.body_html:
            payload["body"] = {"contentType": "HTML", "content": p.body_html}
        if p.location:
            payload["location"] = _parse_location(p.location)
        self._apply_reminder(payload, p.no_reminder, p.reminder_minutes)

        r = _requests().post(self._event_endpoint(cal_id), headers=self._headers(), json=payload)
        r.raise_for_status()
        series = r.json()

        if p.exdates:
            try:
                sid = series.get("id")
                if sid:
                    self._apply_exdate_deletions(cal_id, sid, p.exdates, tz_final, rng)
            except Exception:  # nosec B110 - non-fatal exdate deletion
                pass
        return series

    @staticmethod
    def _build_recurrence_pattern(repeat: str, interval: int, byday: Optional[List[str]]) -> Dict[str, Any]:
        """Build recurrence pattern for Graph API."""
        rpt = (repeat or "").strip().lower()
        pattern: Dict[str, Any] = {"interval": max(1, int(interval))}
        if rpt == "daily":
            pattern["type"] = "daily"
        elif rpt == "weekly":
            pattern["type"] = "weekly"
            pattern["daysOfWeek"] = _normalize_days(byday or [])
        elif rpt in ("monthly", "absolutemonthly"):
            pattern["type"] = "absoluteMonthly"
        else:
            raise ValueError("Unsupported repeat; use daily|weekly|monthly")
        return pattern

    @staticmethod
    def _build_recurrence_range(start_date: str, until: Optional[str], count: Optional[int]) -> Dict[str, Any]:
        """Build recurrence range for Graph API."""
        rng: Dict[str, Any] = {"startDate": start_date}
        if until:
            rng["type"] = "endDate"
            rng["endDate"] = until
        elif count:
            rng["type"] = "numbered"
            rng["numberOfOccurrences"] = int(count)
        else:
            rng["type"] = "noEnd"
        return rng

    def _apply_exdate_deletions(
        self: OutlookClientBase,
        calendar_id: Optional[str],
        series_id: str,
        exdates: List[str],
        _tz: str,
        rng: Dict[str, Any],
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
        self: OutlookClientBase,
        event_id: str,
        calendar_id: Optional[str],
        calendar_name: Optional[str],
        body: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Patch an event and return the result."""
        cal_id = self._resolve_calendar_id(calendar_id, calendar_name)
        r = _requests().patch(self._event_endpoint(cal_id, event_id), headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def update_event_location(
        self: OutlookClientBase,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        location_str: Optional[str] = None,
        location_obj: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Patch the location of an event or series master."""
        if not (location_obj or (location_str and location_str.strip())):
            raise ValueError("Must provide location_str or location_obj")
        loc = location_obj or _parse_location(str(location_str))
        return self._patch_event(event_id, calendar_id, calendar_name, {"location": loc})

    def update_event_reminder(
        self: OutlookClientBase,
        params: "UpdateEventReminderRequest",
    ) -> Dict[str, Any]:
        """Patch event reminder fields."""
        body: Dict[str, Any] = {"isReminderOn": bool(params.is_on)}
        if params.minutes_before_start is not None:
            body["reminderMinutesBeforeStart"] = int(params.minutes_before_start)
        return self._patch_event(params.event_id, params.calendar_id, params.calendar_name, body)

    def update_event_settings(
        self: OutlookClientBase,
        params: "EventSettingsPatch",
    ) -> Dict[str, Any]:
        """Patch selected event fields in one request."""
        body: Dict[str, Any] = {}
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
        self: OutlookClientBase,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        subject: str,
    ) -> Dict[str, Any]:
        """Patch the subject/title of an event or series master."""
        return self._patch_event(event_id, calendar_id, calendar_name, {"subject": subject})

    def delete_event(
        self: OutlookClientBase,
        event_id: str,
        calendar_id: Optional[str] = None
    ) -> None:
        r = _requests().delete(self._event_endpoint(calendar_id, event_id), headers=self._headers())
        if r.status_code not in (200, 202, 204):
            r.raise_for_status()

    def delete_event_by_id(
        self: OutlookClientBase,
        event_id: str,
        calendar_id: Optional[str] = None
    ) -> bool:
        """Delete an event by ID, return True if successful."""
        try:
            self.delete_event(event_id, calendar_id)
            return True
        except Exception:
            return False


# -------------------- Location parsing --------------------
def _parse_location(loc: str) -> Dict[str, Any]:
    """Parse a location string into Outlook location with structured address when possible."""
    disp = (loc or "").strip()

    def _split_name_and_addr(s: str) -> Tuple[str, str]:
        if "(" in s and ")" in s:
            try:
                nm, rest = s.split("(", 1)
                addr = rest.rsplit(")", 1)[0]
                return nm.strip(), addr.strip()
            except Exception:  # nosec B110 - malformed parens, try other patterns
                pass
        if " at " in s:
            head, addr = s.rsplit(" at ", 1)
            return head.strip(), addr.strip()
        m = re.search(r"\b\d+\b", s)
        if m:
            return s[:m.start()].strip(), s[m.start():].strip()
        return s.strip(), ""

    def _parse_addr(addr: str) -> Dict[str, Any]:
        parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
        street = city = state = postal = country = None
        if parts:
            street = parts[0]
        if len(parts) == 2:
            tail = parts[1]
            toks = tail.split()
            if len(toks) >= 2 and re.match(r"^[A-Z]{2}$", toks[0]) and re.match(
                r"^[A-Z][0-9][A-Z]$|^[A-Z][0-9][A-Z]\s[0-9][A-Z][0-9]$",
                (" ".join(toks[1:])).upper()
            ):
                state = toks[0]
                rest = " ".join(toks[1:]).upper()
                mpc = re.search(r"[A-Z][0-9][A-Z]\s?[0-9][A-Z][0-9]", rest)
                if mpc:
                    postal = rest[mpc.start():mpc.end()].replace(" ", " ")
                cand = parts[0].strip()
                words = [w for w in cand.split() if w]

                def is_word_city(w: str) -> bool:
                    return any(ch.isalpha() for ch in w) and not any(ch.isdigit() for ch in w)

                if len(words) >= 2 and is_word_city(words[-1]) and is_word_city(words[-2]):
                    city = f"{words[-2]} {words[-1]}"
                    street = " ".join(words[:-2]) or street
                elif len(words) >= 1 and is_word_city(words[-1]):
                    city = words[-1]
                    street = " ".join(words[:-1]) or street
            else:
                city = parts[1]
        if len(parts) >= 3:
            city = parts[-2]
            tail = parts[-1]
            toks = tail.split()
            canada_pc = None
            if len(toks) >= 2:
                pair = (toks[-2] + " " + toks[-1]).upper()
                if re.match(r"^[A-Z][0-9][A-Z]\s[0-9][A-Z][0-9]$", pair):
                    canada_pc = pair
                    toks = toks[:-2]
            if canada_pc:
                postal = canada_pc
            for t in toks:
                tt = t.strip().strip(",")
                if len(tt) == 2 and tt.isalpha():
                    state = tt
            if not postal:
                for t in reversed(toks):
                    if any(ch.isdigit() for ch in t):
                        postal = t
                        break
        if len(parts) >= 4 and not country:
            country = parts[-1]
        addr_obj: Dict[str, Any] = {}
        if street:
            addr_obj["street"] = street
        if city:
            addr_obj["city"] = city
        if state:
            addr_obj["state"] = state
        if postal:
            addr_obj["postalCode"] = postal
        if country:
            addr_obj["countryOrRegion"] = country
        return addr_obj

    name, addr = _split_name_and_addr(disp)
    if addr:
        try:
            addr_obj = _parse_addr(addr)
        except Exception:
            addr_obj = {}
    else:
        addr_obj = {}

    loc_obj: Dict[str, Any] = {"displayName": name or disp}
    if addr_obj:
        loc_obj["address"] = addr_obj
    return loc_obj


def _normalize_days(days: List[str]) -> List[str]:
    """Map MO,TU,WE,TH,FR,SA,SU -> monday,tuesday,... as Graph expects."""
    map_short = {
        "MO": "monday",
        "TU": "tuesday",
        "WE": "wednesday",
        "TH": "thursday",
        "FR": "friday",
        "SA": "saturday",
        "SU": "sunday",
    }
    out: List[str] = []
    for d in days:
        if not d:
            continue
        dd = d.strip()
        if len(dd) == 2:
            out.append(map_short.get(dd.upper(), dd.lower()))
        else:
            out.append(dd.lower())
    seen = set()
    uniq = []
    for d in out:
        if d not in seen:
            uniq.append(d)
            seen.add(d)
    return uniq
