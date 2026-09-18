"""Gmail receipts pipeline for calendar assistant."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from core.pipeline import SafeProcessor
from core.text_utils import to_24h

from .gmail_service import GmailService
from .pipeline_base import (
    BaseProducer,
    GmailAuth,
    GmailServiceBuilderMixin,
    RequestConsumer,
    dedupe_events,
    parse_month,
    DAY_MAP,
)


# =============================================================================
# Receipt Parsing Patterns (module-level for reuse)
# =============================================================================

# Pattern: class name extraction - matches "Enrollment in <class> (# or ( or - or newline"
_RECEIPT_CLS_PAT = re.compile(
    r"Enrollment\s+in\s+(?P<cls>[a-z][a-z0-9 /+\-]+?)\s*(?:\(#|\(|-|\r|\n)", re.I
)
# Pattern: registrant name - "Registrant: <name>"
_RECEIPT_REG_PAT_1 = re.compile(
    r"Registrant:\s*(?:\r?\n\s*)?(?P<name>[a-z][a-z\s'\-]+)", re.I
)
# Pattern: registrant from order summary
_RECEIPT_REG_PAT_2 = re.compile(
    r"Order\s+Summary:\s*(?P<name>[a-z][a-z\s'\-]+?)\s+Enrollment\s+in", re.I
)
# Pattern: meeting date range
_RECEIPT_DATES_PAT = re.compile(
    r"Meeting\s+Dates:\s*From\s+(?P<m1>[A-Za-z]{3,9})\s+(?P<d1>\d{1,2}),\s*(?P<y1>\d{4})"
    r"\s+to\s+(?P<m2>[A-Za-z]{3,9})\s+(?P<d2>\d{1,2}),\s*(?P<y2>\d{4})",
    re.I,
)
# Pattern: weekly schedule
_RECEIPT_SCHED_PAT = re.compile(
    r"Each\s+(?P<day>Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
    r"\s+from\s+(?P<t1>\d{1,2}:\d{2}\s*(?:am|pm))\s+to\s+(?P<t2>\d{1,2}:\d{2}\s*(?:am|pm))",
    re.I,
)
# Pattern: location
_RECEIPT_LOC_PAT = re.compile(r"Location:\s*(?P<loc>.+)", re.I)



# =============================================================================
# Gmail Receipts Pipeline
# =============================================================================

@dataclass
class GmailReceiptsRequest:
    auth: GmailAuth
    query: str | None
    from_text: str | None
    days: int
    pages: int
    page_size: int
    calendar: str | None
    out_path: Path


GmailReceiptsRequestConsumer = RequestConsumer[GmailReceiptsRequest]


@dataclass
class GmailScanResult:
    document: dict[str, Sequence[dict[str, object]]]
    out_path: Path


class GmailReceiptsProcessor(
    GmailServiceBuilderMixin, SafeProcessor[GmailReceiptsRequest, GmailScanResult]
):
    _service_cls = GmailService

    def _process_safe(self, payload: GmailReceiptsRequest) -> GmailScanResult:
        svc = self._service_builder(payload.auth)
        query = GmailService.build_receipts_query(
            from_text=payload.from_text,
            days=payload.days,
            explicit=payload.query,
        )
        ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        if not ids:
            return GmailScanResult(document={"events": []}, out_path=payload.out_path)
        events = self._parse_receipts(svc, ids, payload.calendar)
        if not events:
            return GmailScanResult(document={"events": []}, out_path=payload.out_path)

        # Dedupe with child field included
        def key_fn(ev):
            return (
                ev.get("subject"),
                tuple(ev.get("byday") or []),
                ev.get("start_time"),
                ev.get("end_time"),
                (ev.get("range") or {}).get("start_date"),
                (ev.get("range") or {}).get("until"),
                ev.get("location"),
                ev.get("child"),
            )
        uniq = dedupe_events(events, key_fn)
        return GmailScanResult(document={"events": uniq}, out_path=payload.out_path)

    def _parse_receipts(self, svc, ids: list[str], calendar: str | None):
        events = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception:  # nosec B112 - skip unreadable messages
                continue
            ev = self._parse_single_receipt(text, calendar)
            if ev:
                events.append(ev)
        return events

    def _parse_single_receipt(
        self, text: str | None, calendar: str | None
    ) -> dict[str, Any] | None:
        """Parse a single receipt message and return an event dict or None."""
        text = text or ""
        m_cls = _RECEIPT_CLS_PAT.search(text)
        m_dates = _RECEIPT_DATES_PAT.search(text)
        m_sched = _RECEIPT_SCHED_PAT.search(text)
        if not (m_cls and m_dates and m_sched):
            return None

        date_range = self._parse_receipt_date_range(m_dates)
        if not date_range:
            return None

        m_loc = _RECEIPT_LOC_PAT.search(text)
        loc_hint = m_loc.group("loc") if m_loc else None
        loc = loc_hint.strip() if loc_hint else None

        ev: dict[str, Any] = {
            "calendar": calendar,
            "subject": self._normalize_subject(m_cls.group("cls"), loc_hint),
            "repeat": "weekly",
            "byday": [DAY_MAP[(m_sched.group("day") or "").lower()]],
            "start_time": to_24h(m_sched.group("t1")),
            "end_time": to_24h(m_sched.group("t2")),
            "range": date_range,
        }
        if loc:
            ev["location"] = loc

        child_first, child_full = self._extract_child_info(text)
        if child_first:
            ev["child"] = child_first
            ev["child_full"] = child_full
        return ev

    def _parse_receipt_date_range(self, m_dates) -> dict[str, str | None] | None:
        """Parse date range from regex match, return dict or None if invalid."""
        m1v = parse_month(m_dates.group("m1"))
        m2v = parse_month(m_dates.group("m2"))
        if not (m1v and m2v):
            return None
        d1, y1 = int(m_dates.group("d1")), int(m_dates.group("y1"))
        d2, y2 = int(m_dates.group("d2")), int(m_dates.group("y2"))
        return {
            "start_date": f"{y1:04d}-{m1v:02d}-{d1:02d}",
            "until": f"{y2:04d}-{m2v:02d}-{d2:02d}",
        }

    def _extract_child_info(self, text: str) -> tuple[str | None, str | None]:
        """Extract child first name and full name from receipt text."""
        m_reg = _RECEIPT_REG_PAT_1.search(text) or _RECEIPT_REG_PAT_2.search(text)
        if not m_reg:
            return None, None
        child_full = (m_reg.group("name") or "").strip()
        child_first = child_full.split()[0].title() if child_full else None
        return child_first, child_full

    def _normalize_subject(self, raw: str | None, loc_hint: str | None) -> str:
        """Normalize subject text using predefined rules."""
        base = (raw or "").strip().split(" - ", 1)[0].strip()
        lower = base.lower()

        # Handle swimming-related subjects
        if lower.startswith("swimmer ") or lower.startswith("swim kids"):
            result = base.title()
        # Handle chess subjects
        elif lower.startswith("chess") or lower == "c":
            result = "Chess"
        # Handle single-letter 's' with location context
        elif lower == "s":
            result = "Swimmer" if (loc_hint and "pool" in loc_hint.lower()) else "Sports"
        # Default: title case
        else:
            result = base.title()

        return result


class GmailScanProducer(BaseProducer):
    def _produce_success(self, payload: GmailScanResult, diagnostics: dict[str, Any] | None) -> None:
        from core.yamlio import dump_config

        dump_config(str(payload.out_path), payload.document)
        events = payload.document.get("events", [])
        self._writer.print(f"Wrote {len(events)} events to {payload.out_path}")
