"""OutlookVerifyProcessor issues one calendarView query per calendar.

The processor used to query Graph once per config entry, each with the entry's
own window and a subject filter. It now fetches each calendar once over the
union window and narrows in memory. These tests pin both halves: the call
count, and that the report is byte-identical to the per-entry path.
"""
from __future__ import annotations

import datetime as dt
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from calendars.outlook_pipelines import (
    OutlookVerifyProcessor,
    OutlookVerifyRequest,
    OutlookVerifyRequestConsumer,
)


def _utc(iso: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(iso)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _occ(subject: str, start: str, end: str) -> dict[str, Any]:
    """A Graph calendarView occurrence as returned without a Prefer header (UTC)."""
    return {
        "subject": subject,
        "start": {"dateTime": f"{start}.0000000", "timeZone": "UTC"},
        "end": {"dateTime": f"{end}.0000000", "timeZone": "UTC"},
        "type": "occurrence",
        "seriesMasterId": f"sm-{subject}",
    }


@dataclass
class _GraphLikeService:
    """Fake honouring calendarView semantics: window overlap plus subject substring.

    Mirrors core.outlook.calendar.list_events_in_range, so a per-entry query
    and a wide query followed by in-memory narrowing can be compared.
    """

    by_calendar: dict[str | None, list[dict[str, Any]]]
    failing: set[str | None] = field(default_factory=set)
    calls: list[Any] = field(default_factory=list)

    def list_events_in_range(self, params: Any) -> list[dict[str, Any]]:
        self.calls.append(params)
        if params.calendar_name in self.failing:
            raise RuntimeError("Graph 503")
        lo, hi = _utc(params.start_iso), _utc(params.end_iso)
        out = []
        for ev in self.by_calendar.get(params.calendar_name, []):
            st = _utc(ev["start"]["dateTime"][:19])
            en = _utc(ev["end"]["dateTime"][:19])
            if st < hi and en > lo:
                out.append(ev)
        if params.subject_filter:
            needle = params.subject_filter.lower()
            out = [ev for ev in out if needle in (ev.get("subject") or "").lower()]
        return out


_CONFIG = {
    "events": [
        # 1. present on its Monday (17:00 Toronto == 22:00 UTC) -> duplicate
        {"subject": "Swim", "repeat": "weekly", "byday": ["MO"], "start_time": "17:00",
         "end_time": "17:30", "range": {"start_date": "2025-01-06", "until": "2025-03-01"}},
        # 2. a matching Piano exists, but only BEFORE this entry's window -> missing
        {"subject": "Piano", "repeat": "weekly", "byday": ["TU"], "start_time": "16:00",
         "end_time": "17:00", "range": {"start_date": "2025-02-01", "until": "2025-02-28"}},
        # 3. subject substring match ("Art" in "Art Class") -> duplicate
        {"subject": "Art", "repeat": "weekly", "byday": ["TH"], "start_time": "10:00",
         "end_time": "11:00", "range": {"start_date": "2025-01-01", "until": "2025-01-31"}},
        # 4. open-ended series on another calendar -> duplicate
        {"subject": "Yoga", "repeat": "weekly", "byday": ["WE"], "start_time": "09:00",
         "end_time": "10:00", "calendar": "Family", "range": {"start_date": "2025-01-06"}},
        # 5. calendar whose listing fails -> error line, neither duplicate nor missing
        {"subject": "Chess", "repeat": "weekly", "byday": ["FR"], "start_time": "18:00",
         "end_time": "19:00", "calendar": "Broken", "range": {"start_date": "2025-01-03", "until": "2025-01-31"}},
        {"subject": "Go", "repeat": "weekly", "byday": ["FR"], "start_time": "19:00",
         "end_time": "20:00", "calendar": "Broken", "range": {"start_date": "2025-01-03", "until": "2025-01-31"}},
        # 7. weekly with no window -> counted, no log line, no query
        {"subject": "Floating", "repeat": "weekly", "byday": ["MO"]},
        # 8. not weekly -> ignored entirely
        {"subject": "Dentist", "start": "2025-01-09T09:00:00", "end": "2025-01-09T10:00:00"},
    ]
}

_EVENTS = {
    None: [
        _occ("Swim", "2025-01-06T22:00:00", "2025-01-06T22:30:00"),
        _occ("Piano", "2025-01-07T21:00:00", "2025-01-07T22:00:00"),
        _occ("Art Class", "2025-01-09T15:00:00", "2025-01-09T16:00:00"),
    ],
    "Family": [_occ("Yoga", "2025-01-15T14:00:00", "2025-01-15T15:00:00")],
}

# Captured from the per-entry implementation (one query per entry) on this fixture.
_EXPECTED_LOGS = [
    "[1] duplicate: Swim MO 17:00-17:30 in '<primary>'",
    "[2] missing:   Piano TU 16:00-17:00 in '<primary>'",
    "[3] duplicate: Art TH 10:00-11:00 in '<primary>'",
    "[4] duplicate: Yoga WE 09:00-10:00 in 'Family'",
    "[5] Unable to list events for 'Chess': Graph 503",
    "[6] Unable to list events for 'Go': Graph 503",
]


class TestOutlookVerifyBatching(unittest.TestCase):
    def _run(self, svc: _GraphLikeService):
        request = OutlookVerifyRequest(config_path=Path("cfg.yaml"), calendar=None, service=svc)
        processor = OutlookVerifyProcessor(config_loader=lambda _p: _CONFIG)
        return processor.process(OutlookVerifyRequestConsumer(request).consume())

    def test_report_matches_per_entry_path(self):
        env = self._run(_GraphLikeService(by_calendar=_EVENTS, failing={"Broken"}))

        self.assertTrue(env.ok(), env.diagnostics)
        self.assertEqual(env.payload.logs, _EXPECTED_LOGS)
        self.assertEqual(env.payload.total, 7)
        self.assertEqual(env.payload.duplicates, 3)
        self.assertEqual(env.payload.missing, 1)

    def test_one_query_per_calendar(self):
        svc = _GraphLikeService(by_calendar=_EVENTS, failing={"Broken"})
        self._run(svc)

        self.assertEqual(len(svc.calls), 3)
        self.assertEqual([c.calendar_name for c in svc.calls], [None, "Family", "Broken"])

    def test_primary_query_spans_union_of_entry_windows(self):
        svc = _GraphLikeService(by_calendar=_EVENTS)
        self._run(svc)

        primary = svc.calls[0]
        self.assertEqual(primary.start_iso, "2025-01-01T00:00:00")
        self.assertEqual(primary.end_iso, "2025-03-01T23:59:59")
        self.assertIsNone(primary.subject_filter)

    def test_no_queries_when_nothing_to_verify(self):
        svc = _GraphLikeService(by_calendar=_EVENTS)
        request = OutlookVerifyRequest(config_path=Path("cfg.yaml"), calendar=None, service=svc)
        processor = OutlookVerifyProcessor(config_loader=lambda _p: {"events": [_CONFIG["events"][-1]]})
        env = processor.process(OutlookVerifyRequestConsumer(request).consume())

        self.assertTrue(env.ok(), env.diagnostics)
        self.assertEqual(svc.calls, [])
        self.assertEqual(env.payload.logs, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
