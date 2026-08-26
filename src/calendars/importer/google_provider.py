"""Google Calendar implementation of CalendarProvider.

Production implementor of the CalendarProvider Protocol backed by the
Google Calendar API (calendar/v3) via GoogleCalendarService.
Dependency-injected so tests can pass a fake service without touching
the network.

RRULE support
-------------
Google encodes recurrence as a list of strings in ``event["recurrence"]``.
This module parses RRULE lines into CalendarEvent fields.

Representable patterns (FREQ -> repeat value):
  DAILY   -> "daily"
  WEEKLY  -> "weekly"
  MONTHLY -> "monthly"

Unrepresentable patterns are SKIPPED and recorded in ``self.skipped``
with a ``reason`` key.  They are never returned in a degraded form.

Unsupported:
  FREQ=YEARLY
  BYSETPOS
  BYMONTHDAY
  Multiple RRULEs on one event
  RDATE lines
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field, replace
from typing import Any

from calendars.gmail_pipelines import CalendarEvent


# ---------------------------------------------------------------------------
# RRULE parser helpers
# ---------------------------------------------------------------------------

_FREQ_MAP: dict[str, str] = {
    "DAILY": "daily",
    "WEEKLY": "weekly",
    "MONTHLY": "monthly",
}

# Parts of an RRULE value string, e.g. "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=20260630T235959Z"
_RRULE_PREFIX = re.compile(r"^RRULE:", re.IGNORECASE)


def _parse_rrule(rrule_str: str) -> dict[str, Any]:
    """Parse an RRULE string into a param dict.

    Returns a dict of uppercase param names -> str values (e.g.
    ``{"FREQ": "WEEKLY", "BYDAY": "MO,WE", "UNTIL": "20260630T235959Z"}``).
    The ``RRULE:`` prefix is stripped if present.
    """
    body = _RRULE_PREFIX.sub("", rrule_str).strip()
    params: dict[str, str] = {}
    for part in body.split(";"):
        part = part.strip()
        if "=" not in part:
            continue
        key, _, val = part.partition("=")
        params[key.upper()] = val
    return params


def _shift_date(date_str: str, days: int) -> str:
    """Return ``date_str`` (YYYY-MM-DD) shifted by ``days``, or it unchanged.

    An unparseable or empty value is returned as-is rather than raising: the
    caller is normalising a boundary, not validating the event.
    """
    s = (date_str or "").strip()
    if not s:
        return s
    try:
        return (_dt.date.fromisoformat(s) + _dt.timedelta(days=days)).isoformat()
    except ValueError:
        return s


def _exclusive_end_to_inclusive(end_date: str) -> str:
    """Google all-day end.date (exclusive) -> plan end (inclusive)."""
    return _shift_date(end_date, -1)


def _inclusive_end_to_exclusive(end_date: str) -> str:
    """Plan all-day end (inclusive) -> Google end.date (exclusive)."""
    return _shift_date(end_date, 1)


def _until_to_date(until_val: str) -> str:
    """Convert UNTIL value (20260630T235959Z or 20260630) to YYYY-MM-DD."""
    # Strip time component if present
    date_part = until_val.split("T")[0]
    if len(date_part) == 8:
        return f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
    return date_part


def _collect_exdates_from_recurrence(recurrence: list[str]) -> list[str]:
    """Extract EXDATE values from the recurrence list, returned as YYYY-MM-DD strings."""
    exdates: list[str] = []
    for line in recurrence:
        upper = line.upper()
        if upper.startswith("EXDATE"):
            # EXDATE;TZID=...:20260101T... or EXDATE:20260101
            _, _, values = line.partition(":")
            for val in values.split(","):
                val = val.strip()
                if val:
                    date_part = val.split("T")[0]
                    # Convert compact form YYYYMMDD to YYYY-MM-DD
                    if len(date_part) == 8 and date_part.isdigit():
                        date_part = f"{date_part[:4]}-{date_part[4:6]}-{date_part[6:8]}"
                    exdates.append(date_part)
    return sorted(set(exdates))


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


@dataclass
class GoogleCalendarProvider:
    """Production CalendarProvider backed by Google Calendar API (calendar/v3).

    Satisfies ``calendars.importer.base.CalendarProvider`` structurally —
    no inheritance is required because the protocol is ``@runtime_checkable``
    and both methods match its signature exactly.

    Constructor parameters
    ----------------------
    svc
        A ``GoogleCalendarService`` instance (or a test fake exposing
        ``list_events(calendar_id, time_min, time_max) -> list[dict]`` and
        ``insert_event(calendar_id, body) -> dict``).
    calendar_id
        Google Calendar identifier (e.g. ``"primary"`` or a full email).
        Defaults to ``"primary"``.

    Attributes
    ----------
    skipped
        Records every event that could not be represented as a CalendarEvent.
        Each entry is a dict with at least a ``reason`` key.  Reset on each
        call to ``list_events``.
    """

    svc: Any
    calendar_id: str = "primary"
    skipped: list[dict[str, Any]] = field(default_factory=list, init=False)

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def list_events(self, date_range: tuple[str, str]) -> list[CalendarEvent]:
        """Return CalendarEvent objects for all events in the given ISO date range.

        Recurring events carry RRULE strings in their ``recurrence`` list.
        Representable patterns (DAILY/WEEKLY/MONTHLY) are parsed into the
        CalendarEvent recurrence fields.  Unrepresentable patterns (YEARLY,
        BYSETPOS, BYMONTHDAY, multiple RRULEs, RDATE) are skipped and recorded
        in ``self.skipped`` — never returned in a degraded form.

        Parameters
        ----------
        date_range
            ``(start_iso, end_iso)`` strings in ISO format (``YYYY-MM-DD`` or
            full RFC 3339).  ``T00:00:00Z`` is appended to date-only strings.
        """
        self.skipped = []
        start_iso, end_iso = date_range
        time_min = _ensure_rfc3339(start_iso)
        time_max = _ensure_rfc3339(end_iso)

        raw_events = self.svc.list_events(self.calendar_id, time_min, time_max)

        results: list[CalendarEvent] = []
        for ev in raw_events or []:
            ce = self._google_event_to_calendar_event(ev)
            if ce is not None:
                results.append(ce)
        return results

    def add_event(self, event: CalendarEvent) -> CalendarEvent:
        """Insert a CalendarEvent into the Google calendar and return the persisted result.

        When ``event.repeat`` is set an RRULE string is included in the insert body.
        """
        body = self._calendar_event_to_body(event)
        result = self.svc.insert_event(self.calendar_id, body)
        persisted = self._google_event_to_calendar_event(result)
        # Always carry the SUBMITTED event's fields forward, overlaying only what
        # the API actually echoed back (the assigned id, and any field it
        # returned). Google's insert response commonly omits recurrence, so
        # trusting the mapped response alone hands the caller an event with
        # repeat/byday/interval/range set to None — silently disagreeing with
        # what was just persisted. That is exactly the degradation CalendarEvent
        # was widened to prevent, and it is invisible without asserting on the
        # return value.
        new_id = (persisted.id if persisted else result.get("id")) or ""
        if persisted is not None and persisted.repeat:
            return replace(persisted, calendar=self.calendar_id)
        return replace(event, id=new_id, calendar=self.calendar_id)

    # ------------------------------------------------------------------
    # Internal helpers — list_events
    # ------------------------------------------------------------------

    def _google_event_to_calendar_event(self, ev: dict[str, Any]) -> CalendarEvent | None:
        """Map a calendar/v3 event dict to CalendarEvent, or None when skipped."""
        ev_id = ev.get("id") or ""
        subject = ev.get("summary") or ""
        tz: str | None = None
        location = ev.get("location") or None

        # Determine start/end (all-day uses "date", timed uses "dateTime")
        start_obj = ev.get("start") or {}
        end_obj = ev.get("end") or {}

        if "date" in start_obj:
            # All-day event. Google's end.date is EXCLUSIVE (the day after the
            # last covered day); the plan format's end is INCLUSIVE, so a
            # one-day event is start == end there. Passing Google's value
            # through unchanged stretches every all-day event by a day.
            start = start_obj["date"]
            end = _exclusive_end_to_inclusive(end_obj.get("date") or "")
        else:
            start = start_obj.get("dateTime") or ""
            end = end_obj.get("dateTime") or ""
            tz = start_obj.get("timeZone") or end_obj.get("timeZone") or None

        recurrence: list[str] = ev.get("recurrence") or []

        if not recurrence:
            # Non-recurring event
            return CalendarEvent(
                id=ev_id,
                subject=subject,
                start=start,
                end=end,
                calendar=self.calendar_id,
                tz=tz,
                location=location,
            )

        # Parse recurrence lines
        return self._parse_recurring_event(ev_id, subject, start, end, tz, location, recurrence)

    def _parse_recurring_event(
        self,
        ev_id: str,
        subject: str,
        start: str,
        end: str,
        tz: str | None,
        location: str | None,
        recurrence: list[str],
    ) -> CalendarEvent | None:
        """Parse recurrence lines into a CalendarEvent, skipping unrepresentable forms."""
        # Collect RRULEs and check for multiple
        rrule_lines = [line for line in recurrence if line.upper().startswith("RRULE:")]
        rdate_lines = [line for line in recurrence if line.upper().startswith("RDATE")]

        if rdate_lines:
            self.skipped.append({"id": ev_id, "subject": subject, "reason": "unsupported_rdate"})
            return None

        if len(rrule_lines) > 1:
            self.skipped.append({"id": ev_id, "subject": subject, "reason": "multiple_rrules"})
            return None

        if not rrule_lines:
            # Recurrence list with no RRULE (e.g. only EXDATE) — treat as non-recurring
            return CalendarEvent(
                id=ev_id,
                subject=subject,
                start=start,
                end=end,
                calendar=self.calendar_id,
                tz=tz,
                location=location,
            )

        params = _parse_rrule(rrule_lines[0])
        freq = params.get("FREQ", "").upper()

        # Check for unsupported properties before checking FREQ so we can catch
        # YEARLY + unsupported combos in a single pass
        if "BYSETPOS" in params:
            self.skipped.append({"id": ev_id, "subject": subject, "reason": "unsupported_bysetpos"})
            return None

        if "BYMONTHDAY" in params:
            self.skipped.append({"id": ev_id, "subject": subject, "reason": "unsupported_bymonthday"})
            return None

        if freq not in _FREQ_MAP:
            self.skipped.append({
                "id": ev_id,
                "subject": subject,
                "freq": freq,
                "reason": f"unsupported_freq_{freq.lower()}" if freq else "missing_freq",
            })
            return None

        repeat = _FREQ_MAP[freq]

        # BYDAY -> uppercase 2-char list (RRULE already uses this form)
        byday: list[str] = []
        if "BYDAY" in params:
            byday = [d.strip().upper() for d in params["BYDAY"].split(",") if d.strip()]

        # INTERVAL — None when 1 (or absent)
        interval_raw = params.get("INTERVAL")
        interval: int | None = None
        if interval_raw is not None:
            try:
                v = int(interval_raw)
                interval = v if v > 1 else None
            except ValueError:
                # Do NOT swallow this. A malformed INTERVAL silently treated as
                # absent exports a triweekly series as plain weekly — a wrong
                # plan that still looks correct. Skip and record instead.
                self.skipped.append({
                    "id": ev_id,
                    "subject": subject,
                    "reason": "malformed_interval",
                    "value": str(interval_raw),
                })
                return None

        # UNTIL / COUNT
        range_dict: dict[str, str] | None = None
        count: int | None = None

        if "UNTIL" in params:
            until_date = _until_to_date(params["UNTIL"])
            # range start_date from the event start
            range_start = start.split("T")[0] if "T" in start else start
            range_dict = {"start_date": range_start, "until": until_date}
        elif "COUNT" in params:
            try:
                count = int(params["COUNT"])
            except ValueError:
                # A malformed COUNT dropped silently turns a bounded series into
                # an unbounded one on re-import. Skip and record.
                self.skipped.append({
                    "id": ev_id,
                    "subject": subject,
                    "reason": "malformed_count",
                    "value": str(params["COUNT"]),
                })
                return None

        # EXDATE lines
        exdates = _collect_exdates_from_recurrence(recurrence)

        # Recurring events: start_time / end_time extracted from dateTime strings
        start_time: str | None = None
        end_time: str | None = None
        if "T" in start:
            start_time = start.split("T")[1][:5]  # HH:MM
        if "T" in end:
            end_time = end.split("T")[1][:5]

        return CalendarEvent(
            id=ev_id,
            subject=subject,
            start=start,
            end=end,
            calendar=self.calendar_id,
            tz=tz,
            location=location,
            repeat=repeat,
            interval=interval,
            byday=byday,
            range=range_dict,
            start_time=start_time,
            end_time=end_time,
            exdates=exdates,
            count=count,
        )

    # ------------------------------------------------------------------
    # Internal helpers — add_event
    # ------------------------------------------------------------------

    def _calendar_event_to_body(self, event: CalendarEvent) -> dict[str, Any]:
        """Translate a CalendarEvent into a calendar/v3 insert body dict."""
        body: dict[str, Any] = {
            "summary": event.subject,
        }
        if event.location:
            body["location"] = event.location

        # Start / end
        if "T" in (event.start or ""):
            # Timed event
            tz = event.tz or "UTC"
            body["start"] = {"dateTime": event.start, "timeZone": tz}
            body["end"] = {"dateTime": event.end, "timeZone": tz}
        else:
            # All-day event: convert the plan's INCLUSIVE end back to Google's
            # EXCLUSIVE end, the inverse of the read path above.
            body["start"] = {"date": event.start}
            body["end"] = {"date": _inclusive_end_to_exclusive(event.end)}

        # Recurrence
        if event.repeat:
            rrule = _build_rrule(event)
            recurrence = [f"RRULE:{rrule}"]
            body["recurrence"] = recurrence

        return body


def _build_rrule(event: CalendarEvent) -> str:
    """Build an RRULE value string from a CalendarEvent's recurrence fields.

    Raises ValueError for a repeat value with no RRULE equivalent. Defaulting
    to WEEKLY would persist a recurrence the caller never asked for — writing a
    wrong rule into a real calendar, which is worse than the read-side
    degradation this provider already refuses. Callers reach here only when
    event.repeat is set, so an unrecognised value is a genuine error.
    """
    freq_map_rev = {"daily": "DAILY", "weekly": "WEEKLY", "monthly": "MONTHLY"}
    repeat = (event.repeat or "").lower()
    if repeat not in freq_map_rev:
        raise ValueError(
            f"Cannot build an RRULE for repeat={event.repeat!r}; "
            f"supported values are {sorted(freq_map_rev)}"
        )
    freq = freq_map_rev[repeat]

    parts = [f"FREQ={freq}"]

    if event.byday:
        parts.append(f"BYDAY={','.join(event.byday)}")

    interval = event.interval or 1
    if interval > 1:
        parts.append(f"INTERVAL={interval}")

    rng = event.range or {}
    if rng.get("until"):
        # Convert YYYY-MM-DD -> YYYYMMDDT235959Z
        until_compact = rng["until"].replace("-", "") + "T235959Z"
        parts.append(f"UNTIL={until_compact}")
    elif event.count:
        parts.append(f"COUNT={event.count}")

    return ";".join(parts)


def _ensure_rfc3339(value: str) -> str:
    """Append T00:00:00Z to a date-only string if needed."""
    if "T" not in value:
        return f"{value}T00:00:00Z"
    return value


__all__ = ["GoogleCalendarProvider"]
