"""Gmail pipeline components for calendar assistant.

Provides pipelines for scanning Gmail for receipts, classes, and sender analysis.
"""
from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.pipeline import SafeProcessor

from .gmail_service import GmailService
from .text_utils import to_24h, extract_email_address
from core.text_utils import html_to_text
from .constants import DAY_MAP
from .scan_common import (
    RANGE_PAT,
    CLASS_PAT,
    LOC_LABEL_PAT,
    FACILITIES,
    MONTH_MAP,
    DATE_RANGE_PAT,
    norm_time as _norm_time_common,
    infer_meta_from_text,
)
from .pipeline_base import (
    BaseProducer,
    GmailAuth,
    GmailServiceBuilder,
    RequestConsumer,
    dedupe_events,
    parse_month,
    DAY_TO_CODE,
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
    query: Optional[str]
    from_text: Optional[str]
    days: int
    pages: int
    page_size: int
    calendar: Optional[str]
    out_path: Path


GmailReceiptsRequestConsumer = RequestConsumer[GmailReceiptsRequest]


@dataclass
class GmailPlanResult:
    document: Dict[str, Sequence[Dict[str, object]]]
    out_path: Path


class GmailReceiptsProcessor(SafeProcessor[GmailReceiptsRequest, GmailPlanResult]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth, service_cls=GmailService)

    def _process_safe(self, payload: GmailReceiptsRequest) -> GmailPlanResult:
        svc = self._service_builder(payload.auth)
        query = GmailService.build_receipts_query(
            from_text=payload.from_text,
            days=payload.days,
            explicit=payload.query,
        )
        ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        if not ids:
            return GmailPlanResult(document={"events": []}, out_path=payload.out_path)
        events = self._parse_receipts(svc, ids, payload.calendar)
        if not events:
            return GmailPlanResult(document={"events": []}, out_path=payload.out_path)

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
        return GmailPlanResult(document={"events": uniq}, out_path=payload.out_path)

    def _parse_receipts(self, svc, ids: List[str], calendar: Optional[str]):
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
        self, text: Optional[str], calendar: Optional[str]
    ) -> Optional[Dict[str, Any]]:
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

        ev: Dict[str, Any] = {
            "calendar": calendar,
            "subject": self._normalize_subject(m_cls.group("cls"), loc_hint),
            "repeat": "weekly",
            "byday": [DAY_TO_CODE[(m_sched.group("day") or "").lower()]],
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

    def _parse_receipt_date_range(self, m_dates) -> Optional[Dict[str, str]]:
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

    def _extract_child_info(self, text: str) -> Tuple[Optional[str], Optional[str]]:
        """Extract child first name and full name from receipt text."""
        m_reg = _RECEIPT_REG_PAT_1.search(text) or _RECEIPT_REG_PAT_2.search(text)
        if not m_reg:
            return None, None
        child_full = (m_reg.group("name") or "").strip()
        child_first = child_full.split()[0].title() if child_full else None
        return child_first, child_full

    def _normalize_subject(self, raw: Optional[str], loc_hint: Optional[str]) -> str:
        base = (raw or "").strip().split(" - ", 1)[0].strip()
        lower = base.lower()
        if lower.startswith("swimmer "):
            return base.title()
        if lower.startswith("swim kids"):
            return base.title()
        if lower.startswith("chess"):
            return "Chess"
        if lower == "c":
            return "Chess"
        if lower == "s":
            if loc_hint and "pool" in loc_hint.lower():
                return "Swimmer"
            return "Sports"
        return base.title()


class GmailPlanProducer(BaseProducer):
    def _produce_success(self, payload: GmailPlanResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        from calendars.yamlio import dump_config

        dump_config(str(payload.out_path), payload.document)
        events = payload.document.get("events", [])
        print(f"Wrote {len(events)} events to {payload.out_path}")


# =============================================================================
# Gmail Scan Classes Pipeline
# =============================================================================

@dataclass
class GmailScanClassesRequest:
    auth: GmailAuth
    from_text: Optional[str]
    query: Optional[str]
    days: int
    pages: int
    page_size: int
    inbox_only: bool
    calendar: Optional[str]
    out_path: Optional[Path]


GmailScanClassesRequestConsumer = RequestConsumer[GmailScanClassesRequest]


@dataclass
class GmailScanClassesResult:
    events: List[Dict[str, Any]]
    message_count: int
    out_path: Optional[Path]


class GmailScanClassesProcessor(SafeProcessor[GmailScanClassesRequest, GmailScanClassesResult]):
    def __init__(self, service_builder=None) -> None:
        from .scan_common import MetaParserConfig

        self._service_builder = service_builder or self._default_service_builder
        self._day_map = DAY_MAP
        self._range_pat = RANGE_PAT
        self._month_map = MONTH_MAP
        self._meta_config = MetaParserConfig()

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def _process_safe(self, payload: GmailScanClassesRequest) -> GmailScanClassesResult:
        svc = self._service_builder(payload.auth)
        query = GmailService.build_query(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        )
        ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        if not ids:
            return GmailScanClassesResult(events=[], message_count=0, out_path=payload.out_path)
        extracted: List[Dict[str, Any]] = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception:  # nosec B112 - skip unreadable messages
                continue
            extracted.extend(self._extract_events(text, payload.calendar))
        events = dedupe_events(extracted)
        if not events:
            return GmailScanClassesResult(events=[], message_count=len(ids), out_path=payload.out_path)
        return GmailScanClassesResult(events=events, message_count=len(ids), out_path=payload.out_path)

    def _extract_events(self, message_text: str, calendar: Optional[str]) -> List[Dict[str, Any]]:
        plain = self._html_to_text(message_text)
        matches = list(self._range_pat.finditer(plain))
        if not matches:
            return []
        meta = self._infer_meta(plain)
        events: List[Dict[str, Any]] = []
        for match in matches:
            day_raw = (match.group("day") or "").lower()
            byday = [self._day_map.get(day_raw, day_raw[:2].upper())]
            start_time = self._norm_time(match.group("h1"), match.group("m1"), match.group("ampm1"))
            end_time = self._norm_time(match.group("h2"), match.group("m2"), match.group("ampm2"))
            ev: Dict[str, Any] = {
                "calendar": calendar,
                "subject": "Class",
                "repeat": "weekly",
                "byday": byday,
                "start_time": start_time,
                "end_time": end_time,
            }
            if meta.get("subject"):
                ev["subject"] = meta["subject"]
            if meta.get("location"):
                ev["location"] = meta["location"]
            if meta.get("range"):
                ev.setdefault("range", {}).update(meta["range"])
            events.append(ev)
        return events

    def _html_to_text(self, html: str) -> str:
        return html_to_text(html)

    def _norm_time(self, hour: str, minute: Optional[str], ampm: Optional[str]) -> str:
        return _norm_time_common(hour, minute, ampm)

    def _infer_meta(self, text: str) -> Dict[str, Any]:
        return infer_meta_from_text(text, config=self._meta_config)


class GmailScanClassesProducer(BaseProducer):
    def _produce_success(self, payload: GmailScanClassesResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        events = payload.events
        if not events:
            if payload.message_count:
                print("No schedule-like lines found in matching emails.")
            else:
                print("No matching messages found.")
            if not payload.out_path:
                print("Use --out plan.yaml to write YAML.")
            return
        print(f"Found {len(events)} candidate recurring class entries from {payload.message_count} messages.")
        if payload.out_path:
            from calendars.yamlio import dump_config

            dump_config(str(payload.out_path), {"events": events})
            print(f"Wrote plan to {payload.out_path}")
            return
        for ev in events:
            byday = ",".join(ev.get("byday") or [])
            print(f"- {byday} {ev.get('start_time')}-{ev.get('end_time')} calendar={ev.get('calendar') or '<default>'}")
        print("Use --out plan.yaml to write YAML.")


# =============================================================================
# Gmail Mail List Pipeline
# =============================================================================

@dataclass
class GmailMailListRequest:
    auth: GmailAuth
    query: Optional[str]
    from_text: Optional[str]
    days: int
    pages: int
    page_size: int
    inbox_only: bool


GmailMailListRequestConsumer = RequestConsumer[GmailMailListRequest]


@dataclass
class GmailMailListResult:
    messages: List[Dict[str, str]]


class GmailMailListProcessor(SafeProcessor[GmailMailListRequest, GmailMailListResult]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def _process_safe(self, payload: GmailMailListRequest) -> GmailMailListResult:
        svc = self._service_builder(payload.auth)
        query = GmailService.build_query(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        )
        ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        if not ids:
            return GmailMailListResult(messages=[])
        messages: List[Dict[str, str]] = []
        for mid in ids:
            try:
                text = svc.get_message_text(mid)
            except Exception as exc:
                messages.append({"id": mid, "snippet": f"<failed to fetch: {exc}>"})
                continue
            first_line = (text or "").splitlines()[0] if text else ""
            messages.append({"id": mid, "snippet": first_line[:100]})
        return GmailMailListResult(messages=messages)


class GmailMailListProducer(BaseProducer):
    def _produce_success(self, payload: GmailMailListResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        messages = payload.messages
        if not messages:
            print("No messages matched.")
            return
        for msg in messages:
            print(f"- {msg.get('id')} | {msg.get('snippet')}")
        print(f"Listed {len(messages)} Gmail message(s).")


# =============================================================================
# Gmail Sweep Top Senders Pipeline
# =============================================================================

@dataclass
class GmailSweepTopRequest:
    auth: GmailAuth
    query: Optional[str]
    from_text: Optional[str]
    days: int
    pages: int
    page_size: int
    inbox_only: bool
    top: int
    out_path: Optional[Path]


GmailSweepTopRequestConsumer = RequestConsumer[GmailSweepTopRequest]


@dataclass
class GmailSweepTopResult:
    top_senders: List[Tuple[str, int]]
    freq_days: int
    inbox_only: bool
    out_path: Optional[Path]


class GmailSweepTopProcessor(SafeProcessor[GmailSweepTopRequest, GmailSweepTopResult]):
    def __init__(self, service_builder=None) -> None:
        self._service_builder = service_builder or self._default_service_builder

    def _default_service_builder(self, auth: GmailAuth):
        return GmailServiceBuilder.build(auth)

    def _process_safe(self, payload: GmailSweepTopRequest) -> GmailSweepTopResult:
        svc = self._service_builder(payload.auth)
        query = GmailService.build_query(
            explicit=payload.query,
            from_text=payload.from_text,
            days=payload.days,
            inbox_only=payload.inbox_only,
        )
        ids = svc.list_message_ids(query=query, max_pages=payload.pages, page_size=payload.page_size)
        if not ids:
            return GmailSweepTopResult(top_senders=[], freq_days=payload.days, inbox_only=payload.inbox_only, out_path=payload.out_path)
        freq = self._count_senders(svc, ids)
        top = freq.most_common(max(1, payload.top))
        return GmailSweepTopResult(
            top_senders=top,
            freq_days=payload.days,
            inbox_only=payload.inbox_only,
            out_path=payload.out_path,
        )

    def _count_senders(self, svc, ids: List[str]) -> collections.Counter:
        """Count sender frequencies from message IDs."""
        freq: collections.Counter = collections.Counter()
        for mid in ids:
            sender = self._extract_sender(svc, mid)
            if sender:
                freq[sender] += 1
        return freq

    def _extract_sender(self, svc, mid: str) -> Optional[str]:
        """Extract sender email address from a message."""
        try:
            msg = svc.get_message(mid)
        except Exception:  # nosec B112 - skip unreadable messages
            return None
        return self._parse_sender_from_message(msg)

    def _parse_sender_from_message(self, msg: Dict[str, Any]) -> Optional[str]:
        """Parse sender from Gmail message dict."""
        payload_data = msg.get("payload") or {}
        headers = payload_data.get("headers") or []
        for header in headers:
            if (header.get("name") or "").lower() == "from":
                return extract_email_address(header.get("value") or "")
        # Fallback: check top-level 'from' field
        if isinstance(msg, dict) and msg.get("from"):
            return extract_email_address(str(msg["from"]))
        return None


class GmailSweepTopProducer(BaseProducer):
    def _produce_success(self, payload: GmailSweepTopResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        top = payload.top_senders
        if not top:
            print("No sender stats available.")
            return
        print(f"Top {len(top)} sender(s) in last {payload.freq_days}d (Inbox={payload.inbox_only}):")
        for sender, count in top:
            print(f"- {sender}: {count}")
        if payload.out_path:
            from calendars.yamlio import dump_config

            filters = []
            for sender, _ in top:
                filters.append(
                    {
                        "name": f"Auto-archive {sender}",
                        "provider": "gmail",
                        "query": f"from:{sender}",
                        "actions": {
                            "archive": True,
                            "mark_read": True,
                            "labels": ["Sweep/Auto-Archive"],
                        },
                    }
                )
            dump_config(str(payload.out_path), {"filters": filters})
            print(f"Wrote suggested Gmail filters to {payload.out_path}")
