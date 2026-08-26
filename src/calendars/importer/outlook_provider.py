"""Outlook implementation of CalendarProvider.

Production implementor of the CalendarProvider Protocol backed by the
Microsoft Graph API via OutlookCalendarMixin.  Dependency-injected so
tests can pass a fake service without touching the network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from calendars.gmail_pipelines import CalendarEvent
from calendars.outlook_pipelines.export import (
    _SUPPORTED_PATTERNS,
    _convert_one_off,
    _reverse_recurrence,
)
from core.outlook.models import EventCreationParams, RecurringEventCreationParams, ListEventsRequest


def _collect_exdates(occurrences: list[dict[str, Any]]) -> list[str]:
    """Return date-only strings for cancelled / exception occurrences."""
    exdates: list[str] = []
    for occ in occurrences:
        if occ.get("isCancelled") or (occ.get("type") or "").lower() == "exceptionoccurrence":
            st = (
                occ.get("originalStart")
                or (occ.get("start") or {}).get("dateTime")
                or ""
            )
            date_only = st.split("T", 1)[0] if "T" in st else st
            if date_only:
                exdates.append(date_only)
    return exdates


@dataclass
class OutlookCalendarProvider:
    """Production CalendarProvider backed by Microsoft Graph.

    Satisfies ``calendars.importer.base.CalendarProvider`` structurally —
    no inheritance needed because the protocol is @runtime_checkable and the
    two methods match its signature exactly.

    Constructor parameters
    ----------------------
    svc
        An Outlook service object exposing:
          - list_events_in_range(params: ListEventsRequest) -> list[dict]
          - get_event(event_id: str) -> dict | None
          - create_event(params: EventCreationParams) -> dict
          - create_recurring_event(params: RecurringEventCreationParams) -> dict
        (Any object satisfying those four methods is accepted — the real
        ``OutlookService`` or a test fake both work.)
    calendar_name
        Optional calendar name forwarded to every Graph query.  When None,
        queries target the default mailbox calendar.

    Attributes
    ----------
    skipped
        Records every event that could not be represented in CalendarEvent
        form. Each entry is a dict with at least a ``reason`` key. Callers
        may inspect this after ``list_events`` to see what was dropped; the
        list is reset on each call.
    """

    svc: Any
    calendar_name: str | None = None
    skipped: list[dict[str, Any]] = field(default_factory=list, init=False)

    # ------------------------------------------------------------------
    # Protocol methods
    # ------------------------------------------------------------------

    def list_events(self, date_range: tuple[str, str]) -> list[CalendarEvent]:
        """Return CalendarEvent objects for events in the given ISO date range.

        Recurring series masters are reversed into recurrence-bearing
        CalendarEvent objects (repeat/byday/interval/range populated).  Events
        whose recurrence pattern cannot be represented (relativeMonthly,
        absoluteYearly, relativeYearly) are skipped and recorded in
        ``self.skipped`` — they are never returned in a degraded form.

        Parameters
        ----------
        date_range
            (start_iso, end_iso) strings in ISO format (YYYY-MM-DD or full
            ISO-8601 with time).
        """
        self.skipped = []
        start_iso, end_iso = date_range
        raw_events = self.svc.list_events_in_range(
            ListEventsRequest(start_iso=start_iso, end_iso=end_iso, calendar_name=self.calendar_name)
        )

        one_offs, by_master = self._partition_events(raw_events or [])

        results: list[CalendarEvent] = []
        for ev in one_offs:
            ce = self._graph_one_off_to_event(ev)
            if ce is not None:
                results.append(ce)

        seen_masters: set[str] = set()
        for master_id, occurrences in by_master.items():
            if master_id in seen_masters:
                continue
            seen_masters.add(master_id)
            ce = self._process_series(master_id, occurrences)
            if ce is not None:
                results.append(ce)

        return results

    @staticmethod
    def _partition_events(
        raw_events: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
        """Split raw Graph events into one-offs and by-series-master buckets."""
        one_offs: list[dict[str, Any]] = []
        by_master: dict[str, list[dict[str, Any]]] = {}
        for ev in raw_events:
            etype = (ev.get("type") or "").lower()
            if etype == "singleinstance" or not ev.get("seriesMasterId"):
                one_offs.append(ev)
            else:
                mid = ev.get("seriesMasterId") or ""
                if mid:
                    by_master.setdefault(mid, []).append(ev)
        return one_offs, by_master

    def _process_series(
        self, master_id: str, occurrences: list[dict[str, Any]]
    ) -> CalendarEvent | None:
        """Resolve one recurring series to a CalendarEvent, or record a skip."""
        rep = occurrences[0] if occurrences else {}
        subject = rep.get("subject") or ""

        master = self.svc.get_event(master_id)
        if master is None:
            self.skipped.append({"seriesMasterId": master_id, "subject": subject, "reason": "orphaned_master"})
            return None

        plan_ev = self._reverse_series_master(master_id, subject, master)
        if plan_ev is None:
            return None

        exdates = _collect_exdates(occurrences)
        if exdates:
            plan_ev["exdates"] = sorted(set(exdates))

        return self._plan_ev_to_recurring_event(plan_ev, master)

    def _reverse_series_master(
        self, master_id: str, subject: str, master: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Validate and reverse a series master into a plan dict, or record skip."""
        recurrence = master.get("recurrence") or {}
        pattern = recurrence.get("pattern") or {}
        ptype_raw = pattern.get("type") or ""
        ptype = ptype_raw.lower()

        if ptype not in _SUPPORTED_PATTERNS:
            self.skipped.append({
                "seriesMasterId": master_id,
                "subject": subject,
                "pattern_type": ptype_raw,
                "reason": "unsupported_pattern",
            })
            return None

        if "interval" not in pattern:
            self.skipped.append({"seriesMasterId": master_id, "subject": subject, "reason": "missing_interval"})
            return None

        try:
            plan_ev = _reverse_recurrence(master, self.svc)
        except ValueError as exc:
            self.skipped.append({"seriesMasterId": master_id, "subject": subject, "reason": str(exc)})
            return None

        if plan_ev is None:
            self.skipped.append({
                "seriesMasterId": master_id,
                "subject": subject,
                "pattern_type": ptype_raw,
                "reason": "unsupported_pattern",
            })
            return None

        return plan_ev

    def add_event(self, event: CalendarEvent) -> CalendarEvent:
        """Add a new event and return the persisted CalendarEvent.

        When ``event.repeat`` is set the Graph ``create_recurring_event``
        path is taken; otherwise ``create_event`` is used.
        """
        if event.repeat:
            return self._add_recurring(event)
        return self._add_single(event)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _graph_one_off_to_event(self, ev: dict[str, Any]) -> CalendarEvent | None:
        """Map a Graph single-instance event dict to CalendarEvent."""
        plan = _convert_one_off(ev, self.svc)
        # Strip internal tz-source marker (used by export pipeline, not plan schema)
        plan.pop("_tz_source", None)
        ev_id = ev.get("id") or ""
        subject = plan.get("subject") or ev.get("subject") or ""
        start = plan.get("start") or ""
        end = plan.get("end") or ""
        cal = ev.get("calendar") or self.calendar_name or ""
        return CalendarEvent(
            id=ev_id,
            subject=subject,
            start=start,
            end=end,
            calendar=cal,
            tz=plan.get("tz"),
            location=plan.get("location"),
        )

    def _plan_ev_to_recurring_event(
        self, plan_ev: dict[str, Any], master: dict[str, Any]
    ) -> CalendarEvent:
        """Convert a reversed plan dict into a CalendarEvent."""
        # Strip internal marker
        plan_ev.pop("_tz_source", None)
        ev_id = master.get("id") or ""
        subject = plan_ev.get("subject") or master.get("subject") or ""
        # Recurring events carry start_time/end_time, not absolute start/end
        start = plan_ev.get("start") or plan_ev.get("start_time") or ""
        end = plan_ev.get("end") or plan_ev.get("end_time") or ""
        cal = master.get("calendar") or self.calendar_name or ""
        rng = plan_ev.get("range")
        return CalendarEvent(
            id=ev_id,
            subject=subject,
            start=start,
            end=end,
            calendar=cal,
            tz=plan_ev.get("tz"),
            location=plan_ev.get("location"),
            repeat=plan_ev.get("repeat"),
            interval=plan_ev.get("interval"),
            byday=list(plan_ev.get("byday") or []),
            range=rng,
            start_time=plan_ev.get("start_time"),
            end_time=plan_ev.get("end_time"),
            exdates=list(plan_ev.get("exdates") or []),
            count=plan_ev.get("count"),
        )

    def _add_single(self, event: CalendarEvent) -> CalendarEvent:
        """Create a one-time Graph event and return a CalendarEvent."""
        params = EventCreationParams(
            subject=event.subject,
            start_iso=event.start,
            end_iso=event.end,
            tz=event.tz,
            location=event.location,
            calendar_name=self.calendar_name,
        )
        result = self.svc.create_event(params)
        return CalendarEvent(
            id=result.get("id") or "",
            subject=result.get("subject") or event.subject,
            start=event.start,
            end=event.end,
            calendar=self.calendar_name or "",
            tz=event.tz,
            location=event.location,
        )

    def _add_recurring(self, event: CalendarEvent) -> CalendarEvent:
        """Create a recurring Graph event series and return a CalendarEvent."""
        rng = event.range or {}
        params = RecurringEventCreationParams(
            subject=event.subject,
            start_time=event.start_time or event.start,
            end_time=event.end_time or event.end,
            repeat=event.repeat or "weekly",
            tz=event.tz,
            interval=event.interval or 1,
            byday=list(event.byday) if event.byday else None,
            range_start_date=rng.get("start_date"),
            range_until=rng.get("until"),
            count=event.count,
            location=event.location,
            exdates=list(event.exdates) if event.exdates else None,
            calendar_name=self.calendar_name,
        )
        result = self.svc.create_recurring_event(params)
        return CalendarEvent(
            id=result.get("id") or "",
            subject=result.get("subject") or event.subject,
            start=event.start,
            end=event.end,
            calendar=self.calendar_name or "",
            tz=event.tz,
            location=event.location,
            repeat=event.repeat,
            interval=event.interval,
            byday=list(event.byday),
            range=event.range,
            start_time=event.start_time,
            end_time=event.end_time,
            exdates=list(event.exdates),
            count=event.count,
        )


__all__ = ["OutlookCalendarProvider"]
