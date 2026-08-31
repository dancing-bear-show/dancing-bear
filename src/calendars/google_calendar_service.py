"""Thin wrapper over the Google Calendar API (calendar/v3).

Lazy-imports googleapiclient so the module loads cleanly even when the
optional Google dependencies are not installed.  Call ``ensure_google_api()``
from ``mail.gmail_api`` before constructing a client.

This is an API seam — minimal surface, no business logic.
"""
from __future__ import annotations

from typing import Any


class GoogleCalendarService:
    """Minimal calendar/v3 client, dependency-injected via ``credentials``.

    Parameters
    ----------
    credentials
        A ``google.oauth2.credentials.Credentials`` object that has been
        authenticated with the ``https://www.googleapis.com/auth/calendar`` scope.

    Usage::

        from mail.gmail_api import GmailClient, ensure_google_api
        from calendars.google_calendar_service import GoogleCalendarService

        ensure_google_api()
        client = GmailClient(credentials_path="...", token_path="...")
        client.authenticate()
        svc = GoogleCalendarService(client.creds)
        events = svc.list_events("primary", "2026-01-01T00:00:00Z", "2026-02-01T00:00:00Z")
    """

    def __init__(self, credentials: Any) -> None:
        # Lazy import — googleapiclient is optional
        try:
            from googleapiclient.discovery import build
        except Exception as exc:  # nosec B110 - optional dependency guard
            raise RuntimeError(
                "Google API libraries not installed. "
                "Run `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib`."
            ) from exc
        self._service = build("calendar", "v3", credentials=credentials)

    # ------------------------------------------------------------------
    # Public API surface
    # ------------------------------------------------------------------

    def list_events(
        self,
        calendar_id: str,
        time_min: str,
        time_max: str,
    ) -> list[dict[str, Any]]:
        """Return all events in [time_min, time_max) for calendar_id.

        Parameters
        ----------
        calendar_id
            Calendar identifier (e.g. ``"primary"`` or a full calendar email).
        time_min, time_max
            RFC 3339 timestamps (e.g. ``"2026-01-01T00:00:00Z"``).

        Returns a flat list of event resource dicts — pagination is handled
        internally with ``nextPageToken``.
        """
        events: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "calendarId": calendar_id,
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": False,
            }
            if page_token:
                kwargs["pageToken"] = page_token
            response = self._service.events().list(**kwargs).execute()
            items = response.get("items") or []
            events.extend(items)
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return events

    def insert_event(
        self,
        calendar_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        """Insert a new event and return the created resource dict.

        Parameters
        ----------
        calendar_id
            Calendar identifier.
        body
            A calendar/v3 Event resource dict (``summary``, ``start``, ``end``,
            ``recurrence``, etc.).
        """
        return self._service.events().insert(calendarId=calendar_id, body=body).execute()

    def get_calendar_timezone(self, calendar_id: str) -> str | None:
        """Return the IANA timezone of the given calendar, or None on failure.

        Uses the Calendars resource (``calendars.get``) which returns a
        ``timeZone`` field.  Returns None rather than raising so the caller can
        fall back gracefully.
        """
        try:
            resource = self._service.calendars().get(calendarId=calendar_id).execute()
            tz = (resource.get("timeZone") or "").strip()
            return tz or None
        except Exception:  # nosec B110 - best-effort timezone lookup; caller falls back
            return None


__all__ = ["GoogleCalendarService"]
