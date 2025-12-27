"""Calendar and event operations for Outlook via Microsoft Graph."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .client import OutlookClientBase, _requests, GRAPH


class OutlookCalendarMixin:
    """Mixin providing calendar and event operations.

    Requires OutlookClientBase methods: _headers, get_mailbox_timezone
    """

    # -------------------- Calendars --------------------
    def list_calendars(self: OutlookClientBase) -> List[Dict[str, Any]]:
        url = f"{GRAPH}/me/calendars"
        out: List[Dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value", []) or [])
            url = data.get("@odata.nextLink")
        return out

    def create_calendar(self: OutlookClientBase, name: str) -> Dict[str, Any]:
        body = {"name": name}
        r = _requests().post(f"{GRAPH}/me/calendars", headers=self._headers(), json=body)
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
        url = f"{GRAPH}/me/calendars/{calendar_id}/calendarPermissions"
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
                            f"{GRAPH}/me/calendars/{calendar_id}/calendarPermissions/{pid}",
                            headers=self._headers(),
                            json=body
                        )
                        rr.raise_for_status()
                        return rr.json() if rr.text else {}
                return p
        body = {"emailAddress": {"address": email}, "role": role}
        r = _requests().post(
            f"{GRAPH}/me/calendars/{calendar_id}/calendarPermissions",
            headers=self._headers(),
            json=body
        )
        r.raise_for_status()
        return r.json()

    # -------------------- Events --------------------
    def list_events_in_range(
        self: OutlookClientBase,
        *,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        start_iso: str,
        end_iso: str,
        subject_filter: Optional[str] = None,
        top: int = 50
    ) -> List[Dict[str, Any]]:
        """List events for a calendar within [start_iso, end_iso].

        Uses calendarView which expands recurring series. Optional subject_filter
        performs a client-side case-insensitive match.
        """
        cal_id = calendar_id or (self.get_calendar_id_by_name(calendar_name or "") if calendar_name else None)
        endpoint = f"{GRAPH}/me/calendarView" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/calendarView"
        url = f"{endpoint}?startDateTime={start_iso}&endDateTime={end_iso}&$top={int(top)}"
        out: List[Dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json() or {}
            vals = data.get("value", []) or []
            for ev in vals:
                if subject_filter:
                    sub = (ev.get("subject") or "").lower()
                    if subject_filter.lower() not in sub:
                        continue
                out.append(ev)
            url = data.get("@odata.nextLink")
        return out

    def _resolve_tz(self: OutlookClientBase, tz: Optional[str]) -> str:
        if tz and tz.strip():
            return tz.strip()
        mbx = self.get_mailbox_timezone()
        if mbx:
            return mbx
        return "America/Toronto"

    def create_event(
        self: OutlookClientBase,
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
        tz_final = self._resolve_tz(tz)
        cal_id = calendar_id or (self.get_calendar_id_by_name(calendar_name or "") if calendar_name else None)
        endpoint = f"{GRAPH}/me/events" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/events"
        payload: Dict[str, Any] = {
            "subject": subject,
            "start": {"dateTime": start_iso, "timeZone": tz_final},
            "end": {"dateTime": end_iso, "timeZone": tz_final},
        }
        if body_html:
            payload["body"] = {"contentType": "HTML", "content": body_html}
        if location:
            payload["location"] = _parse_location(location)
        if all_day:
            payload["isAllDay"] = True
        if no_reminder:
            payload["isReminderOn"] = False
        if reminder_minutes is not None:
            try:
                payload["isReminderOn"] = True
                payload["reminderMinutesBeforeStart"] = int(reminder_minutes)
            except Exception:  # noqa: S110 - invalid reminder_minutes
                pass
        r = _requests().post(endpoint, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def create_recurring_event(
        self: OutlookClientBase,
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
        range_start_date: str,
        range_until: Optional[str] = None,
        count: Optional[int] = None,
        body_html: Optional[str] = None,
        location: Optional[str] = None,
        exdates: Optional[List[str]] = None,
        no_reminder: bool = False,
        reminder_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        tz_final = self._resolve_tz(tz)
        cal_id = calendar_id or (self.get_calendar_id_by_name(calendar_name or "") if calendar_name else None)
        endpoint = f"{GRAPH}/me/events" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/events"

        rpt = (repeat or "").strip().lower()
        pattern: Dict[str, Any] = {"interval": max(1, int(interval))}
        if rpt in ("daily",):
            pattern.update({"type": "daily"})
        elif rpt in ("weekly",):
            pattern.update({"type": "weekly", "daysOfWeek": _normalize_days(byday or [])})
        elif rpt in ("monthly", "absoluteMonthly"):
            pattern.update({"type": "absoluteMonthly"})
        else:
            raise ValueError("Unsupported repeat; use daily|weekly|monthly")

        rng: Dict[str, Any] = {
            "type": "endDate" if range_until else ("numbered" if count else "noEnd"),
            "startDate": range_start_date
        }
        if range_until:
            rng["endDate"] = range_until
        if count:
            rng["numberOfOccurrences"] = int(count)

        start_iso = f"{range_start_date}T{start_time}"
        end_iso = f"{range_start_date}T{end_time}"

        payload: Dict[str, Any] = {
            "subject": subject,
            "start": {"dateTime": start_iso, "timeZone": tz_final},
            "end": {"dateTime": end_iso, "timeZone": tz_final},
            "recurrence": {"pattern": pattern, "range": rng},
        }
        if body_html:
            payload["body"] = {"contentType": "HTML", "content": body_html}
        if location:
            payload["location"] = _parse_location(location)
        if no_reminder:
            payload["isReminderOn"] = False
        if reminder_minutes is not None:
            try:
                payload["isReminderOn"] = True
                payload["reminderMinutesBeforeStart"] = int(reminder_minutes)
            except Exception:  # noqa: S110 - invalid reminder_minutes
                pass

        r = _requests().post(endpoint, headers=self._headers(), json=payload)
        r.raise_for_status()
        series = r.json()

        if exdates:
            try:
                sid = series.get("id")
                if sid:
                    self._apply_exdate_deletions(cal_id, sid, exdates, tz_final, rng)
            except Exception:  # noqa: S110 - non-fatal exdate deletion
                pass
        return series

    def _apply_exdate_deletions(
        self: OutlookClientBase,
        calendar_id: Optional[str],
        series_id: str,
        exdates: List[str],
        tz: str,
        rng: Dict[str, Any],
    ) -> None:
        start_date = rng.get("startDate")
        end_date = rng.get("endDate") or start_date
        start_dt = f"{start_date}T00:00:00"
        end_dt = f"{end_date}T23:59:59"
        base = f"{GRAPH}/me/events/{series_id}" if not calendar_id else f"{GRAPH}/me/calendars/{calendar_id}/events/{series_id}"
        url = f"{base}/instances?startDateTime={start_dt}&endDateTime={end_dt}"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        vals = r.json().get("value", [])
        ex_set = {d.strip() for d in exdates if d and d.strip()}
        for inst in vals:
            iid = inst.get("id")
            st = (inst.get("start") or {}).get("dateTime") or ""
            date_only = st.split("T", 1)[0] if "T" in st else st
            if iid and date_only in ex_set:
                del_url = f"{GRAPH}/me/events/{iid}" if not calendar_id else f"{GRAPH}/me/calendars/{calendar_id}/events/{iid}"
                _requests().delete(del_url, headers=self._headers())

    # -------------------- Event Updates --------------------
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
        cal_id = calendar_id
        if not cal_id and calendar_name:
            cal_id = self.get_calendar_id_by_name(calendar_name)
        if not (location_obj or (location_str and location_str.strip())):
            raise ValueError("Must provide location_str or location_obj")
        loc = location_obj or _parse_location(str(location_str))
        endpoint = f"{GRAPH}/me/events/{event_id}" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/events/{event_id}"
        body = {"location": loc}
        r = _requests().patch(endpoint, headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def update_event_reminder(
        self: OutlookClientBase,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        is_on: bool = False,
        minutes_before_start: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Patch event reminder fields."""
        cal_id = calendar_id
        if not cal_id and calendar_name:
            cal_id = self.get_calendar_id_by_name(calendar_name)
        endpoint = f"{GRAPH}/me/events/{event_id}" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/events/{event_id}"
        body: Dict[str, Any] = {"isReminderOn": bool(is_on)}
        if minutes_before_start is not None:
            body["reminderMinutesBeforeStart"] = int(minutes_before_start)
        r = _requests().patch(endpoint, headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def update_event_fields(
        self: OutlookClientBase,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        categories: Optional[List[str]] = None,
        show_as: Optional[str] = None,
        sensitivity: Optional[str] = None,
        is_reminder_on: Optional[bool] = None,
        reminder_minutes: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Patch selected event fields in one request."""
        cal_id = calendar_id
        if not cal_id and calendar_name:
            cal_id = self.get_calendar_id_by_name(calendar_name)
        endpoint = f"{GRAPH}/me/events/{event_id}" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/events/{event_id}"
        body: Dict[str, Any] = {}
        if categories is not None:
            body["categories"] = list(categories)
        if show_as:
            body["showAs"] = str(show_as)
        if sensitivity:
            body["sensitivity"] = str(sensitivity)
        if is_reminder_on is not None:
            body["isReminderOn"] = bool(is_reminder_on)
        if reminder_minutes is not None:
            body["reminderMinutesBeforeStart"] = int(reminder_minutes)
        if not body:
            return {}
        r = _requests().patch(endpoint, headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def update_event_subject(
        self: OutlookClientBase,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        subject: str,
    ) -> Dict[str, Any]:
        """Patch the subject/title of an event or series master."""
        cal_id = calendar_id
        if not cal_id and calendar_name:
            cal_id = self.get_calendar_id_by_name(calendar_name)
        endpoint = f"{GRAPH}/me/events/{event_id}" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/events/{event_id}"
        body: Dict[str, Any] = {"subject": subject}
        r = _requests().patch(endpoint, headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def delete_event(
        self: OutlookClientBase,
        event_id: str,
        calendar_id: Optional[str] = None
    ) -> None:
        base = f"{GRAPH}/me/events/{event_id}" if not calendar_id else f"{GRAPH}/me/calendars/{calendar_id}/events/{event_id}"
        r = _requests().delete(base, headers=self._headers())
        if r.status_code not in (200, 202, 204):
            r.raise_for_status()


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
            except Exception:  # noqa: S110 - malformed parens, try other patterns
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
    """Map MO,TU,WE,TH,FR,SA,SU → monday,tuesday,... as Graph expects."""
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
