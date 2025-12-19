from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional, Tuple

# Lazy optional deps: avoid importing on --help to prevent warnings/overhead
msal = None  # type: ignore
requests = None  # type: ignore

def _msal():  # type: ignore
    global msal
    if msal is None:  # pragma: no cover - optional import
        import msal as _msal  # type: ignore
        msal = _msal
    return msal

def _requests():  # type: ignore
    global requests
    if requests is None:  # pragma: no cover - optional import
        import requests as _requests  # type: ignore
        requests = _requests
    return requests


GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = [
    "Mail.ReadWrite",
    "Mail.ReadWrite.Shared",
    "MailboxSettings.ReadWrite",
    "Calendars.ReadWrite",
]


class OutlookClient:
    """Minimal Microsoft Graph client for Outlook mail operations.

    Maps Gmail-like operations to nearest Outlook constructs:
    - Labels -> Outlook categories (many-to-many on messages)
    - Filters -> Inbox rules (messageRules on Inbox)
    - Forwarding -> Rule action forwardTo
    """

    def __init__(
        self,
        client_id: str,
        tenant: str = "consumers",
        token_path: Optional[str] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        self.client_id = client_id
        self.tenant = tenant
        self.token_path = token_path
        self.cache_dir = cache_dir
        self._token: Optional[Dict[str, Any]] = None
        # Prefer persistent MSAL token cache so sessions last across runs
        self._cache: Optional["msal.SerializableTokenCache"] = None
        self._app: Optional["msal.PublicClientApplication"] = None
        # Use Graph .default to request the app's configured delegated permissions.
        # MSAL will handle refresh tokens via the token cache.
        self._scopes: List[str] = ["https://graph.microsoft.com/.default"]
        # Provider key for simple JSON config caching
        self._cfg_provider = "outlook"
        # expose GRAPH for external helpers
        self.GRAPH = GRAPH

    # -------------------- Simple config JSON cache --------------------
    def _cfg_path(self, name: str) -> Optional[str]:
        if not self.cache_dir:
            return None
        import os
        return os.path.join(self.cache_dir, self._cfg_provider, "config", f"{name}.json")

    def cfg_get_json(self, name: str, ttl: int) -> Optional[Dict[str, Any]]:
        p = self._cfg_path(name)
        if not p:
            return None
        import os, json, time
        if not os.path.exists(p):
            return None
        try:
            if ttl > 0:
                age = time.time() - os.path.getmtime(p)
                if age > ttl:
                    return None
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return None

    def cfg_put_json(self, name: str, data: Any) -> None:
        p = self._cfg_path(name)
        if not p:
            return
        import os, json
        os.makedirs(os.path.dirname(p), exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False)
        except Exception:
            pass

    def cfg_clear(self) -> None:
        p = self._cfg_path(".")
        if not p:
            return
        import os, shutil
        config_dir = os.path.dirname(p)
        try:
            if os.path.isdir(config_dir):
                shutil.rmtree(config_dir)
        except Exception:
            pass

    # -------------------- Auth --------------------
    def authenticate(self) -> None:
        # Initialize or load persistent MSAL cache
        cache = _msal().SerializableTokenCache()
        if self.token_path and os.path.exists(self.token_path):
            try:
                # Backward compat: if a legacy JSON with access_token is present, try to use it once
                with open(self.token_path, "r", encoding="utf-8") as f:
                    data = f.read()
                try:
                    # Try to deserialize as MSAL cache
                    cache.deserialize(data)
                except Exception:
                    # Fallback: legacy simple token format
                    tok = json.loads(data)
                    if tok.get("access_token") and (tok.get("expires_at", 0) - 60) > time.time():
                        self._token = tok
                        # Proceed without MSAL cache; will upgrade on next device login
                        self._cache = cache
                        self._app = _msal().PublicClientApplication(self.client_id, authority=f"https://login.microsoftonline.com/{self.tenant}")
                        return
            except Exception:
                pass

        app = _msal().PublicClientApplication(
            self.client_id,
            authority=f"https://login.microsoftonline.com/{self.tenant}",
            token_cache=cache,
        )
        # Try silent first
        acct = None
        try:
            accts = app.get_accounts()
            acct = accts[0] if accts else None
        except Exception:
            acct = None
        if acct is not None:
            result = app.acquire_token_silent(self._scopes, account=acct)
            if result and "access_token" in result:
                self._token = {"access_token": result["access_token"], "expires_at": time.time() + int(result.get("expires_in", 3600))}
                self._cache = cache
                self._app = app
                if self.token_path:
                    os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
                    with open(self.token_path, "w", encoding="utf-8") as f:
                        f.write(cache.serialize())
                return

        # Start device flow if silent failed
        flow = app.initiate_device_flow(scopes=self._scopes)
        if "user_code" not in flow:
            raise RuntimeError("Failed to start device flow for Microsoft Graph")
        print(f"To sign in, visit {flow['verification_uri']} and enter code: {flow['user_code']}")
        result = app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"Device flow failed: {result}")
        self._token = {"access_token": result["access_token"], "expires_at": time.time() + int(result.get("expires_in", 3600))}
        self._cache = cache
        self._app = app
        if self.token_path:
            os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
            with open(self.token_path, "w", encoding="utf-8") as f:
                f.write(cache.serialize())

    def _headers(self) -> Dict[str, str]:
        if not self._token:
            raise RuntimeError("OutlookClient not authenticated")
        # Attempt silent refresh to keep sessions alive
        try:
            if self._app is not None:
                acct = None
                accts = self._app.get_accounts()
                acct = accts[0] if accts else None
                if acct is not None:
                    res = self._app.acquire_token_silent(self._scopes, account=acct)
                    if res and "access_token" in res:
                        self._token = {"access_token": res["access_token"], "expires_at": time.time() + int(res.get("expires_in", 3600))}
                        if self._cache and self.token_path:
                            with open(self.token_path, "w", encoding="utf-8") as f:
                                f.write(self._cache.serialize())
        except Exception:
            pass
        return {"Authorization": f"Bearer {self._token['access_token']}", "Content-Type": "application/json"}

    def _headers_search(self) -> Dict[str, str]:
        h = self._headers()
        # Required for $search queries
        h["ConsistencyLevel"] = "eventual"
        return h

    # -------------------- Mailbox settings --------------------
    def get_mailbox_timezone(self) -> Optional[str]:
        try:
            r = _requests().get(f"{GRAPH}/me/mailboxSettings", headers=self._headers())
            r.raise_for_status()
            data = r.json() or {}
            tz = (data.get("timeZone") or "").strip()
            return tz or None
        except Exception:
            return None

    # -------------------- Calendars + Events --------------------
    def list_calendars(self) -> List[Dict[str, Any]]:
        url = f"{GRAPH}/me/calendars"
        out: List[Dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json() or {}
            out.extend(data.get("value", []) or [])
            url = data.get("@odata.nextLink")
        return out

    def create_calendar(self, name: str) -> Dict[str, Any]:
        body = {"name": name}
        r = _requests().post(f"{GRAPH}/me/calendars", headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json()

    def ensure_calendar(self, name: str) -> str:
        target = (name or "").strip().lower()
        if not target:
            raise ValueError("Calendar name is empty")
        for cal in self.list_calendars():
            n = (cal.get("name") or cal.get("displayName") or "").strip().lower()
            if n == target:
                return cal.get("id", "")
        created = self.create_calendar(name)
        return created.get("id", "")

    # -------------------- Calendar Sharing --------------------
    def list_calendar_permissions(self, calendar_id: str) -> List[Dict[str, Any]]:
        url = f"{GRAPH}/me/calendars/{calendar_id}/calendarPermissions"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json().get("value", [])

    def ensure_calendar_permission(self, calendar_id: str, email: str, role: str = "write") -> Dict[str, Any]:
        """Ensure a calendar permission exists for an external email with the given role.

        role: one of Graph accepted roles: read | write | limitedRead | freeBusyRead | delegateWithoutPrivateEventAccess | delegateWithPrivateEventAccess
        """
        perms = self.list_calendar_permissions(calendar_id)
        # Best-effort match by address
        for p in perms:
            em = ((p.get("emailAddress") or {}).get("address") or "").strip().lower()
            if em == (email or "").strip().lower():
                # Update if role differs
                cur = (p.get("role") or "").strip()
                if cur.lower() != role.strip().lower():
                    pid = p.get("id")
                    if pid:
                        body = {"role": role}
                        rr = _requests().patch(f"{GRAPH}/me/calendars/{calendar_id}/calendarPermissions/{pid}", headers=self._headers(), json=body)
                        rr.raise_for_status()
                        return rr.json() if rr.text else {}
                return p
        body = {"emailAddress": {"address": email}, "role": role}
        r = _requests().post(f"{GRAPH}/me/calendars/{calendar_id}/calendarPermissions", headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json()

    def update_event_location(
        self,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        location_str: Optional[str] = None,
        location_obj: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Patch the location of an event or series master.

        If calendar_id or calendar_name is provided, scopes the event under that calendar; otherwise uses /me/events/{id}.
        location_str is parsed via _parse_location; location_obj may be passed directly.
        Returns the updated event JSON (if any body is returned).
        """
        cal_id = calendar_id
        if not cal_id and calendar_name:
            cal_id = self.get_calendar_id_by_name(calendar_name)
        if not (location_obj or (location_str and location_str.strip())):
            raise ValueError("Must provide location_str or location_obj")
        loc = location_obj or self._parse_location(str(location_str))
        endpoint = f"{GRAPH}/me/events/{event_id}" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/events/{event_id}"
        body = {"location": loc}
        r = _requests().patch(endpoint, headers=self._headers(), json=body)
        r.raise_for_status()
        return r.json() if r.text else {}

    def update_event_reminder(
        self,
        *,
        event_id: str,
        calendar_id: Optional[str] = None,
        calendar_name: Optional[str] = None,
        is_on: bool = False,
        minutes_before_start: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Patch event reminder fields (isReminderOn, reminderMinutesBeforeStart).

        If calendar_id or calendar_name provided, scopes the request to that calendar.
        Returns the updated event JSON when available.
        """
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
        self,
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
        """Patch selected event fields in one request.

        Supported fields:
          - categories: List[str]
          - show_as: one of free|tentative|busy|oof|workingElsewhere|unknown
          - sensitivity: one of normal|personal|private|confidential
          - is_reminder_on: bool
          - reminder_minutes: int

        If calendar_id or calendar_name provided, scopes to that calendar.
        """
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
        self,
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

    def get_calendar_id_by_name(self, name: str) -> Optional[str]:
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

    def list_events_in_range(self, *, calendar_id: Optional[str] = None, calendar_name: Optional[str] = None, start_iso: str, end_iso: str, subject_filter: Optional[str] = None, top: int = 50) -> List[Dict[str, Any]]:
        """List events for a calendar within [start_iso, end_iso].

        Uses calendarView which expands recurring series. Optional subject_filter
        performs a client-side case-insensitive match.
        """
        cal_id = calendar_id or (self.get_calendar_id_by_name(calendar_name or "") if calendar_name else None)
        endpoint = f"{GRAPH}/me/calendarView" if not cal_id else f"{GRAPH}/me/calendars/{cal_id}/calendarView"
        # calendarView requires startDateTime/endDateTime query params
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

    def _resolve_tz(self, tz: Optional[str]) -> str:
        # Prefer provided tz; else mailbox setting; else a sensible default (America/Toronto)
        if tz and tz.strip():
            return tz.strip()
        mbx = self.get_mailbox_timezone()
        if mbx:
            return mbx
        # Fallback to Eastern (US & Canada) — Toronto
        return "America/Toronto"

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
            payload["location"] = self._parse_location(location)
        if all_day:
            # For all-day events, Graph expects date-only in local tz.
            # Caller should pass start/end ISO at midnight; we keep as-is here.
            payload["isAllDay"] = True
        # Disable reminders when requested
        if no_reminder:
            payload["isReminderOn"] = False
        if reminder_minutes is not None:
            try:
                payload["isReminderOn"] = True
                payload["reminderMinutesBeforeStart"] = int(reminder_minutes)
            except Exception:
                pass
        r = _requests().post(endpoint, headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

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

        # Map repeat to Graph recurrence pattern
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

        # Recurrence range
        rng: Dict[str, Any] = {"type": "endDate" if range_until else ("numbered" if count else "noEnd"), "startDate": range_start_date}
        if range_until:
            rng["endDate"] = range_until
        if count:
            rng["numberOfOccurrences"] = int(count)

        # For recurring, start/end require a full datetime; build using start_date + times
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
            payload["location"] = self._parse_location(location)

        # Disable reminders when requested
        if no_reminder:
            payload["isReminderOn"] = False
        if reminder_minutes is not None:
            try:
                payload["isReminderOn"] = True
                payload["reminderMinutesBeforeStart"] = int(reminder_minutes)
            except Exception:
                pass
        r = _requests().post(endpoint, headers=self._headers(), json=payload)
        r.raise_for_status()
        series = r.json()

        # Apply exclusions by deleting matching instances
        if exdates:
            try:
                sid = series.get("id")
                if sid:
                    self._apply_exdate_deletions(cal_id, sid, exdates, tz_final, rng)
            except Exception:
                # Non-fatal; series already created
                pass
        return series

    def _parse_location(self, loc: str) -> Dict[str, Any]:
        """Parse a location string into Outlook location with structured address when possible.

        Supported patterns (heuristic):
          - "Name (street, city, state POSTAL)"
          - "Name - Room at Facility street, city, state POSTAL"
          - "Name at Facility street, city, state POSTAL"
          - "street, city, state POSTAL" (address only)
        Falls back to displayName-only when not parseable.
        """
        disp = (loc or "").strip()
        out: Dict[str, Any] = {"displayName": disp}

        def _split_name_and_addr(s: str) -> Tuple[str, str]:
            # 1) Parentheses pattern: Name (addr)
            if "(" in s and ")" in s:
                try:
                    nm, rest = s.split("(", 1)
                    addr = rest.rsplit(")", 1)[0]
                    return nm.strip(), addr.strip()
                except Exception:
                    pass
            # 2) Use the last " at " segment as address delimiter
            if " at " in s:
                head, addr = s.rsplit(" at ", 1)
                return head.strip(), addr.strip()
            # 3) Try to find start of address by first occurrence of a number (street number)
            import re as _re
            m = _re.search(r"\b\d+\b", s)
            if m:
                return s[:m.start()].strip(), s[m.start():].strip()
            # 4) No delimiter; treat whole as name, no address
            return s.strip(), ""

        def _parse_addr(addr: str) -> Dict[str, Any]:
            # Expect comma-separated: street, city, state POSTAL [country]
            parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
            street = city = state = postal = country = None
            if parts:
                street = parts[0]
            if len(parts) == 2:
                # parts[1] likely 'STATE POSTAL'; attempt to extract state/postal
                tail = parts[1]
                toks = tail.split()
                import re as _re
                if len(toks) >= 2 and _re.match(r"^[A-Z]{2}$", toks[0]) and _re.match(r"^[A-Z][0-9][A-Z]$|^[A-Z][0-9][A-Z]\s[0-9][A-Z][0-9]$", (" ".join(toks[1:])).upper()):
                    state = toks[0]
                    # reconstruct postal (handle split)
                    rest = " ".join(toks[1:]).upper()
                    mpc = _re.search(r"[A-Z][0-9][A-Z]\s?[0-9][A-Z][0-9]", rest)
                    if mpc:
                        postal = rest[mpc.start():mpc.end()].replace(" ", " ")
                    # Try to pull city from end of parts[0]
                    cand = parts[0].strip()
                    words = [w for w in cand.split() if w]
                    # take last two words if likely city (titlecase, no digits), else last one
                    def is_word_city(w: str) -> bool:
                        return any(ch.isalpha() for ch in w) and not any(ch.isdigit() for ch in w)
                    city = None
                    if len(words) >= 2 and is_word_city(words[-1]) and is_word_city(words[-2]):
                        city = f"{words[-2]} {words[-1]}"
                        street = " ".join(words[:-2]) or street
                    elif len(words) >= 1 and is_word_city(words[-1]):
                        city = words[-1]
                        street = " ".join(words[:-1]) or street
                else:
                    # Unknown tokenization; treat as city blob
                    city = parts[1]
            if len(parts) >= 3:
                city = parts[-2]
                tail = parts[-1]
                toks = tail.split()
                # Try Canadian postal code (e.g., A1A 1A1) possibly split in two tokens
                import re as _re
                canada_pc = None
                if len(toks) >= 2:
                    pair = (toks[-2] + " " + toks[-1]).upper()
                    if _re.match(r"^[A-Z][0-9][A-Z]\s[0-9][A-Z][0-9]$", pair):
                        canada_pc = pair
                        toks = toks[:-2]  # remaining tokens may include province
                if canada_pc:
                    postal = canada_pc
                for t in toks:
                    tt = t.strip().strip(",")
                    if len(tt) == 2 and tt.isalpha():
                        state = tt
                if not postal:
                    # Fallback: pick the last token with a digit as postal
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

        # Build final location payload
        loc_obj: Dict[str, Any] = {"displayName": name or disp}
        if addr_obj:
            loc_obj["address"] = addr_obj
        return loc_obj

    def _apply_exdate_deletions(
        self,
        calendar_id: Optional[str],
        series_id: str,
        exdates: List[str],
        tz: str,
        rng: Dict[str, Any],
    ) -> None:
        # Query instances for an expanded window around the specified range
        # Build a conservative window (startDateTime, endDateTime)
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
                rr = _requests().delete(del_url, headers=self._headers())
                # Best-effort; ignore failures
                _ = rr.status_code

    # -------------------- Categories (labels) --------------------
    def list_labels(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("categories", ttl)
            if isinstance(cached, list):
                cats = cached
            else:
                r = _requests().get(f"{GRAPH}/me/outlook/masterCategories", headers=self._headers())
                r.raise_for_status()
                cats = r.json().get("value", [])
                self.cfg_put_json("categories", cats)
        else:
            r = _requests().get(f"{GRAPH}/me/outlook/masterCategories", headers=self._headers())
            r.raise_for_status()
            cats = r.json().get("value", [])
        # Normalize to Gmail-like fields
        out = []
        for c in cats:
            entry = {
                "id": c.get("id"),
                "name": c.get("displayName"),
                # Outlook has enum color; keep raw
                "color": {"name": c.get("color")},
                "type": "user",
                # No per-label visibility settings in Outlook; leave unset
            }
            out.append(entry)
        return out

    def create_label(self, name: str, color: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        body = {"displayName": name}
        if color and isinstance(color, dict) and color.get("name"):
            body["color"] = color.get("name")
        r = _requests().post(f"{GRAPH}/me/outlook/masterCategories", headers=self._headers(), json=body)
        r.raise_for_status()
        c = r.json()
        return {"id": c.get("id"), "name": c.get("displayName")}

    def update_label(self, label_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
        # Update by ID or by displayName; Graph requires ID
        payload: Dict[str, Any] = {}
        if body.get("name"):
            payload["displayName"] = body["name"]
        if isinstance(body.get("color"), dict) and body["color"].get("name"):
            payload["color"] = body["color"]["name"]
        if not payload:
            return {}
        r = _requests().patch(f"{GRAPH}/me/outlook/masterCategories/{label_id}", headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json() if r.text else {}

    def delete_label(self, label_id: str) -> None:
        r = _requests().delete(f"{GRAPH}/me/outlook/masterCategories/{label_id}", headers=self._headers())
        r.raise_for_status()

    def get_label_id_map(self) -> Dict[str, str]:
        return {l.get("name", ""): l.get("id", "") for l in self.list_labels()}

    def ensure_label(self, name: str, **kwargs: Any) -> str:
        m = self.get_label_id_map()
        if name in m:
            return m[name]
        created = self.create_label(name, **kwargs)
        return created.get("id", "")

    # -------------------- Rules (filters) --------------------
    def list_filters(self, use_cache: bool = False, ttl: int = 300) -> List[Dict[str, Any]]:
        if use_cache:
            cached = self.cfg_get_json("rules_inbox", ttl)
            if isinstance(cached, list):
                rules = cached
            else:
                r = _requests().get(f"{GRAPH}/me/mailFolders/inbox/messageRules", headers=self._headers())
                r.raise_for_status()
                rules = r.json().get("value", [])
                self.cfg_put_json("rules_inbox", rules)
        else:
            r = _requests().get(f"{GRAPH}/me/mailFolders/inbox/messageRules", headers=self._headers())
            r.raise_for_status()
            rules = r.json().get("value", [])
        # Map to Gmail-like structure
        mapped: List[Dict[str, Any]] = []
        for ru in rules:
            cond = ru.get("conditions", {}) or {}
            act = ru.get("actions", {}) or {}
            crit: Dict[str, Any] = {}
            if cond.get("senderContains"):
                crit["from"] = " OR ".join(cond["senderContains"])  # approximate
            if cond.get("recipientContains"):
                crit["to"] = " OR ".join(cond["recipientContains"])  # approximate
            if cond.get("subjectContains"):
                crit["subject"] = " OR ".join(cond["subjectContains"])
            action: Dict[str, Any] = {}
            if act.get("assignCategories"):
                action["addLabelIds"] = act["assignCategories"]
            if act.get("forwardTo"):
                action["forward"] = ",".join([a.get("emailAddress", {}).get("address", "") for a in act["forwardTo"]])
            if act.get("moveToFolder"):
                action["moveToFolderId"] = act.get("moveToFolder")
            mapped.append({"id": ru.get("id"), "criteria": crit, "action": action})
        return mapped

    def create_filter(self, criteria: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
        # Map DSL to Outlook rule
        cond: Dict[str, Any] = {}
        if criteria.get("from"):
            cond["senderContains"] = [s.strip() for s in str(criteria["from"]).split("OR")]
        if criteria.get("to"):
            cond["recipientContains"] = [s.strip() for s in str(criteria["to"]).split("OR")]
        if criteria.get("subject"):
            cond["subjectContains"] = [s.strip() for s in str(criteria["subject"]).split("OR")]
        act: Dict[str, Any] = {}
        if action.get("addLabelIds"):
            act["assignCategories"] = action["addLabelIds"]
        if action.get("forward"):
            emails = [e.strip() for e in str(action["forward"]).split(",") if e.strip()]
            act["forwardTo"] = [{"emailAddress": {"address": e}} for e in emails]
        if action.get("moveToFolderId"):
            act["moveToFolder"] = action["moveToFolderId"]
        payload = {
            "displayName": f"Rule {int(time.time())}",
            "sequence": 1,
            "isEnabled": True,
            "conditions": cond,
            "actions": act,
            "stopProcessingRules": True,
        }
        r = _requests().post(f"{GRAPH}/me/mailFolders/inbox/messageRules", headers=self._headers(), json=payload)
        r.raise_for_status()
        return r.json()

    def delete_filter(self, filter_id: str) -> None:
        r = _requests().delete(f"{GRAPH}/me/mailFolders/inbox/messageRules/{filter_id}", headers=self._headers())
        r.raise_for_status()

    # -------------------- Messages (search + move + get) --------------------
    def search_inbox_messages(
        self,
        search_query: str,
        days: Optional[int] = None,
        top: int = 25,
        pages: int = 2,
        use_cache: bool = True,
        ttl: int = 300,
    ) -> List[str]:
        """Return message IDs in Inbox matching $search query, optional days filter.

        Uses Graph $search which matches from/subject/body. Optional days filter restricts by
        receivedDateTime >= now - days.
        """
        # Try cache
        if self.cache_dir and use_cache:
            import hashlib
            key = f"search_{hashlib.sha1(f'{search_query}|{top}|{pages}|{days}'.encode()).hexdigest()}"
            cached = self.cfg_get_json(key, ttl)
            if isinstance(cached, list):
                return [str(x) for x in cached]
        ids: List[str] = []
        base = f"{GRAPH}/me/mailFolders/inbox/messages"
        params = [f"$search=\"{search_query}\"", f"$top={int(top)}"]
        if days and int(days) > 0:
            import datetime as _dt
            start = _dt.datetime.utcnow() - _dt.timedelta(days=int(days))
            start_iso = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            params.append(f"$filter=receivedDateTime ge {start_iso}")
        url = base + "?" + "&".join(params)
        nxt = url
        for _ in range(max(1, int(pages))):
            r = _requests().get(nxt, headers=self._headers_search())
            r.raise_for_status()
            data = r.json()
            vals = data.get("value", [])
            for m in vals:
                mid = m.get("id")
                if mid:
                    ids.append(mid)
            nxt = data.get("@odata.nextLink")
            if not nxt:
                break
        if self.cache_dir and use_cache:
            try:
                self.cfg_put_json(key, ids)  # type: ignore[name-defined]
            except Exception:
                pass
        return ids

    def move_message(self, msg_id: str, dest_folder_id: str) -> None:
        body = {"destinationId": dest_folder_id}
        r = _requests().post(f"{GRAPH}/me/messages/{msg_id}/move", headers=self._headers(), json=body)
        r.raise_for_status()

    def get_message(self, msg_id: str, select_body: bool = True) -> Dict[str, Any]:
        sel = "$select=subject,receivedDateTime,from,bodyPreview" + (",body" if select_body else "")
        url = f"{GRAPH}/me/messages/{msg_id}?{sel}"
        r = _requests().get(url, headers=self._headers())
        r.raise_for_status()
        return r.json()

    # -------------------- Events (delete) --------------------
    def delete_event(self, event_id: str, calendar_id: Optional[str] = None) -> None:
        base = f"{GRAPH}/me/events/{event_id}" if not calendar_id else f"{GRAPH}/me/calendars/{calendar_id}/events/{event_id}"
        r = _requests().delete(base, headers=self._headers())
        # Consider 204 No Content as success
        if r.status_code not in (200, 202, 204):
            r.raise_for_status()

    # -------------------- Folders --------------------
    def list_folders(self) -> List[Dict[str, Any]]:
        url = f"{GRAPH}/me/mailFolders"
        out: List[Dict[str, Any]] = []
        while url:
            r = _requests().get(url, headers=self._headers())
            r.raise_for_status()
            data = r.json()
            out.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        return out

    def get_folder_id_map(self) -> Dict[str, str]:
        # Map displayName to id for top-level folders
        return {f.get("displayName", ""): f.get("id", "") for f in self.list_folders()}

    def ensure_folder(self, name: str) -> str:
        m = self.get_folder_id_map()
        if name in m and m[name]:
            return m[name]
        body = {"displayName": name}
        # Try to find by listing first to avoid 409s
        m0 = self.get_folder_id_map()
        if name in m0 and m0[name]:
            return m0[name]
        # Some tenants disallow creating at root; try special well-known root IDs
        for endpoint in [f"{GRAPH}/me/mailFolders", f"{GRAPH}/me/mailFolders/Inbox/childFolders"]:
            r = _requests().post(endpoint, headers=self._headers(), json=body)
            if r.status_code == 409:
                m2 = self.get_folder_id_map()
                if name in m2 and m2[name]:
                    return m2[name]
            if 200 <= r.status_code < 300:
                f = r.json()
                return f.get("id", "")
        r.raise_for_status()
        f = r.json()
        return f.get("id", "")

    def list_all_folders(self, ttl: int = 600, clear_cache: bool = False) -> List[Dict[str, Any]]:
        """Return all folders (shallow pagination), including parent relationships.

        Builds a flat list by traversing childFolders for each discovered folder.
        """
        if clear_cache:
            self.cfg_clear()
        cached = self.cfg_get_json("folders_all", ttl)
        if isinstance(cached, list):
            return cached  # type: ignore[return-value]
        all_folders: Dict[str, Dict[str, Any]] = {}
        # Seed with top-level
        roots = self.list_folders()
        for f in roots:
            if f.get("id"):
                all_folders[f["id"]] = f
        # BFS over children
        queue = list(all_folders.keys())
        while queue:
            fid = queue.pop(0)
            r = _requests().get(f"{GRAPH}/me/mailFolders/{fid}/childFolders", headers=self._headers())
            r.raise_for_status()
            for ch in r.json().get("value", []):
                cid = ch.get("id")
                if cid and cid not in all_folders:
                    all_folders[cid] = ch
                    queue.append(cid)
        vals = list(all_folders.values())
        self.cfg_put_json("folders_all", vals)
        return vals

    def get_folder_path_map(self, ttl: int = 600, clear_cache: bool = False) -> Dict[str, str]:
        """Map full path (Parent/Child/Sub) to folder id."""
        folders = self.list_all_folders(ttl=ttl, clear_cache=clear_cache)
        by_id = {f.get("id"): f for f in folders}
        # Some Graph responses provide parentFolderId
        parent = {fid: f.get("parentFolderId") for fid, f in by_id.items()}
        name = {fid: (f.get("displayName") or "") for fid, f in by_id.items()}
        path_map: Dict[str, str] = {}
        cache: Dict[str, str] = {}

        def build_path(fid: str) -> str:
            if fid in cache:
                return cache[fid]
            parts = []
            cur = fid
            seen = set()
            while cur and cur in name and cur not in seen:
                seen.add(cur)
                parts.append(name[cur])
                cur = parent.get(cur)
            parts.reverse()
            p = "/".join([p for p in parts if p])
            cache[fid] = p
            return p

        for fid in by_id:
            p = build_path(fid)
            if p:
                path_map[p] = fid
        self.cfg_put_json("folders_path_map", path_map)
        return path_map

    def ensure_folder_path(self, path: str) -> str:
        """Ensure a nested folder path exists and return the leaf folder id.

        Path syntax: Parent/Child/Sub. Creates missing ancestors.
        """
        parts = [p for p in (path or "").split("/") if p]
        if not parts:
            raise ValueError("Folder path is empty")

        # Find or create top-level first
        parent_id: Optional[str] = None
        # Resolve top-level
        top_map = self.get_folder_id_map()
        if parts[0] in top_map and top_map[parts[0]]:
            parent_id = top_map[parts[0]]
        else:
            parent_id = self.ensure_folder(parts[0])

        # Walk remaining components
        for seg in parts[1:]:
            # List children under current parent
            r = _requests().get(f"{GRAPH}/me/mailFolders/{parent_id}/childFolders", headers=self._headers())
            r.raise_for_status()
            kids = r.json().get("value", [])
            kid_id = next((k.get("id") for k in kids if (k.get("displayName") == seg)), None)
            if kid_id:
                parent_id = kid_id
                continue
            # Create child
            body = {"displayName": seg}
            r2 = _requests().post(f"{GRAPH}/me/mailFolders/{parent_id}/childFolders", headers=self._headers(), json=body)
            r2.raise_for_status()
            created = r2.json()
            parent_id = created.get("id")
        return parent_id or ""

    # -------------------- Signatures (not available via Graph v1.0) --------------------
    def list_signatures(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("Outlook signatures are not available via Microsoft Graph API v1.0")

    def update_signature(self, signature_html: str) -> None:
        raise NotImplementedError("Outlook signatures cannot be updated programmatically via Graph v1.0")


def _normalize_days(days: List[str]) -> List[str]:
    # Map MO,TU,WE,TH,FR,SA,SU → Monday,Tuesday,... as Graph expects cases like 'monday'
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
    # Deduplicate preserving order
    seen = set()
    uniq = []
    for d in out:
        if d not in seen:
            uniq.append(d)
            seen.add(d)
    return uniq
